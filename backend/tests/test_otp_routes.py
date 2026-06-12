"""API route tests for OTP endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.otp import router as otp_router
from app.services.container import get_otp_service
from app.services.otp_service import OtpError


class _FakeOtpService:
    def send_otp(self, *, channel: str, target: str, purpose: str) -> dict:
        if target == "blocked@example.com":
            raise OtpError("Too many OTP requests. Please try again later.")
        now = datetime.now(UTC)
        return {
            "challenge_id": "otp_test_001",
            "channel": channel,
            "masked_target": "op****@example.com",
            "expires_at": now,
            "resend_available_at": now,
        }

    def verify_otp(self, *, challenge_id: str, otp_code: str) -> dict:
        if otp_code != "123456":
            raise OtpError("Invalid OTP. 2 attempt(s) remaining.")
        return {
            "verified": True,
            "purpose": "onboarding",
            "channel": "email",
            "target": "ops@example.com",
            "verified_at": datetime.now(UTC),
        }


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(otp_router, prefix="/api/v1")
    app.dependency_overrides[get_otp_service] = lambda: _FakeOtpService()
    return TestClient(app)


def test_send_otp_success() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/otp/send",
        json={
            "channel": "email",
            "target": "ops@example.com",
            "purpose": "onboarding",
        },
    )
    assert response.status_code == 200
    assert response.json()["challenge_id"] == "otp_test_001"


def test_send_otp_rate_limit() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/otp/send",
        json={
            "channel": "email",
            "target": "blocked@example.com",
            "purpose": "onboarding",
        },
    )
    assert response.status_code == 429


def test_verify_otp_success() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/otp/verify",
        json={
            "challenge_id": "otp_test_001",
            "otp_code": "123456",
        },
    )
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_verify_otp_invalid() -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/otp/verify",
        json={
            "challenge_id": "otp_test_001",
            "otp_code": "000000",
        },
    )
    assert response.status_code == 400
