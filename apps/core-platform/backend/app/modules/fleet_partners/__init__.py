"""Fleet-partner module — vendor/business entities that supply vehicles/drivers.

A **fleet partner** is the legal entity (or individual) behind third-party
vehicles and personnel. It is the ``fleet_partner_id`` target of ``vehicles``
and ``employment_records``, and the subject of the ``ENTITY_PROOF`` documents
(GST/CIN) seeded in the documents catalog.
"""

from app.modules.fleet_partners.model import FleetPartner

__all__ = ["FleetPartner"]
