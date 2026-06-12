"""Robust OTP challenge service for email verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import logging
import secrets
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from app.core.settings import get_settings
from app.services.email_sender import SmtpEmailSender
from app.services.sms_sender import SmsSender

logger = logging.getLogger(__name__)

OtpChannel = Literal["email", "sms"]


class OtpError(ValueError):
    """Domain error for OTP failures."""


@dataclass
class OtpPolicy:
    code_length: int = 6
    expiry_minutes: int = 10
    resend_cooldown_seconds: int = 60
    max_attempts: int = 5
    max_sends_per_window: int = 5
    send_window_minutes: int = 15


class OtpService:
    """Creates OTP challenges, dispatches OTPs, and verifies submissions."""

    def __init__(
        self,
        *,
        otp_repo,
        email_sender: SmtpEmailSender,
        sms_sender: SmsSender | None = None,
        otp_hash_pepper: str,
        policy: OtpPolicy,
    ) -> None:
        self.otp_repo = otp_repo
        self.email_sender = email_sender
        self.sms_sender = sms_sender
        self.otp_hash_pepper = otp_hash_pepper
        self.policy = policy
        self.settings = get_settings()

    def _is_non_production_bypass_enabled(self) -> bool:
        return self.settings.environment != "production" and self.settings.checkout_test_payment_bypass_enabled

    @staticmethod
    def _now() -> datetime:
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _normalize_target(channel: OtpChannel, target: str) -> str:
        if channel == "email":
            return target.strip().lower()
        return "".join(ch for ch in str(target) if ch.isdigit())

    @staticmethod
    def _mask_target(channel: OtpChannel, target: str) -> str:
        if channel == "sms":
            digits = "".join(ch for ch in str(target) if ch.isdigit())
            if len(digits) < 6:
                return "******"
            return f"{digits[:2]}******{digits[-2:]}"
        name, _, domain = target.partition("@")
        if len(name) <= 2:
            masked_name = name[0] + "*" if name else "*"
        else:
            masked_name = name[:2] + "*" * max(1, len(name) - 2)
        return f"{masked_name}@{domain}"

    def _target_hash(self, channel: OtpChannel, target: str, purpose: str) -> str:
        msg = f"{channel}:{purpose}:{target}".encode("utf-8")
        key = self.otp_hash_pepper.encode("utf-8")
        return hmac.new(key, msg, sha256).hexdigest()

    def _otp_hash(self, otp_code: str, salt: str) -> str:
        msg = f"{salt}:{otp_code}".encode("utf-8")
        key = self.otp_hash_pepper.encode("utf-8")
        return hmac.new(key, msg, sha256).hexdigest()

    def _new_code(self) -> str:
        limit = 10 ** self.policy.code_length
        return f"{secrets.randbelow(limit):0{self.policy.code_length}d}"

    def send_otp(self, *, channel: OtpChannel, target: str, purpose: str) -> dict:
        now = self._now()
        normalized_target = self._normalize_target(channel, target)
        target_hash = self._target_hash(channel, normalized_target, purpose)

        sends = self.otp_repo.count_recent_sends(
            channel=channel,
            target_hash=target_hash,
            purpose=purpose,
            since=now - timedelta(minutes=self.policy.send_window_minutes),
        )
        if sends >= self.policy.max_sends_per_window:
            raise OtpError("Too many OTP requests. Please try again later.")

        active = self.otp_repo.get_active(
            channel=channel,
            target_hash=target_hash,
            purpose=purpose,
            now=now,
        )
        if active and active.get("resend_available_at") and now < active["resend_available_at"]:
            retry_after = int((active["resend_available_at"] - now).total_seconds())
            raise OtpError(f"Please wait {max(1, retry_after)} seconds before requesting another OTP.")

        # In non-production bypass mode with unavailable delivery transports,
        # use a deterministic code so onboarding can proceed without SMTP/SMS.
        use_dev_fallback_code = (
            self._is_non_production_bypass_enabled()
            and ((channel == "email" and not self.email_sender.enabled) or (channel == "sms" and self.sms_sender is None))
        )
        otp_code = "000000" if use_dev_fallback_code else self._new_code()
        challenge_id = f"otp_{uuid4().hex}"
        salt = secrets.token_hex(8)
        expires_at = now + timedelta(minutes=self.policy.expiry_minutes)
        resend_at = now + timedelta(seconds=self.policy.resend_cooldown_seconds)
        challenge = {
            "id": challenge_id,
            "channel": channel,
            "target": normalized_target,
            "target_hash": target_hash,
            "masked_target": self._mask_target(channel, normalized_target),
            "purpose": purpose,
            "otp_hash": self._otp_hash(otp_code, salt),
            "otp_salt": salt,
            "status": "active",
            "attempt_count": 0,
            "max_attempts": self.policy.max_attempts,
            "expires_at": expires_at,
            "resend_available_at": resend_at,
            "created_at": now,
            "updated_at": now,
            "verified_at": None,
        }
        self.otp_repo.create(challenge)

        if use_dev_fallback_code:
            logger.warning(
                "OTP bypass fallback active: using deterministic code for local testing (dev/staging mode only)",
                extra={
                    "channel": channel,
                    "target": self._mask_target(channel, normalized_target),
                    "purpose": purpose,
                    "validity_minutes": self.policy.expiry_minutes,
                },
            )
        else:
            if channel == "email":
                self.email_sender.send_otp_email(
                    to_email=normalized_target,
                    otp_code=otp_code,
                    validity_minutes=self.policy.expiry_minutes,
                )
            else:
                if self.sms_sender is None:
                    raise OtpError("OTP delivery is temporarily unavailable. Please try again shortly.")
                self.sms_sender.send_otp_sms(
                    phone=normalized_target,
                    otp_code=otp_code,
                    validity_minutes=self.policy.expiry_minutes,
                )

        return {
            "challenge_id": challenge_id,
            "channel": channel,
            "masked_target": challenge["masked_target"],
            "expires_at": expires_at,
            "resend_available_at": resend_at,
        }

    def verify_otp(self, *, challenge_id: str, otp_code: str) -> dict:
        now = self._now()
        challenge = self.otp_repo.get(challenge_id)
        if challenge is None:
            raise OtpError("OTP challenge not found")
        if challenge["status"] != "active":
            raise OtpError("OTP challenge is no longer active")
        if now > challenge["expires_at"]:
            self.otp_repo.update(
                challenge_id,
                {"status": "expired", "updated_at": now},
            )
            raise OtpError("OTP has expired")

        expected_hash = challenge.get("otp_hash", "")
        computed_hash = self._otp_hash(otp_code.strip(), str(challenge.get("otp_salt") or ""))
        if not hmac.compare_digest(expected_hash, computed_hash):
            attempts = int(challenge.get("attempt_count", 0)) + 1
            updates = {"attempt_count": attempts, "updated_at": now}
            if attempts >= int(challenge.get("max_attempts", self.policy.max_attempts)):
                updates["status"] = "locked"
            self.otp_repo.update(challenge_id, updates)
            remaining = max(0, int(challenge.get("max_attempts", self.policy.max_attempts)) - attempts)
            if remaining <= 0:
                raise OtpError("OTP verification locked due to too many failed attempts")
            raise OtpError(f"Invalid OTP. {remaining} attempt(s) remaining.")

        self.otp_repo.update(
            challenge_id,
            {
                "status": "verified",
                "verified_at": now,
                "updated_at": now,
            },
        )
        return {
            "verified": True,
            "purpose": challenge["purpose"],
            "channel": challenge["channel"],
            "target": challenge["target"],
            "verified_at": now,
        }
