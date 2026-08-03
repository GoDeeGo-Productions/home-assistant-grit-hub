"""Shared validation for opaque GRIT bearer tokens."""
from __future__ import annotations

import unicodedata
from typing import Any

MAX_BEARER_TOKEN_BYTES = 65_536


class InvalidBearerToken(ValueError):
    """Raised when a value cannot safely be used as a bearer token."""


def validate_bearer_token(value: Any) -> str:
    """Return an opaque token unchanged after bounded header-safety checks."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidBearerToken("bearer token is blank")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise InvalidBearerToken("bearer token contains a control character")
    try:
        encoded = value.encode("latin-1")
    except UnicodeEncodeError as err:
        raise InvalidBearerToken(
            "bearer token cannot be represented in an HTTP header"
        ) from err
    if len(encoded) > MAX_BEARER_TOKEN_BYTES:
        raise InvalidBearerToken("bearer token is too large")
    return value


def bearer_authorization_value(value: Any) -> str:
    """Build the exact Authorization header value for a validated token."""
    return f"Bearer {validate_bearer_token(value)}"
