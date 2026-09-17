"""Common mock data and identity generators for testing and seeding."""

from __future__ import annotations

import random
import string
import uuid
from typing import Literal

from whenever import Instant, days, hours


def random_indian_phone() -> str:
    """Generate a realistic 10-digit Indian mobile number (+91)."""
    prefix = random.choice(["6", "7", "8", "9"])
    digits = "".join(random.choices(string.digits, k=9))
    return f"+91{prefix}{digits}"


def random_pan() -> str:
    """Generate a syntactically valid Permanent Account Number (PAN)."""
    chars = "".join(random.choices(string.ascii_uppercase, k=3))
    status = random.choice(["P", "C", "H", "F", "A", "T", "B", "L", "J", "G"])
    last_char = random.choice(string.ascii_uppercase)
    digits = "".join(random.choices(string.digits, k=4))
    check = random.choice(string.ascii_uppercase)
    return f"{chars}{status}{last_char}{digits}{check}"


def random_gstin(state_code: str = "24") -> str:
    """Generate a syntactically valid Indian GSTIN (default: Gujarat 24)."""
    pan = random_pan()
    entity = str(random.randint(1, 9))
    return f"{state_code}{pan}{entity}Z{random.choice(string.ascii_uppercase + string.digits)}"


def random_recent_instant(within_days: int = 30) -> Instant:
    """Generate an Instant within the last N days using `whenever`."""
    now = Instant.now()
    offset_days = random.randint(1, within_days)
    offset_hours = random.randint(0, 23)
    return now.subtract(days=offset_days).subtract(hours=offset_hours)
