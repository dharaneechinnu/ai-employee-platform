"""What a username may look like, and how to derive one from an email."""

from __future__ import annotations

import re

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 30

# Letters, digits, underscore, dot, hyphen; must start with a letter or digit.
USERNAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,29}$"
USERNAME_MESSAGE = (
    "Use 3 to 30 letters, numbers, dots, hyphens or underscores, starting with a letter or number."
)
_USERNAME_RE = re.compile(USERNAME_PATTERN)


def is_valid_username(value: str) -> bool:
    return _USERNAME_RE.fullmatch(value) is not None


def username_from_email(email: str) -> str:
    """A valid starting point for an account made without one: the part
    before the @, cleaned to the allowed characters. The caller makes it
    unique."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", email.split("@", 1)[0])
    cleaned = cleaned.lstrip("_.-")[:MAX_USERNAME_LENGTH]
    return cleaned.ljust(MIN_USERNAME_LENGTH, "0") if cleaned else "user"


def with_suffix(base: str, n: int) -> str:
    """`base` plus a numeric suffix, trimmed so the whole stays within the limit."""
    suffix = str(n)
    return base[: MAX_USERNAME_LENGTH - len(suffix)] + suffix
