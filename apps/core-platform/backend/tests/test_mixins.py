"""Opt-in mixins: PolymorphicOwnerMixin and HashGuardMixin (app/database/mixins.py).

The hash-guard upsert is exercised against a real PostgreSQL — ``IS DISTINCT
FROM`` inside ``ON CONFLICT DO UPDATE ... WHERE`` is exactly the behaviour the
mixin's docstring promises, so it is tested, not assumed.
"""

from sqlalchemy import CheckConstraint, Index, String, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database.mixins import (
    HashGuardMixin,
    IntPKMixin,
    PolymorphicOwnerMixin,
    TimestampMixin,
)


class _Base(DeclarativeBase):
    """Private metadata: keeps these scratch tables out of the app's Base, whose
    tables the tenancy conformance test audits and Alembic diffs."""


class _Note(IntPKMixin, PolymorphicOwnerMixin, TimestampMixin, _Base):
    __tablename__ = "t_mixin_notes"
    __table_args__ = (
        CheckConstraint("owner_type IN ('user','vehicle')", name="chk_t_mixin_notes_owner_type"),
        Index("ix_t_mixin_notes_owner", "owner_type", "owner_id"),
    )
    body: Mapped[str] = mapped_column(String(100))


class _Record(IntPKMixin, HashGuardMixin, TimestampMixin, _Base):
    __tablename__ = "t_mixin_records"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))


# ── PolymorphicOwnerMixin ───────────────────────────────────────────────────

def test_polymorphic_owner_columns_are_required_and_have_no_single_column_index():
    cols = _Note.__table__.c
    assert not cols.owner_type.nullable and not cols.owner_id.nullable
    assert cols.owner_type.type.length == 50
    assert not cols.owner_type.index and not cols.owner_id.index
    assert not cols.owner_type.foreign_keys and not cols.owner_id.foreign_keys


def test_owner_ref_pairs_type_and_id():
    assert _Note(owner_type="vehicle", owner_id=9, body="x").owner_ref == ("vehicle", 9)


# ── HashGuardMixin ──────────────────────────────────────────────────────────

def test_hash_is_stable_across_key_order_and_ignores_excluded_keys():
    a = {"code": "A", "name": "Alpha", "synced_at": "2026-09-20T10:00"}
    b = {"synced_at": "2026-09-20T11:30", "name": "Alpha", "code": "A"}
    h = HashGuardMixin.hash_content
    assert h(a, exclude=["synced_at"]) == h(b, exclude=["synced_at"])
    assert h(a) != h(b)                                              # without the exclusion they differ
    assert h(a, exclude=["synced_at"]) != h({**a, "name": "Beta"}, exclude=["synced_at"])
    assert len(h(a)) == 64 and int(h(a), 16) >= 0                    # sha256 hex fits String(64)


def test_hash_stringifies_values_json_cannot_encode():
    from datetime import date
    from decimal import Decimal

    assert HashGuardMixin.hash_content({"d": date(2026, 9, 20), "n": Decimal("1.50")})


async def test_hash_guarded_upsert_skips_unchanged_rows_and_rewrites_changed_ones(db):
    # DDL is transactional in PostgreSQL: the table lives and dies with the
    # test's session (the db fixture rolls back), so nothing leaks.
    await db.run_sync(lambda session: _Record.__table__.create(session.connection()))

    def upsert(name: str, content_hash: str | None):
        stmt = insert(_Record).values(code="A", name=name, content_hash=content_hash)
        return stmt.on_conflict_do_update(
            index_elements=[_Record.code],
            set_={"name": stmt.excluded.name, "content_hash": stmt.excluded.content_hash,
                  "updated_at": func.clock_timestamp()},
            where=_Record.content_hash.is_distinct_from(stmt.excluded.content_hash),
        )

    h1 = HashGuardMixin.hash_content({"code": "A", "name": "Alpha"})
    h2 = HashGuardMixin.hash_content({"code": "A", "name": "Beta"})

    await db.execute(upsert("Alpha", h1))
    first = (await db.execute(select(_Record.updated_at, _Record.name))).one()

    await db.execute(upsert("Alpha", h1))                            # same hash → no write
    assert (await db.execute(select(_Record.updated_at, _Record.name))).one() == first

    await db.execute(upsert("Beta", h2))                             # changed → written
    second = (await db.execute(select(_Record.updated_at, _Record.name))).one()
    assert second.name == "Beta" and second.updated_at > first.updated_at

    await db.execute(_Record.__table__.update().values(content_hash=None))
    await db.execute(upsert("Beta", h2))                             # NULL hash is rewritten once, not skipped forever
    assert (await db.scalar(select(_Record.content_hash))) == h2
