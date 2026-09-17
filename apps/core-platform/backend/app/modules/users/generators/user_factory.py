"""Users module test data and mock generators."""

from __future__ import annotations

import random
from typing import Any
import uuid

from app.common.generators.identities import random_indian_phone, random_pan


def generate_fake_user_data(
    *,
    email: str | None = None,
    name: str | None = None,
    country: str = "IN",
    timezone: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """Generate realistic dictionary payload for creating a test User."""
    rand_id = random.randint(1000, 99999)
    first_names = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ananya", "Diya", "Isha"]
    last_names = ["Patel", "Shah", "Mehta", "Desai", "Joshi", "Amin", "Modi", "Panchal", "Bhatt", "Parikh"]
    
    first = random.choice(first_names)
    last = random.choice(last_names)
    full_name = name or f"{first} {last}"
    user_email = email or f"{first.lower()}.{last.lower()}{rand_id}@example.test"

    return {
        "name": full_name,
        "first_name": first,
        "last_name": last,
        "email": user_email,
        "username": f"{first.lower()}_{last.lower()}_{rand_id}",
        "phone": random_indian_phone(),
        "pan": random_pan(),
        "country": country,
        "timezone": timezone,
        "date_format": "d-m-Y",
        "time_format": "H:i",
        "currency": "INR",
        "currency_symbol": "₹",
        "password": "Password123!",
    }


def generate_fake_profile_data(
    user_id: int,
    *,
    country_iso2: str = "IN",
    timezone_name: str = "Asia/Kolkata",
    timezone_source: str = "auto",
) -> dict[str, Any]:
    """Generate dictionary payload for creating a UserProfile."""
    return {
        "uuid": uuid.uuid4(),
        "user_id": user_id,
        "country_iso2": country_iso2,
        "timezone_name": timezone_name,
        "timezone_source": timezone_source,
    }
