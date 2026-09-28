"""The polymorphic orphan finders must at least RUN.

Every registry-driven table (aliases, custom-field values, categorizables, tax
assignments) has a ``find_orphan_*`` function documented as its scheduled safety net.
Three of the four declared ``text`` result columns over ``varchar`` source columns and
raised ``structure of query does not match function result type`` on every call —
which nothing noticed, because nothing called them. Running each against an empty
database is enough to catch that class of bug; the tax finder's real detection
is asserted in ``test_tax_assignments.py``.
"""

import pytest
from sqlalchemy import text

FINDERS = (
    "core.find_orphan_entity_aliases()",
    "extfields.find_orphan_field_values()",
    "core.find_orphan_categorizables()",
    "tax.find_orphan_tax_assignments()",
)


@pytest.mark.parametrize("finder", FINDERS)
async def test_the_orphan_finder_runs_and_finds_nothing_in_a_clean_database(db, finder):
    assert (await db.execute(text(f"SELECT * FROM {finder}"))).all() == []
