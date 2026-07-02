from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TOKEN_FIELD_NAMES = {"access_token", "token", "bearer_token"}


class TokenParseError(ValueError):
    """Raised when a login response does not contain a usable access token."""


def parse_access_token(payload: Mapping[str, Any]) -> str:
    """Extract a bearer token from common RRMS login response shapes."""
    token = _find_token(payload)
    if not token:
        raise TokenParseError(
            "Login response did not contain access_token, token, bearer_token, "
            "data.access_token, or data.token."
        )
    return token


def _find_token(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in TOKEN_FIELD_NAMES:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        data = value.get("data")
        if isinstance(data, Mapping):
            nested = _find_token(data)
            if nested:
                return nested
    return None
