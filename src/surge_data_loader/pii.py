from __future__ import annotations

from collections.abc import Mapping
from typing import Any


FORBIDDEN_PERSONAL_FIELDS = {
    "firstnames",
    "surname",
    "fullname",
    "email",
    "phone",
    "mobile",
    "address",
    "decrypted_ssn",
    "passport",
    "document",
    "user",
    "signatures",
    "photo",
    "avatar",
}


class PIIGuardError(ValueError):
    """Raised when a JSON output contains forbidden personal fields."""


def validate_no_forbidden_fields(value: Any) -> None:
    paths = list(find_forbidden_field_paths(value))
    if paths:
        raise PIIGuardError("Forbidden personal field(s) found in output: " + ", ".join(paths))


def find_forbidden_field_paths(value: Any, prefix: str = "$") -> list[str]:
    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if str(key).lower() in FORBIDDEN_PERSONAL_FIELDS:
                matches.append(path)
            matches.extend(find_forbidden_field_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(find_forbidden_field_paths(child, f"{prefix}[{index}]"))
    return matches
