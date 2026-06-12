"""Sync sold entitlements from CoreAdmin into Core runtime subscription limits."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib import error, request
from urllib.parse import urlparse


class CoreSubscriptionSyncError(RuntimeError):
    """Raised when Core subscription sync cannot be completed."""


class CoreSubscriptionSyncService:
    """Calls Core internal API to upsert tenant subscription quotas."""

    def __init__(self, *, base_url: str, sync_token: str, timeout_seconds: int = 12) -> None:
        self.base_url = base_url.rstrip("/")
        self.sync_token = sync_token
        self.timeout_seconds = timeout_seconds
        self._validate_base_url()

    def _validate_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()
        is_local = hostname in {"localhost", "127.0.0.1"}
        if parsed.scheme != "https" and not is_local:
            raise ValueError("Core subscription sync requires HTTPS for non-local endpoints")

    def _build_signature(self, *, timestamp: str, method: str, path: str, body: bytes) -> str:
        material = b"\n".join(
            (
                timestamp.encode("utf-8"),
                method.upper().encode("utf-8"),
                path.encode("utf-8"),
                body,
            )
        )
        return hmac.new(self.sync_token.encode("utf-8"), material, hashlib.sha256).hexdigest()

    def sync(self, payload: dict) -> dict:
        endpoint = f"{self.base_url}/internal/subscriptions/coreadmin"
        # Core verifies the HMAC signature against the full request path
        # (including any base prefix such as /api/v1), so sign that exact path.
        path = urlparse(endpoint).path
        body = json.dumps(payload).encode("utf-8")
        timestamp = str(int(time.time()))
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "user-agent": "CoreAdmin-SubscriptionSync/1.0",
                "accept": "application/json",
                "x-coreadmin-sync-token": self.sync_token,
                "x-coreadmin-sync-timestamp": timestamp,
                "x-coreadmin-sync-signature": self._build_signature(
                    timestamp=timestamp,
                    method="POST",
                    path=path,
                    body=body,
                ),
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                if int(response.getcode()) >= 400:
                    raise CoreSubscriptionSyncError("Core subscription sync failed")
                return parsed
        except error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("detail") or payload.get("error")
            except Exception:
                detail = None
            message = f"Core subscription sync failed ({exc.code})"
            if detail:
                message = f"{message}: {detail}"
            raise CoreSubscriptionSyncError(message) from exc
        except error.URLError as exc:
            raise CoreSubscriptionSyncError("Core subscription sync is unavailable") from exc
