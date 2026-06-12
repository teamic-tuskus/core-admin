"""Tests for robust OTP service behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.otp_service import OtpError, OtpPolicy, OtpService
from app.services.repositories import OtpChallengeRepository


class _FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_otp_email(self, *, to_email: str, otp_code: str, validity_minutes: int) -> None:
        self.calls.append(
            {
                "to_email": to_email,
                "otp_code": otp_code,
                "validity_minutes": validity_minutes,
            }
        )


def _build_service() -> tuple[OtpService, OtpChallengeRepository, _FakeEmailSender]:
    repo = OtpChallengeRepository()
    email_sender = _FakeEmailSender()
    service = OtpService(
        otp_repo=repo,
        email_sender=email_sender,
        otp_hash_pepper="test-pepper",
        policy=OtpPolicy(
            code_length=6,
            expiry_minutes=10,
            resend_cooldown_seconds=60,
            max_attempts=3,
            max_sends_per_window=3,
            send_window_minutes=15,
        ),
    )
    return service, repo, email_sender


def test_send_and_verify_email_otp(monkeypatch) -> None:
    service, _repo, email_sender = _build_service()
    monkeypatch.setattr(service, "_new_code", lambda: "123456")

    sent = service.send_otp(channel="email", target="ops@example.com", purpose="onboarding")

    assert sent["channel"] == "email"
    assert sent["challenge_id"].startswith("otp_")
    assert email_sender.calls[0]["to_email"] == "ops@example.com"

    verified = service.verify_otp(challenge_id=sent["challenge_id"], otp_code="123456")
    assert verified["verified"] is True
    assert verified["purpose"] == "onboarding"


def test_invalid_otp_locks_after_max_attempts(monkeypatch) -> None:
    service, repo, _email_sender = _build_service()
    monkeypatch.setattr(service, "_new_code", lambda: "123456")

    sent = service.send_otp(channel="email", target="ops@example.com", purpose="login")

    with pytest.raises(OtpError):
        service.verify_otp(challenge_id=sent["challenge_id"], otp_code="111111")
    with pytest.raises(OtpError):
        service.verify_otp(challenge_id=sent["challenge_id"], otp_code="222222")
    with pytest.raises(OtpError, match="locked"):
        service.verify_otp(challenge_id=sent["challenge_id"], otp_code="333333")

    challenge = repo.get(sent["challenge_id"])
    assert challenge is not None
    assert challenge["status"] == "locked"


def test_send_rate_limit(monkeypatch) -> None:
    service, _repo, _email_sender = _build_service()
    monkeypatch.setattr(service, "_new_code", lambda: "123456")

    for _ in range(3):
        sent = service.send_otp(channel="email", target="ops@example.com", purpose="login")
        challenge_id = sent["challenge_id"]
        service.otp_repo.update(
            challenge_id,
            {
                "resend_available_at": datetime.now(timezone.utc) - timedelta(seconds=1),
                "status": "expired",
            },
        )

    with pytest.raises(OtpError, match="Too many OTP requests"):
        service.send_otp(channel="email", target="ops@example.com", purpose="login")
