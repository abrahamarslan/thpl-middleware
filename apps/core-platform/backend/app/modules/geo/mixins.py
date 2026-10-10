"""HasAddressesMixin — an address book on any model, one line.

    class ContactPerson(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasAddressesMixin, Base): ...

An owner's addresses are its live ``geo.place_links`` (owner_type + owner_id → place), each typed
(billing, shipping, home, …). Coordinates live on the PLACE — never on the owner (Design Rule Zero,
docs/geo/README.md) — so "where is this person" is ``link.place.latitude / longitude``.

Read path: ``selectinload(Model.addresses).joinedload(PlaceLink.place)`` — one extra query per result
set. ``lazy="raise_on_sql"`` is the N+1 firewall (the house pattern). Write path: ``geo.service``
(attach / update / detach / freeze) — the relationship is ``viewonly``.

The owner type is ``address_owner_type_of(cls)``: ``__address_owner_type__`` if the model sets it,
else the snake_case class name. It must be one of ``geo.model.link.OWNER_TYPES`` (a CHECK guards the
column, so adding an owner class is a migration).
"""

from __future__ import annotations

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.geo.model.link import PlaceLink

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def address_owner_type_of(model: type) -> str:
    explicit = getattr(model, "__address_owner_type__", None)
    if explicit:
        return str(explicit)
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasAddressesMixin:
    @declared_attr
    def addresses(cls):  # noqa: N805
        return relationship(
            PlaceLink,
            primaryjoin=lambda: and_(
                cls.id == foreign(PlaceLink.owner_id),
                PlaceLink.owner_type == address_owner_type_of(cls),
                PlaceLink.deleted_at.is_(None),
                PlaceLink.valid_to.is_(None),           # current addresses; history via geo.service.address_history
            ),
            viewonly=True,
            lazy="raise_on_sql",
            order_by=lambda: (PlaceLink.link_type.asc(), PlaceLink.is_primary.desc(), PlaceLink.id.asc()),
        )


__all__ = ["HasAddressesMixin", "address_owner_type_of"]
