from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.core_subscription_sync import CoreSubscriptionSyncService


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def decode(self, _encoding: str) -> str:
        return json.dumps(self.payload)

    def getcode(self) -> int:
        return 200

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_sync_requires_https_for_non_local_base_url() -> None:
    with pytest.raises(ValueError, match="requires HTTPS"):
        CoreSubscriptionSyncService(base_url="http://api.tuskus.com/api/v1", sync_token="secret")


def test_sync_sends_signed_headers() -> None:
    service = CoreSubscriptionSyncService(
        base_url="https://api.tuskus.com/api/v1",
        sync_token="secret",
    )
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _FakeResponse({"data": {"ok": True}})

    with patch("app.services.core_subscription_sync.time.time", return_value=1_718_000_000), patch(
        "app.services.core_subscription_sync.request.urlopen",
        side_effect=_fake_urlopen,
    ):
        response = service.sync({"tenant_id": "ten_123"})

    assert response == {"data": {"ok": True}}
    headers = captured["headers"]
    assert headers["X-coreadmin-sync-token"] == "secret"
    assert headers["X-coreadmin-sync-timestamp"] == "1718000000"
    assert headers["X-coreadmin-sync-signature"]
    assert captured["url"] == "https://api.tuskus.com/api/v1/internal/subscriptions/coreadmin"


def test_sync_signature_covers_full_request_path() -> None:
    """Core verifies the HMAC against the full request path including /api/v1."""
    import hashlib
    import hmac

    service = CoreSubscriptionSyncService(
        base_url="https://api.tuskus.com/api/v1",
        sync_token="secret",
    )
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = req.data
        return _FakeResponse({"data": {"ok": True}})

    with patch("app.services.core_subscription_sync.time.time", return_value=1_718_000_000), patch(
        "app.services.core_subscription_sync.request.urlopen",
        side_effect=_fake_urlopen,
    ):
        service.sync({"tenant_id": "ten_123"})

    timestamp = captured["headers"]["x-coreadmin-sync-timestamp"]
    signature = captured["headers"]["x-coreadmin-sync-signature"]
    full_path = "/api/v1/internal/subscriptions/coreadmin"
    material = b"\n".join(
        (
            timestamp.encode("utf-8"),
            b"POST",
            full_path.encode("utf-8"),
            captured["body"],
        )
    )
    expected = hmac.new(b"secret", material, hashlib.sha256).hexdigest()
    assert signature == expected