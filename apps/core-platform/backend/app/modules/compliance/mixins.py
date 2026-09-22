"""Compliance mixins — pure schema only (no relationships, no I/O)."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class ConsentBoundMixin:
    """Links a consent-worthy row to its authorizing ``ConsentRecord``.

    Deliberately a single nullable FK and nothing else: consent itself is a
    first-class table (history + withdrawal), and mixins must not carry
    relationships. The service loads the consent row when it needs it.
    """

    consent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("consent_records.id", ondelete="SET NULL"), index=True,
        comment="The consent that authorized this record",
    )
