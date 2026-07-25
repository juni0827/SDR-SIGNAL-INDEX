from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from signal_index.config import Settings
from signal_index.schemas import SearchRequest
from signal_index.security import (
    create_session_token,
    decode_session_token,
    hash_password,
    validate_external_url,
    verify_password,
)
from signal_index.storage import ObjectStorage


def settings() -> Settings:
    return Settings(
        APP_ENV="test",
        SESSION_SECRET="s" * 32,
        JWT_SECRET="j" * 32,
        TOOL_API_KEY="t" * 32,
    )


def test_password_and_session_permissions() -> None:
    hashed = hash_password("a-strong-password")
    assert verify_password(hashed, "a-strong-password")
    assert not verify_password(hashed, "wrong-password")
    token = create_session_token("user-1", settings())
    assert decode_session_token(token, settings()) == "user-1"


def test_ssrf_rejects_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(ValueError, match="private"):
        validate_external_url("http://example.test/data")


def test_signed_url_expiry_and_private_bucket() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed.invalid/object"
    with patch("signal_index.storage.boto3.client", return_value=client):
        storage = ObjectStorage(settings())
        assert storage.signed_get_url("originals/a.wav", 60).startswith("https://signed")
        with pytest.raises(ValueError):
            storage.signed_get_url("originals/a.wav", 2)


def test_query_validation() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(frequency_min_hz=10, frequency_max_hz=1)
    with pytest.raises(ValidationError):
        SearchRequest(number_group="281 DROP TABLE")
