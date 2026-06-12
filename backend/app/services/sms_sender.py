"""SMS sender for OTP delivery via MSG91 with secrets from GCP Secret Manager."""

from __future__ import annotations

import logging

import httpx

from app.core.secret_manager import get_secret
from app.core.settings import get_settings


logger = logging.getLogger(__name__)

JSON_CONTENT_TYPE = "application/json"
SMS_DELIVERY_FAILED = "SMS delivery failed"


class SmsSender:
    """Sends OTP SMS messages using configured provider credentials."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.sms_enabled

    def _resolve_msg91_key(self) -> str:
        return get_secret(self.settings.sms_msg91_auth_key_secret_id)

    def _send_msg91_via_otp_api(self, *, phone: str, otp_code: str, validity_minutes: int) -> None:
        auth_key = self._resolve_msg91_key()
        mobile = self._normalize_phone(phone)
        message = f"Your Core verification code is {otp_code}. It is valid for {validity_minutes} minutes."

        payload: dict[str, object] = {
            "mobile": f"{self.settings.sms_country_code}{mobile}",
            "otp": otp_code,
            "otp_expiry": max(1, validity_minutes),
        }
        template_id = (self.settings.sms_msg91_template_id or "").strip()
        if template_id:
            # For DLT-linked MSG91 flows, rely on approved template payload only.
            payload["template_id"] = template_id
        else:
            payload["message"] = message

        headers = {
            "content-type": JSON_CONTENT_TYPE,
            "authkey": auth_key,
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://control.msg91.com/api/v5/otp",
                json=payload,
                headers=headers,
            )
        if response.status_code >= 400:
            raise RuntimeError(SMS_DELIVERY_FAILED)
        data = response.json()
        if data.get("type") != "success":
            logger.warning("MSG91 OTP rejected", extra={"provider_response": data})
            raise RuntimeError(SMS_DELIVERY_FAILED)
        logger.info(
            "MSG91 OTP accepted",
            extra={
                "request_id": data.get("request_id"),
                "mobile_suffix": mobile[-4:],
                "template_id": template_id or None,
            },
        )

    def _send_msg91_via_sms_flow(self, *, phone: str, otp_code: str) -> None:
        auth_key = self._resolve_msg91_key()
        mobile = self._normalize_phone(phone)
        template_id = (self.settings.sms_msg91_template_id or "").strip()
        if not template_id:
            raise RuntimeError("SMS template is required for MSG91 SMS Flow API")

        var_key = (self.settings.sms_msg91_flow_var_key or "VAR1").strip() or "VAR1"
        recipient: dict[str, str] = {"mobiles": f"{self.settings.sms_country_code}{mobile}", var_key: otp_code}
        payload: dict[str, object] = {
            "template_id": template_id,
            "short_url": self.settings.sms_msg91_flow_short_url,
            "recipients": [recipient],
        }
        sender_id = (self.settings.sms_msg91_sender_id or "").strip()
        if sender_id:
            payload["sender"] = sender_id
        headers = {
            "accept": JSON_CONTENT_TYPE,
            "content-type": JSON_CONTENT_TYPE,
            "authkey": auth_key,
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://control.msg91.com/api/v5/flow",
                json=payload,
                headers=headers,
            )

        if response.status_code >= 400:
            raise RuntimeError(SMS_DELIVERY_FAILED)
        data = response.json()
        if data.get("type") != "success":
            logger.warning("MSG91 SMS Flow rejected", extra={"provider_response": data})
            raise RuntimeError(SMS_DELIVERY_FAILED)
        logger.info(
            "MSG91 SMS Flow accepted",
            extra={
                "request_id": data.get("message"),
                "mobile_suffix": mobile[-4:],
                "template_id": template_id,
                "sender_id": sender_id or None,
            },
        )

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("Phone is required for OTP delivery")
        return digits[-10:]

    def send_otp_sms(self, *, phone: str, otp_code: str, validity_minutes: int) -> None:
        """Send OTP through MSG91. Raises RuntimeError when provider call fails."""
        if not self.enabled:
            raise RuntimeError("SMS is disabled. Set COREADMIN_SMS_ENABLED=true to enable SMS delivery.")
        if self.settings.sms_provider != "msg91":
            raise RuntimeError("Unsupported SMS provider configuration")

        if self.settings.sms_msg91_channel == "otp":
            self._send_msg91_via_otp_api(phone=phone, otp_code=otp_code, validity_minutes=validity_minutes)
        else:
            self._send_msg91_via_sms_flow(phone=phone, otp_code=otp_code)

        test_phone = str(self.settings.onboarding_test_sms_target or "").strip()
        if test_phone and self._normalize_phone(test_phone) != self._normalize_phone(phone):
            if self.settings.sms_msg91_channel == "otp":
                self._send_msg91_via_otp_api(phone=test_phone, otp_code=otp_code, validity_minutes=validity_minutes)
            else:
                self._send_msg91_via_sms_flow(phone=test_phone, otp_code=otp_code)
