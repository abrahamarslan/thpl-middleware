"""The translation layer — the anti-corruption boundary, in both directions.

Every record that crosses the boundary crosses it here: a Zoho payload becoming
our canonical columns, and our row becoming a Zoho write payload. No module
reads a source payload directly, and no module hand-builds one.

This is the **Translator** of the classic anti-corruption layer (façade +
adapter + translator): the adapter owns HTTP, auth and retries; the translator
owns meaning, and nothing else. It is also EIP's *Message Translator* sitting
either side of a *Canonical Data Model* — `currency.currencies` is the
canonical model, and each source gets a translator, never its own table.

### The one rule that shapes the design

**The write direction is never the inverted read direction.** It is tempting to
declare one field map and run it backwards, and it is wrong in practice:

    currency_id       Zoho's, read-only — sending it back is an error
    currency_name     Zoho COMPUTES it ("AUD- Australian Dollar") from the code
    is_base_currency  set by organization settings, not by this endpoint
    currency_format   REQUIRED on create, optional on update

A single symmetric map cannot express any of that, so a field declares its
``direction`` (IN / OUT / BOTH) and carries a ``codec`` whose ``decode`` and
``encode`` are written separately, not derived from each other.

### Shapes and intents

Reads differ by **shape**: an INDEX row is thinner than a DETAIL document, and
a NESTED one thinner still. The gate already refuses to let a thin payload
overwrite a rich one; the translator's job is only to never invent a value that
was not sent — a missing key is skipped, never decoded to NULL.

Writes differ by **intent**: Zoho's create and update argument lists are not
the same, so ``required_on_create`` is checked for CREATE and ignored for
UPDATE. A payload that would be rejected by Zoho is refused here, with the
missing fields named, rather than spent as a failed API call.

### Failure doctrine

Decoding never raises: a field that cannot be translated is dropped and
reported in ``Decoded.warnings``, because a single malformed attribute must not
cost us the record (every business column is nullable by schema rule).
Encoding *does* raise — we are about to make an outbound call, and a payload we
know to be invalid is a bug worth stopping for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol

import structlog
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

logger = structlog.get_logger("app.sync.translation")

#: Distinguishes "key absent" from "key present and null" — a missing key is
#: skipped so a partial payload can never erase data we already hold.
MISSING: Any = object()


class Direction(StrEnum):
    """Which way a field is allowed to travel."""

    IN = "in"        # source → us only (read-only upstream: ids, computed names)
    OUT = "out"      # us → source only (write-only: rarely, but it happens)
    BOTH = "both"


class PayloadShape(StrEnum):
    """How complete the payload being decoded is."""

    INDEX = "index"        # a list row
    DETAIL = "detail"      # the full document
    NESTED = "nested"      # embedded inside a parent payload
    WEBHOOK = "webhook"

    @classmethod
    def of(cls, source: str | None) -> PayloadShape:
        """Map the engine's provenance string onto a shape."""
        if not source:
            return cls.INDEX
        if source.startswith("nested:"):
            return cls.NESTED
        if source.startswith("list:"):
            return cls.INDEX
        if source == "webhook":
            return cls.WEBHOOK
        return cls.DETAIL


class WriteIntent(StrEnum):
    """Which outbound argument list applies."""

    CREATE = "create"
    UPDATE = "update"


class TranslationError(ValueError):
    """An outbound payload could not be built (missing required arguments)."""


# ── codecs: decode and encode written separately, on purpose ────────────────

@dataclass(frozen=True, slots=True)
class Codec:
    """A named pair of one-way conversions.

    ``encode`` is NOT the inverse of ``decode``: ``zoho_date`` decodes
    ``"2013-09-04"`` into a ``date`` and encodes a ``date`` back into Zoho's
    string form, but ``money`` decodes into ``Decimal`` (never float — rates
    are money) and encodes into a JSON number, because that is what the wire
    wants in each direction.
    """

    name: str
    decode: Callable[[Any], Any]
    encode: Callable[[Any], Any]


def _dec_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dec_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value).strip())


def _dec_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "y", "active")


def _dec_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc


def _enc_number(value: Any) -> Any:
    """Decimal → JSON number, without the float round-trip where avoidable."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _dec_date(value: Any) -> date | None:
    parsed = _dec_datetime(value)
    return parsed.date() if parsed else None


def _dec_datetime(value: Any) -> datetime | None:
    if value in (None, "", " "):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _enc_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _enc_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dec_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(str(value).strip())


_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")


def _dec_month_index(value: Any) -> int | None:
    """0-based month from an int (documented) or a name (what the live API
    actually sends: ``"april"``) — see ERRORS E34."""
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 0 <= value <= 11 else None
    text = str(value).strip().lower()
    if text.isdigit():
        return _dec_month_index(int(text))
    for index, name in enumerate(_MONTHS):
        if text in (name, name[:3]):
            return index
    return None


def _identity(value: Any) -> Any:
    return value


CODECS: dict[str, Codec] = {
    codec.name: codec
    for codec in (
        Codec("str", _dec_str, lambda v: None if v is None else str(v)),
        Codec("int", _dec_int, lambda v: None if v is None else int(v)),
        Codec("bool", _dec_bool, lambda v: None if v is None else bool(v)),
        Codec("float", _dec_float, lambda v: None if v is None else float(v)),
        Codec("decimal", _dec_decimal, _enc_number),
        Codec("money", _dec_decimal, _enc_number),
        # Zoho documents 0–11 and sends "april"; we store and send the integer.
        Codec("month_index", _dec_month_index, lambda v: None if v is None else int(v)),
        Codec("zoho_date", _dec_date, _enc_date),
        Codec("zoho_datetime", _dec_datetime, _enc_datetime),
        Codec("passthrough", _identity, _identity),
    )
}


def register_codec(codec: Codec) -> None:
    """Modules may register domain-specific codecs before their spec loads."""
    CODECS[codec.name] = codec


# ── field specification ─────────────────────────────────────────────────────

class FieldSpec(BaseModel):
    """One external-attribute ↔ canonical-column rule, direction-aware.

    Accepts the legacy keyword names (``zoho=``, ``transform=``, ``outbound=``,
    ``outbound_key=``) so every existing module spec keeps working untouched.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    #: Dotted path in the source payload ("address.city").
    external: str = Field(validation_alias=AliasChoices("external", "zoho"))
    #: Canonical column on our model.
    local: str
    #: Name in CODECS. ``transform=`` is the legacy spelling.
    codec: str | None = Field(default=None, validation_alias=AliasChoices("codec", "transform"))
    direction: Direction = Direction.BOTH
    #: Key to use on writes when it differs from the read key.
    external_write: str | None = Field(
        default=None, validation_alias=AliasChoices("external_write", "outbound_key")
    )
    #: Zoho rejects a CREATE without this argument.
    required_on_create: bool = False
    #: Shapes that carry this field; empty = all. Purely documentary today —
    #: a missing key is skipped regardless — but it records what a thin index
    #: row is expected NOT to contain, which is otherwise tribal knowledge.
    shapes: tuple[PayloadShape, ...] = ()
    default: Any = None
    apply_default_when_missing: bool = False
    #: Legacy switch; folded into ``direction`` below.
    outbound: bool | None = None

    @field_validator("external", "local")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("mapping paths must not be blank")
        return v

    @model_validator(mode="after")
    def _fold_legacy_outbound(self) -> FieldSpec:
        # outbound=False was the old way to say "never send this upstream".
        if self.outbound is False and self.direction is Direction.BOTH:
            object.__setattr__(self, "direction", Direction.IN)
        return self

    @property
    def zoho(self) -> str:
        """Legacy alias — existing code reads ``mapping.zoho``."""
        return self.external

    @property
    def transform(self) -> str | None:
        return self.codec

    @property
    def reads(self) -> bool:
        return self.direction in (Direction.IN, Direction.BOTH)

    @property
    def writes(self) -> bool:
        return self.direction in (Direction.OUT, Direction.BOTH)

    @property
    def write_key(self) -> str:
        return self.external_write or self.external


@dataclass(slots=True)
class Decoded:
    """The result of translating one inbound payload."""

    values: dict[str, Any] = field(default_factory=dict)
    #: Child collections the adapter's hook projects (e.g. exchange rates).
    children: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Fields that could not be translated. Never fatal, always visible.
    warnings: list[str] = field(default_factory=list)


class Translator(Protocol):
    """What the engine needs of any source, for any module."""

    def decode(self, payload: dict, *, shape: PayloadShape) -> Decoded: ...

    def encode(self, entity: Any, *, intent: WriteIntent) -> dict: ...


# ── payload access ──────────────────────────────────────────────────────────

def extract(payload: dict, dotted: str) -> Any:
    """Dotted-path read; MISSING when any segment is absent."""
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def assign(target: dict, dotted: str, value: Any) -> None:
    """Dotted-path write, creating intermediate objects."""
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


# ── the declarative translator ──────────────────────────────────────────────

class FieldTranslator:
    """A Translator driven by ``FieldSpec``s — what most modules need.

    A module with irreducible logic subclasses this and overrides ``decode`` or
    ``encode``, calling ``super()`` for the declarative part. That keeps the
    common case a table and the exceptional case ordinary Python, instead of
    growing the spec language until it is a worse programming language.
    """

    def __init__(self, module: str, fields: list[FieldSpec]) -> None:
        self.module = module
        self.fields = fields

    # -- inbound ------------------------------------------------------------

    def decode(self, payload: dict, *, shape: PayloadShape = PayloadShape.DETAIL) -> Decoded:
        result = Decoded()
        for spec in self.fields:
            if not spec.reads:
                continue
            raw = extract(payload, spec.external)
            if raw is MISSING:
                # A key the source did not send is not a value of NULL.
                if spec.apply_default_when_missing:
                    result.values[spec.local] = spec.default
                continue
            decoded, warning = self._decode_one(spec, raw)
            if warning is not None:
                result.warnings.append(warning)
                continue
            result.values[spec.local] = decoded
        return result

    def _decode_one(self, spec: FieldSpec, raw: Any) -> tuple[Any, str | None]:
        if raw is None:
            return spec.default, None
        if spec.codec is None:
            return raw, None
        codec = CODECS.get(spec.codec)
        if codec is None:
            logger.warning("sync.translation.unknown_codec", module=self.module,
                           codec=spec.codec, field=spec.local)
            return raw, None
        try:
            decoded = codec.decode(raw)
        except Exception:  # noqa: BLE001 — one bad field never costs the record
            logger.warning("sync.translation.decode_failed", module=self.module,
                           field=spec.local, codec=spec.codec, raw=repr(raw)[:120])
            return None, f"{spec.local}: could not decode {spec.codec} from {raw!r}"
        return (spec.default if decoded is None else decoded), None

    # -- outbound -----------------------------------------------------------

    def encode(self, entity: Any, *, intent: WriteIntent = WriteIntent.UPDATE) -> dict:
        """Canonical row → source write payload.

        Only fields this source actually accepts are included, so a read-only
        attribute (an id the source owns, a name it computes) can never be sent
        back at it.
        """
        payload: dict[str, Any] = {}
        missing: list[str] = []
        for spec in self.fields:
            if not spec.writes:
                continue
            value = getattr(entity, spec.local, None)
            if value is None:
                if intent is WriteIntent.CREATE and spec.required_on_create:
                    missing.append(f"{spec.local} (as {spec.write_key})")
                continue
            codec = CODECS.get(spec.codec) if spec.codec else None
            assign(payload, spec.write_key, codec.encode(value) if codec else value)
        if missing:
            raise TranslationError(
                f"{self.module}: cannot build a {intent.value} payload — "
                f"required argument(s) missing: {', '.join(sorted(missing))}"
            )
        return payload

    # -- introspection ------------------------------------------------------

    @property
    def readable(self) -> tuple[str, ...]:
        return tuple(spec.local for spec in self.fields if spec.reads)

    @property
    def writable(self) -> tuple[str, ...]:
        """Canonical columns this source accepts — the basis of the
        owned-field guard: a column we can push is a column we may own."""
        return tuple(spec.local for spec in self.fields if spec.writes)


__all__ = [
    "CODECS",
    "MISSING",
    "Codec",
    "Decoded",
    "Direction",
    "FieldSpec",
    "FieldTranslator",
    "PayloadShape",
    "TranslationError",
    "Translator",
    "WriteIntent",
    "assign",
    "extract",
    "register_codec",
]
