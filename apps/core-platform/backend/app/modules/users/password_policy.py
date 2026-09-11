"""Configurable password policy — one validator every entry point reuses.

Complexity is configuration (``settings.PASSWORD_*``), not code: flipping a
flag changes register, admin-create, change-password and reset-password
together. There is exactly one rule engine here; callers never re-implement
"at least one uppercase".

Two entry points, deliberately:
  - ``PasswordStr`` (Annotated Pydantic type) enforces length/complexity at the
    request boundary and surfaces failures as the standard 422 envelope.
  - ``validate_password`` additionally enforces user-specific rules (email/name
    must not appear in the password) in the service layer, where that context
    exists, raising ``PasswordPolicyError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from pydantic import AfterValidator

from app.common.exception.errors import AppError
from app.core.conf import settings


class PasswordPolicyError(AppError):
    """A password failed the configured policy (422, not a 500)."""

    status_code = 422
    code = "password_policy"


#: Small built-in denylist — the point is to stop the trivially guessable
#: top-of-list passwords, not to be a full breach corpus (a k-anonymity API
#: check would be the next step if we ever need one).
_COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "passw0rd", "p@ssw0rd",
        "12345678", "123456789", "1234567890", "11111111", "00000000",
        "qwertyui", "qwerty123", "qwertyuiop", "letmein", "iloveyou",
        "admin123", "administrator", "welcome1", "changeme", "abc12345",
        "monkey123", "dragon123", "football", "baseball", "master123",
        "sunshine", "princess", "shadow123", "superman", "michael123",
    }
)


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    min_length: int = 8
    max_length: int = 128
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = False
    special_chars: str = ""            # empty => any non-alphanumeric counts
    min_unique_chars: int = 4
    disallow_common: bool = True
    disallow_user_info: bool = True

    @classmethod
    def from_settings(cls) -> PasswordPolicy:
        return cls(
            min_length=settings.PASSWORD_MIN_LENGTH,
            max_length=settings.PASSWORD_MAX_LENGTH,
            require_uppercase=settings.PASSWORD_REQUIRE_UPPERCASE,
            require_lowercase=settings.PASSWORD_REQUIRE_LOWERCASE,
            require_digit=settings.PASSWORD_REQUIRE_DIGIT,
            require_special=settings.PASSWORD_REQUIRE_SPECIAL,
            special_chars=settings.PASSWORD_SPECIAL_CHARS,
            min_unique_chars=settings.PASSWORD_MIN_UNIQUE_CHARS,
            disallow_common=settings.PASSWORD_DISALLOW_COMMON,
            disallow_user_info=settings.PASSWORD_DISALLOW_USER_INFO,
        )

    def _has_special(self, password: str) -> bool:
        if self.special_chars:
            return any(c in self.special_chars for c in password)
        return any(not c.isalnum() for c in password)

    def violations(self, password: str, *, email: str | None = None, name: str | None = None) -> list[str]:
        """Return human-readable rule failures (empty list == valid)."""
        problems: list[str] = []
        if len(password) < self.min_length:
            problems.append(f"be at least {self.min_length} characters")
        if len(password) > self.max_length:
            problems.append(f"be at most {self.max_length} characters")
        if self.require_uppercase and not any(c.isupper() for c in password):
            problems.append("contain an uppercase letter")
        if self.require_lowercase and not any(c.islower() for c in password):
            problems.append("contain a lowercase letter")
        if self.require_digit and not any(c.isdigit() for c in password):
            problems.append("contain a digit")
        if self.require_special and not self._has_special(password):
            problems.append("contain a special character")
        if self.min_unique_chars and len(set(password)) < self.min_unique_chars:
            problems.append(f"contain at least {self.min_unique_chars} distinct characters")
        if self.disallow_common and password.lower() in _COMMON_PASSWORDS:
            problems.append("not be a commonly used password")
        if self.disallow_user_info:
            haystack = password.lower()
            tokens = set()
            if email:
                tokens.add(email.split("@", 1)[0].lower())
            if name:
                tokens.update(t.lower() for t in name.split())
            for token in tokens:
                if len(token) >= 3 and token in haystack:
                    problems.append("not contain your name or email")
                    break
        return problems

    def validate(self, password: str, *, email: str | None = None, name: str | None = None) -> str:
        problems = self.violations(password, email=email, name=name)
        if problems:
            raise PasswordPolicyError(
                "Password does not meet the security policy: " + "; ".join(problems)
            )
        return password


@lru_cache
def get_password_policy() -> PasswordPolicy:
    return PasswordPolicy.from_settings()


def validate_password(password: str, *, email: str | None = None, name: str | None = None) -> str:
    """Validate against the configured policy; raises ``PasswordPolicyError``."""
    return get_password_policy().validate(password, email=email, name=name)


def _pydantic_check(value: str) -> str:
    # Raise the domain error (not ValueError): Pydantic catches ValueError and
    # embeds the exception object in exc.errors(), which this app's ORJSON
    # envelope handler cannot serialize. A non-ValueError propagates to the
    # AppError handler and renders the standard 422 envelope.
    problems = get_password_policy().violations(value)
    if problems:
        raise PasswordPolicyError(
            "Password does not meet the security policy: " + "; ".join(problems)
        )
    return value


#: Drop-in Pydantic type for any password field (register/create/change/reset).
PasswordStr = Annotated[str, AfterValidator(_pydantic_check)]
