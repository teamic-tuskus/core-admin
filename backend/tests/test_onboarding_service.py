"""Unit tests for onboarding service dual OTP enforcement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import re

from app.services.onboarding_service import OnboardingService
from app.services.otp_service import OtpError
from app.services.repositories import OnboardingSessionRepository, SubscriptionRepository, TenantRepository


class _FakeOtpService:
    def __init__(self) -> None:
        self.send_calls: list[dict[str, str]] = []
        self.verify_calls: list[dict[str, str]] = []

    def send_otp(self, *, channel: str, target: str, purpose: str) -> dict:
        self.send_calls.append({"channel": channel, "target": target, "purpose": purpose})
        suffix = "email" if channel == "email" else "phone"
        return {
            "challenge_id": f"otp_{suffix}",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        }

    def verify_otp(self, *, challenge_id: str, otp_code: str) -> dict:
        self.verify_calls.append({"challenge_id": challenge_id, "otp_code": otp_code})
        if otp_code == "000000":
            raise OtpError("Invalid OTP")
        return {"verified": True}


class _FakeCoreSyncService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def sync(self, payload: dict) -> dict:
        self.calls.append(payload)
        return {"message": "ok"}


class _FakeGstVerificationService:
    def verify_gst(self, *, gstin: str, fallback_email: str | None, fallback_phone: str | None) -> dict:
        return {
            "transaction_id": "gst_tx_001",
            "data": {
                "gstin": gstin,
                "business_name": "Acme Trade",
                "legal_name": "Acme Legal Pvt Ltd",
                "contact_details": {
                    "principal": {
                        "email": fallback_email or "ops@example.com",
                        "mobile": fallback_phone or "919999999999",
                    }
                },
            },
        }


class _FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.settings = SimpleNamespace(
            onboarding_test_email_target="app@teamic.in",
            onboarding_redirect_url="https://core.tuskus.com",
            support_email="support@tuskus.com",
        )

    def send_email(self, *, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> None:
        self.sent.append(
            {
                "to_email": to_email,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html or "",
            }
        )


def _build_service() -> OnboardingService:
    subscription_repo = SubscriptionRepository()
    onboarding_repo = OnboardingSessionRepository()
    tenant_repo = TenantRepository()
    otp_service = _FakeOtpService()
    sync_service = _FakeCoreSyncService()
    gst_service = _FakeGstVerificationService()
    email_sender = _FakeEmailSender()

    subscription_repo.create_pending(
        {
            "tenant_id": "tenant_001",
            "product_id": "prd_001",
            "product_snapshot": {"id": "prd_001", "code": "CORE", "name": "Core"},
            "modules": ["execution"],
            "max_users": 10,
            "tenure_months": 12,
            "currency": "INR",
            "amount_paise": 100000,
            "coupon_code": None,
            "coupon_snapshot": None,
            "customer_name": "Buyer",
            "customer_email": "buyer@example.com",
            "customer_phone": "919999999999",
        }
    )
    subscription = next(iter(subscription_repo.list()))

    service = OnboardingService(
        subscription_repo=subscription_repo,
        tenant_repo=tenant_repo,
        onboarding_repo=onboarding_repo,
        gst_verification_service=gst_service,
        otp_service=otp_service,
        email_sender=email_sender,
        core_subscription_sync_service=sync_service,
    )
    service._test_subscription_id = subscription["id"]  # type: ignore[attr-defined]
    service._test_otp_service = otp_service  # type: ignore[attr-defined]
    service._test_sync_service = sync_service  # type: ignore[attr-defined]
    service._test_subscription_repo = subscription_repo  # type: ignore[attr-defined]
    service._test_email_sender = email_sender  # type: ignore[attr-defined]
    return service


def test_send_dual_otp_defaults_to_email_when_phone_missing() -> None:
    service = _build_service()
    subscription_id = service._test_subscription_id  # type: ignore[attr-defined]
    service.gst_verification_service = type(
        "NoPhoneGstService",
        (),
        {
            "verify_gst": staticmethod(
                lambda **_kwargs: {
                    "transaction_id": "gst_tx_001",
                    "data": {
                        "gstin": "27ABCDE1234F1Z5",
                        "business_name": "Acme Trade",
                        "legal_name": "Acme Legal Pvt Ltd",
                        "contact_details": {"principal": {"email": "buyer@example.com", "mobile": None}},
                    },
                }
            )
        },
    )()

    result = service.send_dual_otp(
        subscription_id=subscription_id,
        gstin="27ABCDE1234F1Z5",
        transaction_id="tx_1",
    )

    assert result["otp_session_id"].startswith("os_")
    otp_service = service._test_otp_service  # type: ignore[attr-defined]
    assert len(otp_service.send_calls) == 1
    assert otp_service.send_calls[0]["channel"] == "email"


def test_send_dual_otp_creates_single_email_challenge_by_default() -> None:
    service = _build_service()
    subscription_id = service._test_subscription_id  # type: ignore[attr-defined]
    otp_service = service._test_otp_service  # type: ignore[attr-defined]

    result = service.send_dual_otp(
        subscription_id=subscription_id,
        gstin="27ABCDE1234F1Z5",
        transaction_id="tx_1",
    )

    assert result["otp_session_id"].startswith("os_")
    assert len(otp_service.send_calls) == 1
    assert otp_service.send_calls[0]["channel"] == "email"


def test_verify_dual_otp_accepts_email_fallback_for_single_mode() -> None:
    service = _build_service()
    subscription_id = service._test_subscription_id  # type: ignore[attr-defined]

    session = service.send_dual_otp(
        subscription_id=subscription_id,
        gstin="27ABCDE1234F1Z5",
        transaction_id="tx_1",
    )

    result = service.verify_dual_otp(
        otp_session_id=session["otp_session_id"],
        email_otp="123456",
        phone_otp=None,
    )
    assert result == {"verified": True}


def test_verify_dual_otp_verifies_both_channels() -> None:
    service = _build_service()
    otp_service = service._test_otp_service  # type: ignore[attr-defined]

    session_id = "os_dual_001"
    now = datetime.now(timezone.utc)
    service.onboarding_repo.create(
        {
            "id": session_id,
            "subscription_id": "sub_001",
            "transaction_id": "tx_1",
            "gstin": "27ABCDE1234F1Z5",
            "email": "buyer@example.com",
            "phone": "919999999999",
            "otp_channel": "email",
            "otp_mode": "dual",
            "email_challenge_id": "otp_email",
            "phone_challenge_id": "otp_phone",
            "organization_name": "Acme Legal Pvt Ltd",
            "status": "otp_sent",
            "expires_at": now + timedelta(minutes=10),
            "verified_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    result = service.verify_dual_otp(
        otp_session_id=session_id,
        email_otp="123456",
        phone_otp="654321",
    )

    assert result == {"verified": True}
    assert [call["challenge_id"] for call in otp_service.verify_calls] == ["otp_email", "otp_phone"]


def test_send_dual_otp_sms_channel_is_blocked() -> None:
    service = _build_service()
    subscription_id = service._test_subscription_id  # type: ignore[attr-defined]

    try:
        service.send_dual_otp(
            subscription_id=subscription_id,
            gstin="27ABCDE1234F1Z5",
            transaction_id="tx_1",
            otp_channel="sms",
        )
    except ValueError as exc:
        assert str(exc) == "SMS OTP is temporarily unavailable. OTP is sent to GST registered email."
    else:
        raise AssertionError("Expected ValueError when SMS channel is selected")


def test_complete_onboarding_syncs_subscription_limits() -> None:
    service = _build_service()
    subscription_id = service._test_subscription_id  # type: ignore[attr-defined]
    sync_service = service._test_sync_service  # type: ignore[attr-defined]
    subscription_repo = service._test_subscription_repo  # type: ignore[attr-defined]

    session = service.send_dual_otp(
        subscription_id=subscription_id,
        gstin="27ABCDE1234F1Z5",
        transaction_id="tx_1",
    )
    service.verify_dual_otp(
        otp_session_id=session["otp_session_id"],
        email_otp="123456",
        phone_otp="654321",
    )

    subscription_repo.activate(
        subscription_id=subscription_id,
        start_at=datetime.now(timezone.utc),
        end_at=datetime.now(timezone.utc) + timedelta(days=365),
        payment_id="pay_001",
    )

    result = service.complete_onboarding(
        {
            "subscription_id": subscription_id,
            "selected_plan": "growth",
            "billing_contact": {
                "company_name": "Acme",
                "contact_name": "Owner",
                "email": "owner@example.com",
            },
            "gst_profile": {"legal_name": "Acme Pvt Ltd"},
            "head_office_location": {"city": "Bengaluru"},
            "role_assignment": {"email": "owner@example.com", "role": "super_admin"},
        }
    )

    assert result["onboarding_status"] == "completed"
    assert len(sync_service.calls) == 1
    assert sync_service.calls[0]["coreadmin_subscription_id"] == subscription_id
    assert sync_service.calls[0]["tenant_id"] == result["tenant_id"]
    assert re.fullmatch(r"[A-Z0-9]{12}", result["tenant_id"]) is not None
    email_sender = service._test_email_sender  # type: ignore[attr-defined]
    assert len(email_sender.sent) == 2
    assert email_sender.sent[0]["to_email"] == "owner@example.com"
    assert email_sender.sent[1]["to_email"] == "app@teamic.in"
    assert result["tenant_id"] in email_sender.sent[0]["body_text"]
