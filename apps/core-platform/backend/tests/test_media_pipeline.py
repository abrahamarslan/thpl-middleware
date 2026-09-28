"""The Celery side of media: variant generation, chord join, garbage collection.

Tasks are run for real (Pillow, local storage, Postgres) with the broker taken
out of the picture. Needs the scratch database — see tests/conftest.py.
"""

import asyncio
import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select, text

from app.modules.media import storage_sync
from app.modules.media.conversions import USER_AVATAR_CONVERSIONS
from app.modules.media.imaging import sanitize_original
from app.modules.media.model import Media
from app.tasks import media as media_tasks
from app.tasks.media import finalize_conversions, gc_deleted_media, gen_variant
from tests.media_fixtures import run_pipeline
from tests.media_helpers import make_jpeg

MEDIA_ORIGINAL = sanitize_original(make_jpeg(size=(900, 600), gps=False))


async def _seed(db, env, *, visibility="public", collection="avatar", model_id=1, stored=True, **fields) -> Media:
    # Explicit tenant + organization: never rely on the DEFAULT organization existing (a freshly
    # migrated database has DEFAULT-HQ; the THPL one only appears after the first fixture teardown).
    tenant_id, org_id = (await db.execute(
        text("SELECT tenant_id, id FROM org_management.organizations ORDER BY id LIMIT 1")
    )).one()
    media = Media(
        tenant_id=tenant_id, organization_id=org_id,
        model_type="user", model_id=model_id, collection=collection, disk="local", visibility=visibility,
        file_name="placeholder", mime_type="image/jpeg", size_bytes=len(MEDIA_ORIGINAL.data), **fields,
    )
    db.add(media)
    await db.flush()
    media.file_name = f"{media.uuid}/original.jpeg"
    await db.commit()
    if stored:
        storage_sync.get_storage_provider_sync("local").save(
            MEDIA_ORIGINAL.data, media.file_name, "image/jpeg", visibility=visibility,
        )
    return media


async def _row(db, media_id) -> Media:
    # populate_existing re-reads THIS row (workers wrote it behind the session's
    # back) without expiring the test's other Media instances — an expired
    # attribute would trigger a sync lazy load, which async sessions forbid.
    return (await db.execute(
        select(Media).where(Media.uuid == media_id).execution_options(include_deleted=True, populate_existing=True)
    )).scalar_one()


# ── gen_variant + finalize ───────────────────────────────────────────────────

async def test_all_variants_are_generated_and_the_row_becomes_done(db, media_env):
    media = await _seed(db, media_env)

    results = await run_pipeline(str(media.uuid), USER_AVATAR_CONVERSIONS)

    assert {r["variant"]: r["status"] for r in results} == {"thumb": "done", "medium": "done", "large": "done"}
    row = await _row(db, media.uuid)
    assert row.status == "done"
    assert set(row.conversions) == {"thumb", "medium", "large"}
    provider = storage_sync.get_storage_provider_sync("local")
    for name, side in (("thumb", 150), ("medium", 400), ("large", 800)):
        info = row.conversions[name]
        assert info["status"] == "done" and info["file_name"] == f"{media.uuid}/{name}.webp"
        assert (info["w"], info["h"]) == (side, side)
        data = provider.read(info["file_name"], visibility="public")
        assert info["size"] == len(data)
        with Image.open(io.BytesIO(data)) as img:
            assert img.format == "WEBP" and img.size == (side, side)


async def test_variants_are_written_in_the_rows_own_visibility_tree(db, media_env):
    media = await _seed(db, media_env, visibility="private", collection="documents")
    await run_pipeline(str(media.uuid), {"thumb": USER_AVATAR_CONVERSIONS["thumb"]})
    assert (media_env.base / "private" / str(media.uuid) / "thumb.webp").is_file()
    assert not (media_env.base / "public").exists()


async def test_concurrent_variant_writes_never_clobber_each_other(db, media_env):
    """Workers on different processes finish different variants of ONE media at
    once. Each merges only its own jsonb key, so N concurrent writers leave N keys
    (a read-modify-write of the whole map would keep only the last few)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.conf import settings
    from app.modules.media.repository_worker import merge_conversion

    media = await _seed(db, media_env)
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)      # one connection per writer
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def writer(name: str) -> None:
        async with factory() as s:
            await merge_conversion(s, str(media.uuid), name, {"status": "done", "file_name": f"{media.uuid}/{name}.webp"})
            await s.commit()

    names = [f"v{i}" for i in range(12)]
    await asyncio.gather(*(writer(n) for n in names))
    await engine.dispose()

    row = await _row(db, media.uuid)
    assert set(row.conversions) == set(names)
    assert all(v["status"] == "done" for v in row.conversions.values())


async def test_rerunning_a_variant_is_idempotent(db, media_env):
    media = await _seed(db, media_env)
    spec = {"thumb": USER_AVATAR_CONVERSIONS["thumb"]}
    await run_pipeline(str(media.uuid), spec)
    first = (await _row(db, media.uuid)).conversions["thumb"]
    await run_pipeline(str(media.uuid), spec)
    second = (await _row(db, media.uuid)).conversions["thumb"]
    assert first == second


async def test_processing_status_is_visible_while_variants_are_running(db, media_env):
    media = await _seed(db, media_env)
    assert (await _row(db, media.uuid)).status == "pending"
    await asyncio.to_thread(
        lambda: gen_variant.apply(args=(str(media.uuid), "thumb", USER_AVATAR_CONVERSIONS["thumb"]), throw=True).get()
    )
    assert (await _row(db, media.uuid)).status == "processing"      # finalize has not run yet


async def test_a_deleted_media_is_skipped_quietly(db, media_env):
    media = await _seed(db, media_env)
    m = await _row(db, media.uuid)
    m.soft_delete()
    await db.commit()

    result = await asyncio.to_thread(
        lambda: gen_variant.apply(args=(str(media.uuid), "thumb", USER_AVATAR_CONVERSIONS["thumb"]), throw=True).get()
    )
    assert result["status"] == "skipped"
    assert (await _row(db, media.uuid)).conversions == {}
    # and the join must not resurrect a status on it
    await asyncio.to_thread(lambda: finalize_conversions.run([result], media_id=str(media.uuid)))
    assert (await _row(db, media.uuid)).status == "pending"


async def test_a_corrupt_source_fails_at_once_without_retrying_and_the_others_still_finish(db, media_env):
    media = await _seed(db, media_env)
    # ruin the stored original
    storage_sync.get_storage_provider_sync("local").save(b"not an image", media.file_name, "image/jpeg")

    results = await run_pipeline(str(media.uuid), USER_AVATAR_CONVERSIONS)      # throw=True: nothing raised

    assert {r["status"] for r in results} == {"failed"}
    row = await _row(db, media.uuid)
    assert row.status == "partial_failure"
    assert all(v["status"] == "failed" and v["error"] for v in row.conversions.values())


async def test_one_failing_variant_does_not_block_the_others(db, media_env):
    media = await _seed(db, media_env)
    specs = {
        "thumb": USER_AVATAR_CONVERSIONS["thumb"],
        "broken": {"width": 10, "height": 10, "fit": "zoom", "format": "webp"},     # bad spec → permanent failure
    }
    results = await run_pipeline(str(media.uuid), specs)

    assert {r["variant"]: r["status"] for r in results} == {"thumb": "done", "broken": "failed"}
    row = await _row(db, media.uuid)
    assert row.status == "partial_failure"
    assert row.conversions["thumb"]["status"] == "done"
    assert row.conversions["broken"]["status"] == "failed"


async def test_transient_errors_are_retried_and_only_the_last_failure_is_recorded(db, media_env, monkeypatch):
    media = await _seed(db, media_env)
    provider = storage_sync.get_storage_provider_sync("local")

    def flaky(*_a, **_k):
        raise ConnectionError("garage unreachable")

    monkeypatch.setattr(provider, "read", flaky)
    args = (str(media.uuid), "thumb", USER_AVATAR_CONVERSIONS["thumb"])

    # first attempt: raise so Celery schedules a retry; nothing is written to the row yet
    with pytest.raises(ConnectionError):
        await asyncio.to_thread(lambda: gen_variant.run(*args))
    assert (await _row(db, media.uuid)).conversions == {}

    # last attempt: the failure is recorded and RETURNED, so the chord callback still fires
    def last_attempt():
        gen_variant.push_request(retries=gen_variant.max_retries)
        try:
            return gen_variant.run(*args)
        finally:
            gen_variant.pop_request()

    result = await asyncio.to_thread(last_attempt)
    assert result["status"] == "failed" and "unreachable" in result["error"]
    row = await _row(db, media.uuid)
    assert row.conversions["thumb"]["status"] == "failed"


async def test_finalize_marks_done_or_partial_failure(db, media_env):
    media = await _seed(db, media_env)
    mid = str(media.uuid)
    await asyncio.to_thread(lambda: finalize_conversions.run([{"variant": "a", "status": "done"}, None], media_id=mid))
    assert (await _row(db, media.uuid)).status == "done"
    await asyncio.to_thread(
        lambda: finalize_conversions.run([{"variant": "a", "status": "done"}, {"variant": "b", "status": "failed"}], media_id=mid)
    )
    assert (await _row(db, media.uuid)).status == "partial_failure"


def test_dispatch_builds_one_subtask_per_variant_joined_by_a_chord(monkeypatch):
    seen = {}

    class FakeChord:
        def __init__(self, header):
            seen["header"] = list(header)

        def __call__(self, body):
            seen["body"] = body

    monkeypatch.setattr(media_tasks, "chord", FakeChord)
    media_tasks.dispatch_conversions("abc", USER_AVATAR_CONVERSIONS)

    assert [s.args[1] for s in seen["header"]] == ["thumb", "medium", "large"]
    assert all(s.task == "app.tasks.media.gen_variant" and s.args[0] == "abc" for s in seen["header"])
    assert seen["body"].task == "app.tasks.media.finalize_conversions"
    assert seen["body"].kwargs == {"media_id": "abc"}


def test_dispatch_with_no_conversions_queues_nothing(monkeypatch):
    monkeypatch.setattr(media_tasks, "chord", lambda *_a, **_k: pytest.fail("no chord for an empty collection"))
    media_tasks.dispatch_conversions("abc", {})


# ── garbage collection ───────────────────────────────────────────────────────

async def _soft_delete(db, media: Media, age: timedelta) -> None:
    row = await _row(db, media.uuid)
    row.deleted_at = datetime.now(UTC) - age
    await db.commit()


async def _count(db) -> int:
    return (await db.execute(text("SELECT count(*) FROM media.items"))).scalar_one()


async def test_gc_purges_only_after_the_24h_grace_window(db, media_env):
    old = await _seed(db, media_env, model_id=1)
    recent = await _seed(db, media_env, model_id=2)
    live = await _seed(db, media_env, model_id=3)
    for m in (old, recent, live):
        await run_pipeline(str(m.uuid), USER_AVATAR_CONVERSIONS)
    await _soft_delete(db, old, timedelta(hours=25))
    await _soft_delete(db, recent, timedelta(hours=1))

    result = await asyncio.to_thread(gc_deleted_media.run)

    assert result == {"purged": 1, "failed": 0}
    assert await _count(db) == 2
    # every byte of the purged media is gone: original + all variants ...
    assert not (media_env.base / "public" / str(old.uuid)).exists() or not any(
        (media_env.base / "public" / str(old.uuid)).iterdir()
    )
    # ... and nothing else was touched
    for kept in (recent, live):
        for name in ("original.jpeg", "thumb.webp", "medium.webp", "large.webp"):
            assert (media_env.base / "public" / str(kept.uuid) / name).is_file()


async def test_gc_is_not_run_on_a_replaced_avatar_immediately(db, media_env):
    media = await _seed(db, media_env)
    await _soft_delete(db, media, timedelta(minutes=5))
    assert (await asyncio.to_thread(gc_deleted_media.run))["purged"] == 0
    assert await _count(db) == 1


async def test_one_unreachable_disk_does_not_stall_the_sweep(db, media_env, monkeypatch):
    good = await _seed(db, media_env, model_id=1)
    await run_pipeline(str(good.uuid), {"thumb": USER_AVATAR_CONVERSIONS["thumb"]})
    stranded = await _seed(db, media_env, model_id=2, stored=False)
    stranded_row = await _row(db, stranded.uuid)
    stranded_row.disk = "garage"                       # not configured in the test env → provider init fails
    await db.commit()
    for m in (good, stranded):
        await _soft_delete(db, m, timedelta(hours=30))

    from app.modules.media import storage_common

    monkeypatch.setattr(storage_common.settings, "S3_ACCESS_KEY_ID", "")
    result = await asyncio.to_thread(gc_deleted_media.run)

    assert result == {"purged": 1, "failed": 1}
    assert await _count(db) == 1                       # the stranded row stays for the next sweep


# ── rescuing rows a crash left half-done ─────────────────────────────────────

async def _age(db, media: Media, *, idle: timedelta, created: timedelta | None = None) -> None:
    await db.execute(
        text("UPDATE media.items SET updated_at = now() - make_interval(secs => :i), "
             "created_at = now() - make_interval(secs => :c) WHERE uuid = :u"),
        {"i": idle.total_seconds(), "c": (created or idle).total_seconds(), "u": media.uuid},
    )
    await db.commit()


@pytest.fixture
def dispatched(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(media_tasks, "dispatch_conversions", lambda mid, conv: calls.append((mid, conv)))
    return calls


async def test_a_row_idle_in_pending_is_requeued_with_every_missing_variant(db, media_env, dispatched):
    stuck = await _seed(db, media_env)                       # e.g. the broker was down at upload time
    await _age(db, stuck, idle=timedelta(minutes=30))

    result = await asyncio.to_thread(media_tasks.requeue_stuck_media.run)

    assert result == {"requeued": 1, "finished": 0, "gave_up": 0}
    assert dispatched == [(str(stuck.uuid), USER_AVATAR_CONVERSIONS)]
    # touched, so the next tick leaves it alone while the re-queued work runs
    assert (await asyncio.to_thread(media_tasks.requeue_stuck_media.run))["requeued"] == 0


async def test_only_the_variants_that_are_not_done_are_requeued(db, media_env, dispatched):
    stuck = await _seed(db, media_env)
    # the worker died after ONE variant: no other variant ran and finalize never fired
    await asyncio.to_thread(
        lambda: gen_variant.apply(args=(str(stuck.uuid), "thumb", USER_AVATAR_CONVERSIONS["thumb"]), throw=True).get()
    )
    await _age(db, stuck, idle=timedelta(minutes=30))

    await asyncio.to_thread(media_tasks.requeue_stuck_media.run)

    ((_, specs),) = dispatched
    assert set(specs) == {"medium", "large"}


async def test_a_row_whose_variants_all_finished_only_needs_its_status(db, media_env, dispatched):
    stuck = await _seed(db, media_env)
    await asyncio.to_thread(lambda: [
        gen_variant.apply(args=(str(stuck.uuid), n, s), throw=True).get() for n, s in USER_AVATAR_CONVERSIONS.items()
    ])                                                       # all done, but finalize never ran (worker killed)
    await _age(db, stuck, idle=timedelta(minutes=30))

    result = await asyncio.to_thread(media_tasks.requeue_stuck_media.run)

    assert result["finished"] == 1 and dispatched == []
    assert (await _row(db, stuck.uuid)).status == "done"


async def test_rows_that_are_recent_deleted_or_finished_are_left_alone(db, media_env, dispatched):
    fresh = await _seed(db, media_env, model_id=1)                                   # just uploaded: a worker is about to start
    deleted = await _seed(db, media_env, model_id=2)
    done = await _seed(db, media_env, model_id=3)
    await run_pipeline(str(done.uuid), USER_AVATAR_CONVERSIONS)
    for m in (deleted, done):
        await _age(db, m, idle=timedelta(hours=2))
    (await _row(db, deleted.uuid)).soft_delete()
    await db.commit()
    assert fresh is not None

    result = await asyncio.to_thread(media_tasks.requeue_stuck_media.run)

    assert result == {"requeued": 0, "finished": 0, "gave_up": 0} and dispatched == []


async def test_a_poison_row_is_given_up_on_after_24_hours(db, media_env, dispatched):
    stuck = await _seed(db, media_env)
    await _age(db, stuck, idle=timedelta(hours=3), created=timedelta(hours=25))

    result = await asyncio.to_thread(media_tasks.requeue_stuck_media.run)

    assert result == {"requeued": 0, "finished": 0, "gave_up": 1} and dispatched == []
    assert (await _row(db, stuck.uuid)).status == "partial_failure"


async def test_a_collection_with_no_conversions_has_nothing_to_wait_for(db, media_env, dispatched):
    stuck = await _seed(db, media_env, collection="documents", visibility="private")
    await _age(db, stuck, idle=timedelta(minutes=30))
    result = await asyncio.to_thread(media_tasks.requeue_stuck_media.run)
    assert result["finished"] == 1 and dispatched == []
    assert (await _row(db, stuck.uuid)).status == "done"


def test_the_sweeper_is_scheduled():
    from app.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["requeue-stuck-media"]
    assert entry["task"] == "app.tasks.media.requeue_stuck_media"
    assert entry["schedule"] < media_tasks.STUCK_IDLE          # ticks more often than a row counts as stuck
