"""Chart-of-accounts codecs, registered with the shared translation layer on import.

``account_status``  Zoho's ``is_active`` boolean ↔ our one lifecycle column ``status``
                    (``active`` / ``inactive``). Zoho sends the boolean as a JSON bool on
                    the documented endpoints and as the string ``"true"`` on some
                    undocumented ones — the tolerant bool parser takes both. Outbound,
                    Zoho changes activity through ``POST /chartofaccounts/{id}/active`` /
                    ``/inactive``, never the body, so the field is IN-only and the encoder
                    exists only for symmetry.
"""

from __future__ import annotations

from typing import Any

from app.modules.sync.translation import CODECS, Codec, register_codec


def _dec_status(value: Any) -> str | None:
    flag = CODECS["bool"].decode(value)
    if flag is None:
        return None
    return "active" if flag else "inactive"


def _enc_status(value: Any) -> bool | None:
    if value is None:
        return None
    return str(value) == "active"


register_codec(Codec("account_status", _dec_status, _enc_status))
