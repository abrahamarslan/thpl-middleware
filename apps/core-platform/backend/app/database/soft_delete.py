"""Global soft-delete filtering (opt-in per model).

Three problems this solves (docs/modules-to-implement/soft-delete.md):

  1. Forgotten filters — a ``do_orm_execute`` listener injects
     ``deleted_at IS NULL`` into every SELECT touching an opted-in model
     (including relationship / selectinload loads via include_aliases).
  2. Unique constraints vs soft-deleted rows — use PARTIAL unique indexes
     (``postgresql_where=text("deleted_at IS NULL")``) on opted-in models so
     a re-created record never collides with a soft-deleted ghost.
  3. Relationship cascade destruction — soft delete is an UPDATE
     (never ``session.delete``), so FKs and children stay intact.

Opt-in, not global: legacy modules (users, files, favorites) filter
explicitly and have restore flows that SELECT deleted rows — flipping the
default under them would silently break restores. New models inherit
``SoftDeleteFilteredMixin`` instead of ``SoftDeleteMixin`` to get the
automatic filter.

Escaping the filter (restores, admin trash views, sync identity matching):

    stmt = select(Model).execution_options(include_deleted=True)
    row  = await db.get(Model, id, execution_options={"include_deleted": True})

This module is imported for its side effect (listener registration) from
app/database/db.py, so it is active in the API, Celery workers and tests.
"""

from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.database.mixins import SoftDeleteMixin


class SoftDeleteFilteredMixin(SoftDeleteMixin):
    """Soft delete + automatic ``deleted_at IS NULL`` on every SELECT.

    Inherit this (instead of SoftDeleteMixin) to opt into global filtering.
    """

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(UTC)

    def restore(self) -> None:
        self.deleted_at = None


@event.listens_for(Session, "do_orm_execute")
def _apply_soft_delete_filter(execute_state) -> None:
    """Inject the not-deleted criteria into ORM SELECTs (opt-in models only)."""
    if not execute_state.is_select:
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        # Attribute refreshes / lazy loads of an already-loaded row must not
        # be filtered away mid-flight.
        return
    if execute_state.execution_options.get("include_deleted", False):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            SoftDeleteFilteredMixin,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True,
        )
    )
