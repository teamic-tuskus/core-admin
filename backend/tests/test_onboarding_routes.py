"""Route tests for sales onboarding endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.v1.routes import onboarding as onboarding_routes
from app.api.v1.routes.onboarding import router as onboarding_router
from app.services.container import get_onboarding_service, get_rate_limiter


class _FakeRateLimiter:
    def __init__(self, *, allowed: bool = True, retry_after_seconds: int = 0) -> None:
        self.allowed = allowed
        self.retry_after_seconds = retry_after_seconds

    def check(self, *, route_key: str, subject: str, limit: int, window_seconds: int):
        _ = (route_key, subject, limit, window_seconds)
        return type(
            "Decision",
            (),
            {"allowed": self.allowed, "retry_after_seconds": self.retry_after_seconds},
        )()


class _FakeOnboardingService:
    def verify_gst(self, *, subscription_id: str, gstin: str) -> dict:
        if gstin == "BADGSTINBADGSTI":
            raise ValueError("Invalid GSTIN")
        return {
            "transaction_id": "gst_tx_001",
            "data": {
                "gstin": gstin,
                "organisation_name": "Demo Legal",
                "masked_email": "o**@example.com",
                "masked_phone": "91******99",
                "address": "12 Demo Street, Pune, Maharashtra, 411001",
            },
        }

    def send_dual_otp(self, **_kwargs) -> dict:
        return {"otp_session_id": "os_001"}

    def verify_dual_otp(self, **_kwargs) -> dict:
        return {"verified": True}

    def complete_onboarding(self, _payload: dict) -> dict:
        return {
            "tenant_id": "ten_001",
            "super_admin_email": "admin@example.com",
            "onboarding_status": "completed",
            "completed_at": datetime.now(UTC),
        }


class _FakeDocSnapshot:
    def __init__(self, data: dict | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict:
        return dict(self._data or {})


class _FakeDocRef:
    def __init__(self, store: dict[str, dict], doc_id: str) -> None:
        self._store = store
        self._doc_id = doc_id

    def get(self) -> _FakeDocSnapshot:
        return _FakeDocSnapshot(self._store.get(self._doc_id))

    def set(self, payload: dict, merge: bool = False) -> None:
        if merge and self._doc_id in self._store:
            merged = dict(self._store[self._doc_id])
            merged.update(payload)
            self._store[self._doc_id] = merged
        else:
            self._store[self._doc_id] = dict(payload)


class _FakeCollection:
    def __init__(self, backing: dict[str, dict]) -> None:
        self._backing = backing

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(self._backing, doc_id)


class _FakeFirestore:
    def __init__(self) -> None:
        self.tenants: dict[str, dict] = {}

    def collection(self, name: str) -> _FakeCollection:
        if name != "tenants":
            raise AssertionError(f"Unexpected collection: {name}")
        return _FakeCollection(self.tenants)


@pytest.fixture
def fake_firestore(monkeypatch: pytest.MonkeyPatch) -> _FakeFirestore:
    db = _FakeFirestore()
    monkeypatch.setattr(onboarding_routes, "get_firestore_client", lambda: db)
    monkeypatch.setattr(
        onboarding_routes,
        "get_settings",
        lambda: SimpleNamespace(core_firebase_api_key_secret_id="fake-api-key-secret"),
    )
    monkeypatch.setattr(onboarding_routes, "get_secret", lambda _secret_id: "fake-api-key")
    return db


def _build_client(*, allowed: bool = True, retry_after_seconds: int = 0) -> TestClient:
    app = FastAPI()
    app.include_router(onboarding_router, prefix="/api/v1")
    app.dependency_overrides[get_onboarding_service] = lambda: _FakeOnboardingService()
    app.dependency_overrides[get_rate_limiter] = lambda: _FakeRateLimiter(
        allowed=allowed,
        retry_after_seconds=retry_after_seconds,
    )
    return TestClient(app)


def test_gst_verify_route() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/onboarding/gst/verify",
        json={"subscription_id": "sub_00123456", "gstin": "27ABCDE1234F1Z5"},
    )
    assert response.status_code == 200
    assert response.json()["transaction_id"] == "gst_tx_001"


def test_otp_send_route() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/onboarding/otp/send",
        json={
            "subscription_id": "sub_00123456",
            "gstin": "27ABCDE1234F1Z5",
            "transaction_id": "gst_tx_001",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"otp_session_id": "os_001"}


def test_otp_verify_route() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/onboarding/otp/verify",
        json={"otp_session_id": "os_00000001", "email_otp": "111111", "phone_otp": "222222"},
    )
    assert response.status_code == 200
    assert response.json() == {"verified": True}


def test_complete_route(fake_firestore: _FakeFirestore) -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/onboarding/complete",
        json={
            "subscription_id": "sub_00123456",
            "selected_plan": "growth",
            "billing_contact": {"company_name": "Acme", "contact_name": "Owner", "email": "owner@example.com"},
            "gst_profile": {"gstin": "27ABCDE1234F1Z5"},
            "head_office_location": {"latitude": 12.1, "longitude": 77.1},
            "role_assignment": {"email": "owner@example.com", "role": "super_admin"},
        },
    )
    assert response.status_code == 200
    assert response.json()["onboarding_status"] == "completed"
    assert isinstance(response.json()["credentials_setup_token"], str)
    assert response.json()["credentials_setup_token"]
    assert fake_firestore.tenants["ten_001"]["credentials_setup_token_hash"]


def test_credentials_requires_setup_token(fake_firestore: _FakeFirestore) -> None:
    client = _build_client()
    fake_firestore.tenants["ten_001"] = {
        "credentials_setup_email": "admin@example.com",
        "credentials_setup_token_hash": "abc",
        "credentials_setup_token_expires_at": datetime.now(UTC),
        "credentials_setup_token_used_at": None,
    }

    response = client.post(
        "/api/v1/onboarding/credentials",
        json={
            "tenant_id": "ten_001",
            "email": "admin@example.com",
            "password": "Password123!",
        },
    )

    assert response.status_code == 422


def test_credentials_accepts_valid_setup_token_and_marks_used(
    fake_firestore: _FakeFirestore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _build_client()

    complete = client.post(
        "/api/v1/onboarding/complete",
        json={
            "subscription_id": "sub_00123456",
            "selected_plan": "growth",
            "billing_contact": {"company_name": "Acme", "contact_name": "Owner", "email": "owner@example.com"},
            "gst_profile": {"gstin": "27ABCDE1234F1Z5"},
            "head_office_location": {"latitude": 12.1, "longitude": 77.1},
            "role_assignment": {"email": "owner@example.com", "role": "super_admin"},
        },
    )
    assert complete.status_code == 200
    setup_token = complete.json()["credentials_setup_token"]

    class _FakeHttpxResponse:
        status_code = 200

        @property
        def is_success(self) -> bool:
            return True

        def json(self) -> dict:
            return {}

    monkeypatch.setattr(onboarding_routes.httpx, "post", lambda url, **kwargs: _FakeHttpxResponse())

    response = client.post(
        "/api/v1/onboarding/credentials",
        json={
            "tenant_id": "ten_001",
            "email": "admin@example.com",
            "password": "Password123!",
            "setup_token": setup_token,
        },
    )
    assert response.status_code == 200
    assert response.json()["account_created"] is True
    assert fake_firestore.tenants["ten_001"]["credentials_setup_token_used_at"] is not None

    second = client.post(
        "/api/v1/onboarding/credentials",
        json={
            "tenant_id": "ten_001",
            "email": "admin@example.com",
            "password": "Password123!",
            "setup_token": setup_token,
        },
    )
    assert second.status_code == 400
    assert second.json() == {"detail": "Invalid or expired account setup token."}


def test_gst_verify_returns_429_when_rate_limited() -> None:
    client = _build_client(allowed=False, retry_after_seconds=25)

    response = client.post(
        "/api/v1/onboarding/gst/verify",
        json={"subscription_id": "sub_00123456", "gstin": "27ABCDE1234F1Z5"},
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many requests. Please try again shortly."}
    assert response.headers.get("retry-after") == "25"
