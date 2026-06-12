"""Sales onboarding service with GST check, dual OTP, and completion guardrails."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import logging
import re
from typing import Protocol
from uuid import uuid4

from app.services.email_sender import SmtpEmailSender
from app.services.gst_verification_service import GstVerificationService
from app.services.otp_service import OtpError, OtpService


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


GSTIN_REGEX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
SUBSCRIPTION_NOT_FOUND = "Subscription not found"
OTP_UNAVAILABLE_MESSAGE = "OTP delivery is temporarily unavailable. Please try again shortly."
SMS_OTP_DISABLED_MESSAGE = "SMS OTP is temporarily unavailable. OTP is sent to GST registered email."
NOT_AVAILABLE = "Not available"

logger = logging.getLogger(__name__)


class OnboardingService:
    """Coordinates post-payment onboarding with strong OTP verification."""

    def __init__(
        self,
        *,
        subscription_repo,
        tenant_repo,
        onboarding_repo,
        gst_verification_service: GstVerificationService,
        otp_service: OtpService,
        email_sender: SmtpEmailSender,
        core_subscription_sync_service: "CoreSubscriptionSyncServiceProtocol | None" = None,
    ) -> None:
        self.subscription_repo = subscription_repo
        self.tenant_repo = tenant_repo
        self.onboarding_repo = onboarding_repo
        self.gst_verification_service = gst_verification_service
        self.otp_service = otp_service
        self.email_sender = email_sender
        self.core_subscription_sync_service = core_subscription_sync_service

    @staticmethod
    def _normalize_gstin(gstin: str) -> str:
        return gstin.strip().upper()

    def _get_subscription_or_raise(self, subscription_id: str) -> dict:
        subscription = self.subscription_repo.get(subscription_id)
        if subscription is None:
            raise ValueError(SUBSCRIPTION_NOT_FOUND)
        return subscription

    def _validated_gst_payload(self, *, subscription: dict, gstin: str) -> tuple[str, dict]:
        normalized_gstin = self._normalize_gstin(gstin)
        if not GSTIN_REGEX.fullmatch(normalized_gstin):
            raise ValueError("Invalid GSTIN")
        payload = self.gst_verification_service.verify_gst(
            gstin=normalized_gstin,
            fallback_email=str(subscription.get("customer_email") or "").strip().lower() or None,
            fallback_phone=str(subscription.get("customer_phone") or "").strip() or None,
        )
        return normalized_gstin, payload

    @staticmethod
    def _extract_otp_targets(gst_payload: dict) -> tuple[dict, str, str]:
        gst_profile = gst_payload.get("data") or {}
        principal = ((gst_profile.get("contact_details") or {}).get("principal") or {})
        email = str(principal.get("email") or "").strip().lower()
        phone = "".join(ch for ch in str(principal.get("mobile") or "") if ch.isdigit())
        return gst_profile, email, phone

    def _create_otp_session(
        self,
        *,
        subscription_id: str,
        transaction_id: str | None,
        normalized_gstin: str,
        gst_profile: dict,
        email: str,
        phone: str,
        otp_channel: str,
        challenge_result: dict | None,
        masked_target: str,
        email_challenge_id: str | None = None,
        phone_challenge_id: str | None = None,
        otp_mode: str = "single",
    ) -> dict:
        now = _now()
        session_id = f"os_{uuid4().hex}"
        resolved_email_challenge_id = email_challenge_id
        resolved_phone_challenge_id = phone_challenge_id
        if challenge_result is not None:
            if otp_channel == "email":
                resolved_email_challenge_id = challenge_result["challenge_id"]
            elif otp_channel == "sms":
                resolved_phone_challenge_id = challenge_result["challenge_id"]

        self.onboarding_repo.create(
            {
                "id": session_id,
                "subscription_id": subscription_id,
                "transaction_id": transaction_id,
                "gstin": normalized_gstin,
                "email": email,
                "phone": phone,
                "otp_channel": otp_channel,
                "otp_mode": otp_mode,
                "email_challenge_id": resolved_email_challenge_id,
                "phone_challenge_id": resolved_phone_challenge_id,
                "organization_name": str(gst_profile.get("legal_name") or gst_profile.get("business_name") or ""),
                "status": "otp_sent",
                "expires_at": (challenge_result or {}).get("expires_at") or now,
                "verified_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return {
            "otp_session_id": session_id,
            "otp_channel": otp_channel,
            "masked_target": masked_target,
        }

    def _dispatch_setup_complete_emails(self, *, tenant: dict, subscription: dict, session: dict, role_assignment: dict) -> None:
        primary_email = str(
            role_assignment.get("email")
            or tenant.get("super_admin_email")
            or tenant.get("credentials_setup_email")
            or session.get("email")
            or tenant.get("company_email")
            or ""
        ).strip().lower()
        if not primary_email:
            return
        try:
            self._send_setup_complete_email(tenant=tenant, subscription=subscription, to_email=primary_email)
            test_email = str(self.email_sender.settings.onboarding_test_email_target or "").strip().lower()
            if test_email and test_email != primary_email:
                self._send_setup_complete_email(tenant=tenant, subscription=subscription, to_email=test_email)
        except Exception:
            logger.exception("Failed to send setup completion email", extra={"tenant_id": tenant.get("id")})

    def verify_gst(self, *, subscription_id: str, gstin: str) -> dict:
        subscription = self._get_subscription_or_raise(subscription_id)
        _, payload = self._validated_gst_payload(subscription=subscription, gstin=gstin)
        return self._public_gst_response(payload)

    def _public_gst_response(self, payload: dict) -> dict:
        """Build the minimal, masked GST surface returned to the public client.

        Only organisation name, masked email, masked phone, and the registered
        address (for the location step) are exposed. Full taxpayer data stays
        server-side.
        """
        data = payload.get("data") or {}
        principal = ((data.get("contact_details") or {}).get("principal") or {})
        email = str(principal.get("email") or "").strip()
        phone = str(principal.get("mobile") or "").strip()
        address = principal.get("address")
        return {
            "transaction_id": str(payload.get("transaction_id") or ""),
            "data": {
                "gstin": str(data.get("gstin") or ""),
                "organisation_name": str(data.get("legal_name") or data.get("business_name") or ""),
                "masked_email": self._mask_email(email) if email else None,
                "masked_phone": self._mask_phone(phone) if phone else None,
                "address": (str(address).strip() or None) if address else None,
            },
        }

    @staticmethod
    def _mask_email(email: str) -> str:
        if not email:
            return NOT_AVAILABLE
        name, _, domain = email.partition("@")
        if not name or not domain:
            return NOT_AVAILABLE
        if len(name) <= 2:
            return f"{name[0]}*@{domain}"
        return f"{name[0]}{'*' * max(len(name) - 2, 1)}{name[-1]}@{domain}"

    @staticmethod
    def _mask_phone(phone: str) -> str:
        if not phone:
            return NOT_AVAILABLE
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) < 6:
            return NOT_AVAILABLE
        return f"{digits[:2]}{'*' * 6}{digits[-2:]}"

    def send_dual_otp(
        self,
        *,
        subscription_id: str,
        gstin: str,
        transaction_id: str | None,
        otp_channel: str | None = None,
    ) -> dict:
        subscription = self._get_subscription_or_raise(subscription_id)
        normalized_gstin, gst_payload = self._validated_gst_payload(subscription=subscription, gstin=gstin)
        gst_profile, email, normalized_phone = self._extract_otp_targets(gst_payload)
        if not email:
            raise ValueError("Business email is required for OTP delivery")

        requested_channel = str(otp_channel or "").strip().lower()
        if requested_channel == "sms":
            raise ValueError(SMS_OTP_DISABLED_MESSAGE)
        if requested_channel not in {"", "email"}:
            raise ValueError("Unsupported OTP channel")

        # Hard lock to GST-registered email channel until SMS OTP path is stable.
        resolved_channel = "email"
        purpose = f"sales_onboarding:{subscription_id}:{normalized_gstin}"

        try:
            if resolved_channel == "email":
                challenge_result = self.otp_service.send_otp(channel="email", target=email, purpose=f"{purpose}:email")
                masked_target = self._mask_email(email)
                return self._create_otp_session(
                    subscription_id=subscription_id,
                    transaction_id=transaction_id,
                    normalized_gstin=normalized_gstin,
                    gst_profile=gst_profile,
                    email=email,
                    phone=normalized_phone,
                    otp_channel=resolved_channel,
                    challenge_result=challenge_result,
                    masked_target=masked_target,
                    otp_mode="single",
                )
        except (OtpError, RuntimeError) as exc:
            raise ValueError(OTP_UNAVAILABLE_MESSAGE) from exc

        raise ValueError("Unsupported OTP channel")

    def verify_dual_otp(
        self,
        *,
        otp_session_id: str,
        otp_code: str | None = None,
        email_otp: str | None = None,
        phone_otp: str | None = None,
    ) -> dict:
        session = self.onboarding_repo.get(otp_session_id)
        if session is None:
            raise ValueError("OTP session not found")
        if session.get("status") == "verified":
            return {"verified": True}
        if _now() > session["expires_at"]:
            self.onboarding_repo.update(
                otp_session_id,
                {"status": "expired", "updated_at": _now()},
            )
            raise ValueError("OTP session expired")

        channel = str(session.get("otp_channel") or "email")
        mode = str(session.get("otp_mode") or "single")
        code = str(otp_code or "").strip()

        try:
            if code:
                challenge_id = session["email_challenge_id"] if channel == "email" else session["phone_challenge_id"]
                if not challenge_id:
                    raise ValueError("OTP session is incomplete")
                self.otp_service.verify_otp(challenge_id=challenge_id, otp_code=code)
            elif mode == "dual":
                email_code = str(email_otp or "").strip()
                phone_code = str(phone_otp or "").strip()
                if len(email_code) < 4:
                    raise ValueError("Email OTP is required")
                if len(phone_code) < 4:
                    raise ValueError("Phone OTP is required")
                email_challenge_id = session.get("email_challenge_id")
                phone_challenge_id = session.get("phone_challenge_id")
                if not email_challenge_id or not phone_challenge_id:
                    raise ValueError("OTP session is incomplete")
                self.otp_service.verify_otp(challenge_id=email_challenge_id, otp_code=email_code)
                self.otp_service.verify_otp(challenge_id=phone_challenge_id, otp_code=phone_code)
            else:
                fallback_code = str(email_otp or "").strip() if channel == "email" else str(phone_otp or "").strip()
                if len(fallback_code) < 4:
                    raise ValueError("OTP code is required")
                challenge_id = session["email_challenge_id"] if channel == "email" else session["phone_challenge_id"]
                if not challenge_id:
                    raise ValueError("OTP session is incomplete")
                self.otp_service.verify_otp(challenge_id=challenge_id, otp_code=fallback_code)
        except OtpError as exc:
            raise ValueError(str(exc)) from exc

        now = _now()
        self.onboarding_repo.update(
            otp_session_id,
            {
                "status": "verified",
                "verified_at": now,
                "updated_at": now,
            },
        )
        return {"verified": True}

    def _ensure_verified_session(self, subscription_id: str) -> dict:
        session = self.onboarding_repo.get_latest_by_subscription(subscription_id)
        session_status = str((session or {}).get("status") or "")
        if session is None or session_status not in {"verified", "sync_pending"}:
            raise ValueError("OTP verification is required before onboarding completion")
        return session

    def _ensure_tenant(
        self,
        *,
        session: dict,
        subscription: dict,
        subscription_id: str,
        selected_plan: str | None,
        billing_contact: dict,
        role_assignment: dict,
        gst_profile: dict,
        location: dict,
    ) -> dict:
        tenant = None
        existing_tenant_id = session.get("tenant_id")
        if existing_tenant_id:
            tenant = self.tenant_repo.get(str(existing_tenant_id))

        if tenant is None:
            organization_name = str(
                billing_contact.get("company_name")
                or gst_profile.get("organisation_name")
                or gst_profile.get("organization_name")
                or gst_profile.get("legal_name")
                or gst_profile.get("business_name")
                or "Core Organisation"
            ).strip()
            tenant = self.tenant_repo.create(
                {
                    "name": organization_name or "Core Organisation",
                    "company_email": str(billing_contact.get("email") or role_assignment.get("email") or subscription.get("customer_email") or ""),
                    "contact_name": str(billing_contact.get("contact_name") or subscription.get("customer_name") or "Owner"),
                    "phone": billing_contact.get("phone") or subscription.get("customer_phone"),
                    "status": "active",
                    "subscription_id": subscription_id,
                    "selected_plan": selected_plan,
                    "gst_profile": gst_profile,
                    "head_office_location": location,
                    "super_admin_email": role_assignment.get("email"),
                }
            )
        return tenant

    def _sync_subscription_limits(self, *, tenant: dict, subscription: dict, selected_plan: str | None) -> None:
        if self.core_subscription_sync_service is None:
            return
        try:
            self.core_subscription_sync_service.sync(
                {
                    "tenant_id": tenant["id"],
                    "coreadmin_subscription_id": subscription["id"],
                    "product_id": subscription.get("product_id"),
                    "product_code": (subscription.get("product_snapshot") or {}).get("code") or selected_plan or "core",
                    "product_name": (subscription.get("product_snapshot") or {}).get("name") or selected_plan or "Core",
                    "entitlement_modules": list(subscription.get("modules") or []),
                    "entitlement_max_users": int(subscription.get("max_users") or 1),
                    "entitlement_tenure_months": int(subscription.get("tenure_months") or 1),
                    "amount_paise": int(subscription.get("amount_paise") or 0),
                    "currency": subscription.get("currency") or "INR",
                    "coupon_code": subscription.get("coupon_code"),
                    "start_at": subscription.get("start_at").isoformat() if subscription.get("start_at") else None,
                    "end_at": subscription.get("end_at").isoformat() if subscription.get("end_at") else None,
                    "buyer_email": str(subscription.get("customer_email") or ""),
                }
            )
        except Exception as exc:
            raise ValueError("Subscription limits sync failed. Please retry onboarding completion.") from exc

    def _send_setup_complete_email(self, *, tenant: dict, subscription: dict, to_email: str) -> None:
        organization_id = str(tenant.get("id") or "")
        organization_name = str(tenant.get("name") or "Core Organisation")
        login_url = self.email_sender.settings.onboarding_redirect_url
        customer_name = str(subscription.get("customer_name") or "there")
        safe_name = html.escape(organization_name)
        safe_id = html.escape(organization_id)
        safe_login_url = html.escape(login_url)
        safe_customer_name = html.escape(customer_name)
        subject = "Your Core onboarding is complete"
        body_text = (
            f"Hi {customer_name},\n\n"
            "Welcome to Core. Your onboarding is complete and your workspace is ready.\n\n"
            f"Organization name: {organization_name}\n"
            f"Organization ID: {organization_id}\n"
            f"Login URL: {login_url}\n\n"
            "You can now sign in with your Super Admin credentials."
        )
        body_html = f"""
<!doctype html>
<html>
    <body style=\"margin:0;padding:0;background:#eaf0ff;font-family:'Segoe UI',Arial,sans-serif;\">
        <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"padding:28px 12px;\">
            <tr>
                <td align=\"center\">
                    <table role=\"presentation\" width=\"560\" cellpadding=\"0\" cellspacing=\"0\" style=\"width:100%;max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 16px 48px rgba(15,23,42,0.12);\">
                        <tr>
                            <td style=\"background:linear-gradient(135deg,#0f172a,#1d4ed8);padding:28px 32px;\">
                                <p style=\"margin:0;color:#dbeafe;font-size:12px;font-weight:700;letter-spacing:0.6px;text-transform:uppercase;\">Core Subscription</p>
                                <h1 style=\"margin:8px 0 0;color:#ffffff;font-size:24px;line-height:1.3;\">Onboarding complete. You are ready to go.</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:30px 32px 12px;\">
                                <p style=\"margin:0 0 16px;color:#1e293b;font-size:15px;line-height:1.6;\">Hi <strong>{safe_customer_name}</strong>,</p>
                                <p style=\"margin:0 0 18px;color:#1e293b;font-size:15px;line-height:1.6;\">Your Core workspace setup is complete, and you can now sign in with your Super Admin account.</p>
                                <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;\">
                                    <tr>
                                        <td style=\"padding:18px 20px;\">
                                            <p style=\"margin:0 0 8px;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:0.7px;font-weight:700;\">Organization name</p>
                                            <p style=\"margin:0 0 16px;color:#0f172a;font-size:22px;font-weight:800;\">{safe_name}</p>
                                            <p style=\"margin:0 0 8px;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:0.7px;font-weight:700;\">Organization ID</p>
                                            <p style=\"margin:0;color:#0f172a;font-size:18px;font-weight:800;letter-spacing:0.6px;\">{safe_id}</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:0 32px 30px;\">
                                <a href=\"{safe_login_url}\" style=\"display:inline-block;background:#1d4ed8;color:#ffffff;text-decoration:none;font-weight:700;padding:14px 24px;border-radius:999px;\">Sign in to Core</a>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
</html>
"""
        self.email_sender.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    def complete_onboarding(self, payload: dict) -> dict:
        subscription_id = payload["subscription_id"]
        subscription = self._get_subscription_or_raise(subscription_id)
        if str(subscription.get("status") or "").lower() != "active":
            raise ValueError("Subscription must be active before onboarding completion")
        if not subscription.get("razorpay_payment_id"):
            raise ValueError("Verified payment is required before onboarding completion")

        session = self._ensure_verified_session(subscription_id)

        billing_contact = payload.get("billing_contact") or {}
        role_assignment = payload.get("role_assignment") or {}
        gst_profile = payload.get("gst_profile") or {}
        location = payload.get("head_office_location") or {}
        selected_plan = payload.get("selected_plan")

        tenant = self._ensure_tenant(
            session=session,
            subscription=subscription,
            subscription_id=subscription_id,
            selected_plan=selected_plan,
            billing_contact=billing_contact,
            role_assignment=role_assignment,
            gst_profile=gst_profile,
            location=location,
        )

        self.onboarding_repo.update(
            session["id"],
            {
                "status": "sync_pending",
                "updated_at": _now(),
                "tenant_id": tenant["id"],
            },
        )

        self._sync_subscription_limits(
            tenant=tenant,
            subscription=subscription,
            selected_plan=selected_plan,
        )
        self._dispatch_setup_complete_emails(
            tenant=tenant,
            subscription=subscription,
            session=session,
            role_assignment=role_assignment,
        )

        now = _now()
        self.onboarding_repo.update(
            session["id"],
            {
                "status": "completed",
                "completed_at": now,
                "updated_at": now,
                "tenant_id": tenant["id"],
            },
        )

        return {
            "tenant_id": tenant["id"],
            "super_admin_email": str(role_assignment.get("email") or tenant.get("company_email") or ""),
            "onboarding_status": "completed",
            "completed_at": now,
        }


class CoreSubscriptionSyncServiceProtocol(Protocol):
    def sync(self, payload: dict) -> dict: ...
