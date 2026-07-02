import pytest

from surge_data_loader.pii import PIIGuardError, validate_no_forbidden_fields


def test_pii_guard_allows_sanitized_output():
    validate_no_forbidden_fields(
        [{"event_id": 1, "participants": [{"person_id": 2, "sex_or_gender": "female"}]}]
    )


def test_pii_guard_blocks_forbidden_nested_field():
    with pytest.raises(PIIGuardError, match="email"):
        validate_no_forbidden_fields([{"participants": [{"email": "person@example.org"}]}])
