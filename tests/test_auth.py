import pytest

from surge_data_loader.auth import TokenParseError, parse_access_token


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "abc"},
        {"token": "abc"},
        {"bearer_token": "abc"},
        {"data": {"access_token": "abc"}},
        {"data": {"token": "abc"}},
    ],
)
def test_parse_access_token_common_shapes(payload):
    assert parse_access_token(payload) == "abc"


def test_parse_access_token_rejects_missing_token():
    with pytest.raises(TokenParseError):
        parse_access_token({"data": {"refresh_token": "nope"}})
