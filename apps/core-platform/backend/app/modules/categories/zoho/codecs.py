"""Category-specific codecs, registered with the shared translation layer on import.

``csv_list``  Zoho's ``seo_keyword`` is ONE comma-separated string
              (``"soap, bodywash"``, max 700 chars); ``core.categories.meta_keywords``
              is a JSON array of strings. Decoding splits and trims; encoding joins
              — so the outbound seam (``service.to_zoho_payload``) sends the shape
              Zoho documents, not our storage shape. A blank string is "no keywords"
              (NULL), never ``[""]``.
"""

from __future__ import annotations

from typing import Any

from app.modules.sync.translation import Codec, register_codec


def _dec_csv_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        items = [str(item).strip() for item in value]
    else:
        items = [part.strip() for part in str(value).split(",")]
    items = [item for item in items if item]
    return items or None


def _enc_csv_list(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value)


register_codec(Codec("csv_list", _dec_csv_list, _enc_csv_list))
