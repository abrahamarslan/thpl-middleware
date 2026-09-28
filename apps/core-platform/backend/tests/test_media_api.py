"""Avatar upload/delete and the unauthenticated public media router, end to end.

Real Postgres, real Pillow, real tenancy (two tenants), local disk for bytes.
The design's verification checklist maps onto these tests one to one — see the
`test_*` names for: local upload, private 404, driver switch, replace + GC
window, >40 MP rejection, GPS EXIF strip.
"""

import asyncio
import io
import os

import pytest
from PIL import Image
from sqlalchemy import select

from app.modules.media import service, storage
from app.modules.media.conversions import USER_AVATAR_CONVERSIONS
from app.modules.media.model import Media
from tests.media_fixtures import run_pipeline
from tests.media_helpers import has_any_exif, has_exif_gps, make_huge_png, make_jpeg, make_png

AVATAR = "/api/me/avatar"


async def _upload(client, headers, data: bytes, *, name="me.jpg", ctype="image/jpeg"):
    resp = await client.post(AVATAR, files={"file": (name, data, ctype)}, headers=headers)
    assert resp.status_code < 500 and resp.status_code != 409, f"unexpected {resp.status_code}: {resp.text}"
    return resp


async def _rows(db, *, user_id: int, include_deleted=True) -> list[Media]:
    stmt = select(Media).where(Media.model_type == "user", Media.model_id == user_id).order_by(Media.id)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return list((await db.execute(stmt.execution_options(populate_existing=True))).scalars().all())


class FakeGarage:
    """An in-memory stand-in for the garage disk, to prove per-row `disk` routing."""

    disk = "garage"

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.reads = 0

    async def save(self, data, key, content_type, *, visibility="public"):
        self.objects[(visibility, key)] = data

    async def read(self, key, *, visibility="public"):
        self.reads += 1
        try:
            return self.objects[(visibility, key)]
        except KeyError:
            raise FileNotFoundError(key) from None

    async def delete(self, key, *, visibility="public"):
        self.objects.pop((visibility, key), None)

    async def exists(self, key, *, visibility="public"):
        return (visibility, key) in self.objects


# ── upload ───────────────────────────────────────────────────────────────────

async def test_upload_stores_a_clean_public_original_and_queues_every_variant(worlds, media_env, db):
    client, acme, _ = worlds
    raw = make_jpeg(size=(600, 400), gps=True, orientation=6)
    assert has_exif_gps(raw)

    resp = await _upload(client, acme.auth(acme.admin), raw)

    assert resp.status_code == 202, resp.text
    body = resp.json()["data"]
    media_id = body["media_id"]
    assert body["status"] == "pending"
    assert body["avatar_urls"] == {
        "original": f"https://media.test/public/m/{media_id}/original",
        "thumb": None, "medium": None, "large": None,             # not generated yet: the client polls
    }

    (row,) = await _rows(db, user_id=acme.admin.id)
    assert (row.disk, row.visibility, row.status, row.collection) == ("local", "public", "pending", "avatar")
    assert row.tenant_id == acme.tenant.id and row.organization_id == acme.organization.id
    assert row.created_by == acme.admin.id
    assert row.file_name == f"{media_id}/original.jpeg"
    assert media_env.dispatched == [(media_id, USER_AVATAR_CONVERSIONS)]

    stored = (media_env.base / "public" / media_id / "original.jpeg").read_bytes()
    assert len(stored) == row.size_bytes
    assert not has_exif_gps(stored) and not has_any_exif(stored)           # GPS never reaches storage
    with Image.open(io.BytesIO(stored)) as img:
        assert img.size == (400, 600)                                      # orientation baked in


async def test_full_flow_upload_convert_serve(worlds, media_env, db):
    client, acme, _ = worlds
    resp = await _upload(client, acme.auth(acme.admin), make_jpeg(size=(900, 600), gps=True))
    media_id = resp.json()["data"]["media_id"]

    await run_pipeline(media_id, USER_AVATAR_CONVERSIONS)

    # the profile now lists every variant, so a client polling it sees "ready"
    profile = await client.get("/api/me/profile", headers=acme.auth(acme.admin))
    assert profile.status_code == 200, profile.text
    urls = profile.json()["data"]["avatar_urls"]
    assert urls == {v: f"https://media.test/public/m/{media_id}/{v}" for v in ("original", "thumb", "medium", "large")}

    # ... and they are served with NO credentials at all, from the same client minus the header
    for variant, side in (("thumb", 150), ("medium", 400), ("large", 800)):
        r = await client.get(f"/public/m/{media_id}/{variant}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/webp"
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert r.headers["cross-origin-resource-policy"] == "cross-origin"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["etag"]
        with Image.open(io.BytesIO(r.content)) as img:
            assert img.size == (side, side)
    original = await client.get(f"/public/m/{media_id}/original")
    assert original.status_code == 200 and original.headers["content-type"] == "image/jpeg"
    assert not has_exif_gps(original.content)


async def test_the_public_router_needs_no_auth_and_ignores_tenant_context(worlds, media_env, db):
    """ACME's avatar is fetched by an anonymous caller — and even by a request that
    happens to carry ANOTHER tenant's token, since the route never reads it."""
    client, acme, globex = worlds
    media_id = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]

    anonymous = await client.get(f"/public/m/{media_id}/original")
    as_globex = await client.get(f"/public/m/{media_id}/original", headers=globex.auth(globex.admin))
    assert anonymous.status_code == as_globex.status_code == 200
    assert anonymous.content == as_globex.content


@pytest.mark.parametrize(("path_suffix", "status"), [("medium", 200), ("medium.webp", 200), ("medium.png", 404),
                                                     ("original.jpeg", 200), ("original.webp", 404)])
async def test_variant_extension_is_optional_but_must_match(worlds, media_env, db, path_suffix, status):
    client, acme, _ = worlds
    media_id = (await _upload(client, acme.auth(acme.admin), make_jpeg(gps=False))).json()["data"]["media_id"]
    await run_pipeline(media_id, USER_AVATAR_CONVERSIONS)
    assert (await client.get(f"/public/m/{media_id}/{path_suffix}")).status_code == status


async def test_conditional_get_and_head(worlds, media_env, db):
    client, acme, _ = worlds
    media_id = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]
    first = await client.get(f"/public/m/{media_id}/original")
    etag = first.headers["etag"]

    cached = await client.get(f"/public/m/{media_id}/original", headers={"If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b""
    assert cached.headers["cache-control"] == first.headers["cache-control"]
    stale = await client.get(f"/public/m/{media_id}/original", headers={"If-None-Match": '"something-else"'})
    assert stale.status_code == 200

    head = await client.head(f"/public/m/{media_id}/original")
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-type"] == "image/png"


# ── everything that is not a public, ready image is a plain 404 ──────────────

async def test_private_and_unknown_and_not_ready_are_indistinguishable_404s(worlds, media_env, db):
    client, acme, _ = worlds
    ready = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]

    private = Media(
        model_type="user", model_id=acme.admin.id, collection="documents", disk="local", visibility="private",
        file_name="x/original.png", mime_type="image/png", size_bytes=10, tenant_id=acme.tenant.id,
        organization_id=acme.organization.id,
    )
    db.add(private)
    await db.commit()
    (media_env.base / "private" / "x").mkdir(parents=True)
    (media_env.base / "private" / "x" / "original.png").write_bytes(make_png())     # the bytes DO exist

    probes = [
        f"/public/m/{private.uuid}/original",                       # exists, but private   -> 404 (never 403)
        "/public/m/3b241101-e2bb-4255-8caf-4136c566a962/original",  # never existed
        "/public/m/not-a-uuid/original",                            # malformed
        f"/public/m/{ready}/thumb",                                 # public, variant not generated yet
        f"/public/m/{ready}/nosuchvariant",
        f"/public/m/{ready}/UPPER",                                 # fails the variant grammar
    ]
    responses = [await client.get(p) for p in probes]

    assert {r.status_code for r in responses} == {404}
    assert len({r.content for r in responses}) == 1                 # same body: no oracle for "exists"
    assert len({r.headers.get("cache-control") for r in responses}) == 1
    assert responses[0].headers["cache-control"] == "no-store"      # an edge must not cache "not ready yet"
    assert private.uuid.hex not in responses[0].text


async def test_bytes_gone_from_disk_is_a_404_not_a_500(worlds, media_env, db):
    client, acme, _ = worlds
    media_id = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]
    (media_env.base / "public" / media_id / "original.png").unlink()
    assert (await client.get(f"/public/m/{media_id}/original")).status_code == 404


# ── driver switch ────────────────────────────────────────────────────────────

async def test_flipping_the_driver_never_breaks_urls_already_issued(worlds, media_env, db, monkeypatch):
    """The regression the per-row `disk` exists for: an avatar uploaded while the
    driver was `garage` must still resolve after the env flips to `local`, and
    vice versa — the router reads `media.disk`, never MEDIA_STORAGE_DRIVER."""
    client, acme, _ = worlds
    fake = FakeGarage()
    storage._provider_cache["garage"] = fake

    monkeypatch.setattr(storage.settings, "MEDIA_STORAGE_DRIVER", "garage")          # env says garage ...
    on_garage = (await _upload(client, acme.auth(acme.admin), make_png(color=(1, 2, 3)))).json()["data"]["media_id"]
    monkeypatch.setattr(storage.settings, "MEDIA_STORAGE_DRIVER", "local")           # ... then local ...
    on_local = (await _upload(client, acme.auth(acme.member), make_png(color=(9, 8, 7)))).json()["data"]["media_id"]

    (garage_row,) = await _rows(db, user_id=acme.admin.id)
    (local_row,) = await _rows(db, user_id=acme.member.id)
    assert (garage_row.disk, local_row.disk) == ("garage", "local")
    assert (("public", f"{on_garage}/original.png") in fake.objects)                 # bytes really went to garage
    assert not (media_env.base / "public" / on_garage).exists()                      # ... and NOT to local disk

    # now flip the driver the other way and fetch BOTH: each still comes from its own disk
    monkeypatch.setattr(storage.settings, "MEDIA_STORAGE_DRIVER", "local")
    r_garage = await client.get(f"/public/m/{on_garage}/original")
    monkeypatch.setattr(storage.settings, "MEDIA_STORAGE_DRIVER", "garage")
    r_local = await client.get(f"/public/m/{on_local}/original")

    assert r_garage.status_code == 200 and fake.reads >= 1
    assert r_local.status_code == 200
    assert r_garage.content != r_local.content


async def test_new_uploads_follow_the_configured_driver(worlds, media_env, db, monkeypatch):
    client, acme, _ = worlds
    fake = FakeGarage()
    storage._provider_cache["garage"] = fake
    monkeypatch.setattr(storage.settings, "MEDIA_STORAGE_DRIVER", "garage")

    media_id = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]

    assert ("public", f"{media_id}/original.png") in fake.objects
    assert not media_env.base.exists() or not any(media_env.base.rglob("*"))


# ── replace / delete ─────────────────────────────────────────────────────────

async def test_replacing_an_avatar_mints_a_new_id_and_soft_deletes_the_old_one(worlds, media_env, db):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    first = (await _upload(client, h, make_png(color=(1, 1, 1)))).json()["data"]["media_id"]
    second = (await _upload(client, h, make_png(color=(2, 2, 2)))).json()["data"]["media_id"]
    third = (await _upload(client, h, make_png(color=(3, 3, 3)))).json()["data"]["media_id"]
    assert len({first, second, third}) == 3

    rows = {str(r.uuid): r for r in await _rows(db, user_id=acme.admin.id)}
    assert rows[first].deleted_at is not None and rows[second].deleted_at is not None
    assert rows[first].deleted_reason == "replaced"
    assert rows[third].deleted_at is None

    # the bytes of the replaced images are still there: GC, not the request, removes them (24 h later)
    for old in (first, second):
        assert (media_env.base / "public" / old / "original.png").is_file()
    # the origin stops serving a replaced id at once; only the newest is live
    assert (await client.get(f"/public/m/{first}/original")).status_code == 404
    assert (await client.get(f"/public/m/{third}/original")).status_code == 200
    profile = (await client.get("/api/me/profile", headers=h)).json()["data"]
    assert profile["avatar_urls"]["original"].endswith(f"/{third}/original")


async def test_each_user_has_their_own_avatar(worlds, media_env, db):
    client, acme, globex = worlds
    a = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]
    b = (await _upload(client, globex.auth(globex.admin), make_png())).json()["data"]["media_id"]
    assert (await _rows(db, user_id=acme.admin.id))[0].deleted_at is None              # not replaced by GLOBEX's
    assert a != b


async def test_delete_avatar_is_idempotent_and_removes_it_from_the_profile(worlds, media_env, db):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    media_id = (await _upload(client, h, make_png())).json()["data"]["media_id"]

    assert (await client.delete(AVATAR, headers=h)).status_code == 204
    assert (await client.delete(AVATAR, headers=h)).status_code == 204                # nothing left: still fine
    await db.commit()          # the harness overrides get_db (which commits in production)

    (row,) = await _rows(db, user_id=acme.admin.id)
    assert row.deleted_at is not None
    assert (await client.get(f"/public/m/{media_id}/original")).status_code == 404
    profile = (await client.get("/api/me/profile", headers=h)).json()["data"]
    assert profile["avatar_urls"] is None


# ── rejections: nothing persisted, nothing queued ───────────────────────────

async def _assert_nothing_happened(db, media_env, user_id):
    assert await _rows(db, user_id=user_id) == []
    assert media_env.dispatched == []
    assert not media_env.base.exists() or not any(p.is_file() for p in media_env.base.rglob("*"))


async def test_more_than_40_megapixels_is_rejected_before_storage_and_celery(worlds, media_env, db):
    client, acme, _ = worlds
    resp = await _upload(client, acme.auth(acme.admin), make_huge_png(), name="big.png", ctype="image/png")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_media" and "megapixels" in resp.json()["msg"]
    await _assert_nothing_happened(db, media_env, acme.admin.id)


@pytest.mark.parametrize(("data", "ctype", "fragment"), [
    (b"definitely not an image", "image/png", "invalid"),
    (make_png(), "image/gif", "unsupported image type"),
    (make_png(), "application/pdf", "unsupported image type"),
    (make_png(size=(300, 300))[:120], "image/png", "invalid"),                       # truncated
])
async def test_bad_uploads_are_400s(worlds, media_env, db, data, ctype, fragment):
    client, acme, _ = worlds
    resp = await _upload(client, acme.auth(acme.admin), data, ctype=ctype)
    assert resp.status_code == 400 and fragment in resp.json()["msg"]
    await _assert_nothing_happened(db, media_env, acme.admin.id)


async def test_files_over_10_mb_are_rejected(worlds, media_env, db):
    client, acme, _ = worlds
    resp = await _upload(client, acme.auth(acme.admin), b"\x00" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 400 and "too large" in resp.json()["msg"]
    await _assert_nothing_happened(db, media_env, acme.admin.id)


async def test_a_rejected_replacement_leaves_the_current_avatar_alone(worlds, media_env, db):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    good = (await _upload(client, h, make_png())).json()["data"]["media_id"]
    assert (await _upload(client, h, b"garbage")).status_code == 400
    (row,) = await _rows(db, user_id=acme.admin.id)
    assert str(row.uuid) == good and row.deleted_at is None


async def test_upload_requires_authentication(worlds, media_env, db):
    client, *_ = worlds
    assert (await client.post(AVATAR, files={"file": ("a.png", make_png(), "image/png")})).status_code in (401, 403)
    assert (await client.delete(AVATAR)).status_code in (401, 403)
    assert media_env.dispatched == []


# ── failure handling ─────────────────────────────────────────────────────────

async def test_a_broker_outage_does_not_fail_the_upload(worlds, media_env, db, monkeypatch):
    client, acme, _ = worlds

    def boom(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(service, "_dispatch_conversions", boom)
    resp = await _upload(client, acme.auth(acme.admin), make_png())

    assert resp.status_code == 202                                     # the original is safely stored
    (row,) = await _rows(db, user_id=acme.admin.id)
    assert row.status == "pending"


async def test_a_database_failure_leaves_no_orphan_bytes(worlds, media_env, db, monkeypatch):
    client, acme, _ = worlds

    async def boom(*_a, **_k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(service, "create_media", boom)
    with pytest.raises(RuntimeError):
        await _upload(client, acme.auth(acme.admin), make_png())

    assert not any(p.is_file() for p in media_env.base.rglob("*"))     # the saved original was cleaned up
    assert media_env.dispatched == []


# ── the same flow on a REAL Garage (skipped unless TEST_GARAGE_* is set) ─────

@pytest.mark.skipif(not os.environ.get("TEST_GARAGE_ENDPOINT"), reason="no TEST_GARAGE_ENDPOINT")
async def test_full_flow_on_real_garage(worlds, media_env, db, monkeypatch):
    """Checklist: 'Upload under garage: file lands in the public bucket; variants are
    generated there; /public/m/{id}/medium returns 200' — plus the GC purging the bucket."""
    from datetime import UTC, datetime, timedelta

    from app.modules.media import storage_common, storage_sync
    from app.tasks.media import gc_deleted_media

    client, acme, _ = worlds
    for name, value in (
        ("MEDIA_STORAGE_DRIVER", "garage"),
        ("S3_ENDPOINT_URL", os.environ["TEST_GARAGE_ENDPOINT"]),
        ("S3_ACCESS_KEY_ID", os.environ["TEST_GARAGE_ACCESS_KEY"]),
        ("S3_SECRET_ACCESS_KEY", os.environ["TEST_GARAGE_SECRET_KEY"]),
    ):
        monkeypatch.setattr(storage_common.settings, name, value)
    await storage.verify_storage_ready()                              # the boot check, against real buckets

    media_id = (await _upload(client, acme.auth(acme.admin), make_jpeg(size=(900, 600), gps=True))).json()["data"]["media_id"]
    (row,) = await _rows(db, user_id=acme.admin.id)
    assert row.disk == "garage" and row.visibility == "public"
    assert not media_env.base.exists() or not any(media_env.base.rglob("*"))          # nothing on local disk

    await run_pipeline(media_id, USER_AVATAR_CONVERSIONS)

    sync = storage_sync.get_storage_provider_sync("garage")
    keys = [f"{media_id}/{n}" for n in ("original.jpeg", "thumb.webp", "medium.webp", "large.webp")]
    assert all(sync.exists(k, visibility="public") for k in keys)                      # in the PUBLIC bucket ...
    assert not any(sync.exists(k, visibility="private") for k in keys)                # ... and only there
    assert not has_exif_gps(sync.read(keys[0], visibility="public"))

    medium = await client.get(f"/public/m/{media_id}/medium")
    assert medium.status_code == 200 and medium.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(medium.content)) as img:
        assert img.size == (400, 400)

    # replace → old id 404s at once; 24 h later the GC empties the bucket of it
    replacement = (await _upload(client, acme.auth(acme.admin), make_png())).json()["data"]["media_id"]
    try:
        assert (await client.get(f"/public/m/{media_id}/medium")).status_code == 404
        old = next(r for r in await _rows(db, user_id=acme.admin.id) if str(r.uuid) == media_id)
        old.deleted_at = datetime.now(UTC) - timedelta(hours=25)
        await db.commit()

        assert (await asyncio.to_thread(gc_deleted_media.run))["purged"] == 1
        assert not any(sync.exists(k, visibility="public") for k in keys)
    finally:
        # The replacement's row is truncated with the test database, so nothing would ever
        # purge its bytes: delete them here or every run litters the bucket.
        sync.delete(f"{replacement}/original.png", visibility="public")
