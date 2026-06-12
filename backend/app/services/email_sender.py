"""SMTP email sender for OTP and transactional notifications."""

from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage
from typing import Sequence, TypedDict

from app.core.secret_manager import get_secret
from app.core.settings import get_settings


class EmailAttachment(TypedDict):
    filename: str
    content: bytes
    mime_type: str


class SmtpEmailSender:
    """Sends emails using SMTP credentials from GCP Secret Manager."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.smtp_enabled

    def _resolve_credentials(self) -> tuple[str, str, str]:
        username = get_secret(self.settings.smtp_username_secret_id)
        password = get_secret(self.settings.smtp_password_secret_id)
        from_email = get_secret(self.settings.smtp_from_email_secret_id)
        return username, password, from_email

    def _dispatch_message(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        attachments: Sequence[EmailAttachment] | None = None,
    ) -> None:
        username, password, from_email = self._resolve_credentials()

        msg = EmailMessage()
        msg["From"] = f"{self.settings.smtp_from_name} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Reply-To"] = self.settings.support_email
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")
        for attachment in attachments or ():
            filename = str(attachment.get("filename") or "attachment.bin").strip() or "attachment.bin"
            raw = attachment.get("content")
            if not isinstance(raw, (bytes, bytearray)):
                continue
            mime_type = str(attachment.get("mime_type") or "application/octet-stream").strip().lower()
            if "/" in mime_type:
                maintype, subtype = mime_type.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"
            msg.add_attachment(bytes(raw), maintype=maintype, subtype=subtype, filename=filename)

        with smtplib.SMTP(
            host=self.settings.smtp_host,
            port=self.settings.smtp_port,
            timeout=self.settings.smtp_timeout_seconds,
        ) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)

    def send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        attachments: Sequence[EmailAttachment] | None = None,
    ) -> None:
        """Send a transactional email through configured SMTP transport."""
        if not self.enabled:
            raise RuntimeError("SMTP is disabled. Set COREADMIN_SMTP_ENABLED=true to enable email delivery.")
        self._dispatch_message(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
        )

    def send_otp_email(
        self,
        *,
        to_email: str,
        otp_code: str,
        validity_minutes: int = 10,
        product_name: str = "Core",
    ) -> None:
        """Send a branded OTP email with both text and HTML content."""
        if not self.enabled:
            raise RuntimeError("SMTP is disabled. Set COREADMIN_SMTP_ENABLED=true to enable email delivery.")

        safe_product_name = html.escape(product_name.strip() or "Core")
        safe_support_email = html.escape(self.settings.support_email)
        normalized_otp = "".join(ch for ch in otp_code if ch.isdigit()) or otp_code.strip()
        subject = f"Your {product_name} verification code"
        body_text = (
            "Your verification code\n\n"
            f"OTP: {normalized_otp}\n"
            f"This code is valid for {validity_minutes} minutes.\n\n"
            "If you did not request this code, you can safely ignore this email.\n"
            f"Need help? Contact {self.settings.support_email}."
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
                                <p style=\"margin:0;color:#dbeafe;font-size:12px;letter-spacing:0.6px;text-transform:uppercase;font-weight:700;\">Secure Verification</p>
                                <h1 style=\"margin:8px 0 0;color:#ffffff;font-size:24px;line-height:1.3;\">Your one-time password</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:30px 32px 12px;\">
                                <p style=\"margin:0 0 16px;color:#1e293b;font-size:15px;line-height:1.6;\">Use this OTP to continue your sign-in on <strong>{safe_product_name}</strong>.</p>
                                <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f1f5f9;border:1px solid #cbd5e1;border-radius:14px;\">
                                    <tr>
                                        <td align=\"center\" style=\"padding:24px 14px;\">
                                            <p style=\"margin:0 0 10px;color:#334155;font-size:12px;letter-spacing:0.8px;text-transform:uppercase;font-weight:700;\">Verification Code</p>
                                            <p style=\"margin:0;color:#0f172a;font-size:34px;line-height:1;letter-spacing:8px;font-weight:800;\">{html.escape(normalized_otp)}</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:10px 32px 18px;\">
                                <p style=\"margin:0;color:#334155;font-size:13px;line-height:1.7;\">This code expires in <strong>{validity_minutes} minutes</strong> and can only be used once.</p>
                                <p style=\"margin:12px 0 0;color:#475569;font-size:12px;line-height:1.7;\">If you did not request this code, you can safely ignore this email.</p>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:0 32px 28px;\">
                                <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"border-top:1px solid #e2e8f0;padding-top:16px;\">
                                    <tr>
                                        <td style=\"color:#475569;font-size:12px;line-height:1.6;\">Need help? Contact <a href=\"mailto:{safe_support_email}\" style=\"color:#1e40af;text-decoration:underline;font-weight:700;\">{safe_support_email}</a>.</td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
</html>
"""
        self._dispatch_message(to_email=to_email, subject=subject, body_text=body_text, body_html=body_html)
        test_email = str(self.settings.onboarding_test_email_target or "").strip().lower()
        if test_email and test_email != to_email.strip().lower():
            self._dispatch_message(to_email=test_email, subject=subject, body_text=body_text, body_html=body_html)
