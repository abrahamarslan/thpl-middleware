"""Location hub — canonical places and the polymorphic address book.

Not to be confused with ``app.modules.locations``, which is the read-only
Zoho *warehouse location* mirror. That module records what Zoho said; this
one owns addresses for the whole platform and projects each Zoho location
into a usable place (``geo.places.zoho_id``).

See docs/geo/README.md.
"""
