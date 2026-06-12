"""Tests for Secret Manager integration service."""

import types

import pytest

from app.core.secret_manager import SecretAccessError, SecretManagerService


class _FakeClient:
    def __init__(self, payload: str = "value", raise_error: bool = False) -> None:
        self.payload = payload
        self.raise_error = raise_error
        self.calls = 0

    def access_secret_version(self, request: dict[str, str]) -> types.SimpleNamespace:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("unavailable")
        assert request["name"].startswith("projects/demo/secrets/")
        return types.SimpleNamespace(
            payload=types.SimpleNamespace(data=self.payload.encode("utf-8"))
        )


def test_get_secret_uses_cache() -> None:
    fake_client = _FakeClient(payload="cached-value")
    service = SecretManagerService(project_id="demo", _client=fake_client)

    first = service.get_secret("jwt-signing-key")
    second = service.get_secret("jwt-signing-key")

    assert first == "cached-value"
    assert second == "cached-value"
    assert fake_client.calls == 1


def test_get_secret_raises_clear_error() -> None:
    fake_client = _FakeClient(raise_error=True)
    service = SecretManagerService(project_id="demo", _client=fake_client)

    with pytest.raises(SecretAccessError):
        service.get_secret("missing-secret")