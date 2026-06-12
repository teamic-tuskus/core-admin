"""Application configuration.

Security rule: secrets are never sourced from environment variables or files.
Only secret identifiers are configured here; values come from GCP Secret Manager.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_tuple_config(value: object) -> tuple[str, ...] | object:
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",") if item.strip()]
        return tuple(parts)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return value


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="COREADMIN_", case_sensitive=False)

    app_name: str = "CoreAdmin API"
    environment: Literal["local", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    storage_backend: Literal["memory", "firestore"] = "firestore"
    firebase_storage_bucket: str | None = None
    checkout_test_payment_bypass_enabled: bool = False

    gcp_project_id: str
    gcp_secret_version: str = "latest"

    smtp_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_timeout_seconds: int = 15
    smtp_from_name: str = "Tuskus Core"
    support_email: str = "support@tuskus.com"
    smtp_username_secret_id: str = "smtp-username"
    smtp_password_secret_id: str = "smtp-password"
    smtp_from_email_secret_id: str = "smtp-from-email"

    invoicing_enabled: bool = False
    invoice_http_timeout_seconds: int = 20
    invoice_email_subject_prefix: str = "Core Invoice"
    zoho_books_enabled: bool = False
    zoho_books_api_base: str = "https://www.zohoapis.in/books/v3"
    zoho_oauth_api_base: str = "https://accounts.zoho.in"
    zoho_books_auto_refresh_enabled: bool = True
    zoho_books_access_token_secret_id: str = "zoho-books-access-token"
    zoho_books_refresh_token_secret_id: str = "zoho-books-refresh-token"
    zoho_books_client_id_secret_id: str = "zoho-books-client-id"
    zoho_books_client_secret_secret_id: str = "zoho-books-client-secret"
    zoho_books_organization_id_secret_id: str = "zoho-books-organization-id"

    deepvue_enabled: bool = False
    deepvue_base_url: str = "https://production.deepvue.tech"
    deepvue_auth_endpoint: str = "/v1/authorize"
    deepvue_gstin_verify_endpoint: str = "/v1/verification/gstin-advanced"
    deepvue_timeout_seconds: int = 15
    deepvue_client_id_secret_id: str = "deepvue-client-id"
    deepvue_client_secret_secret_id: str = "deepvue-client-secret"

    onboarding_test_email_target: str | None = None
    onboarding_test_sms_target: str | None = None
    onboarding_redirect_url: str = "https://core.tuskus.com"

    sms_enabled: bool = False
    sms_provider: Literal["msg91"] = "msg91"
    sms_msg91_channel: Literal["sms_flow", "otp"] = "sms_flow"
    sms_country_code: str = "91"
    sms_msg91_template_id: str | None = None
    sms_msg91_sender_id: str | None = None
    sms_msg91_flow_var_key: str = "VAR1"
    sms_msg91_flow_short_url: str = "0"
    sms_msg91_auth_key_secret_id: str = "msg91-auth-key"

    otp_code_length: int = 6
    otp_expiry_minutes: int = 10
    otp_resend_cooldown_seconds: int = 60
    otp_max_attempts: int = 5
    otp_max_sends_per_window: int = 5
    otp_send_window_minutes: int = 15
    otp_hash_pepper_secret_id: str = "jwt-signing-key"

    coreadmin_portal_base_url: str = "https://coreadmin.tuskus.com"
    core_api_base_url: str = "https://api.tuskus.com/api/v1"
    core_subscription_sync_enabled: bool = True
    core_subscription_sync_timeout_seconds: int = 12
    core_subscription_sync_token_secret_id: str = "coreadmin-sync-token"
    post_payment_async_enabled: bool = True
    post_payment_async_mode: Literal["thread", "cloud_tasks"] = "cloud_tasks"
    post_payment_tasks_queue_id: str = "coreadmin-post-payment"
    post_payment_tasks_location: str = "asia-south1"
    post_payment_tasks_handler_url: str | None = None
    post_payment_tasks_token_secret_id: str = "coreadmin-post-payment-task-token"
    core_firebase_api_key_secret_id: str = "core-firebase-api-key"
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )
    super_admin_invitation_expiry_days: int = 7
    portal_invitation_resend_cooldown_seconds: int = 90
    portal_invitation_resend_max_per_hour: int = 6

    # Secret names only. Values are always loaded from GCP Secret Manager.
    secret_ids: tuple[str, ...] = (
        "firebase-service-account-json",
        "razorpay-key-id",
        "razorpay-key-secret",
        "razorpay-webhook-secret",
        "jwt-signing-key",
    )

    @field_validator("secret_ids", mode="before")
    @classmethod
    def parse_secret_ids(cls, value: object) -> tuple[str, ...]:
        """Allow comma-separated env input while keeping strict tuple output."""
        return _parse_tuple_config(value)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: object) -> tuple[str, ...]:
        """Allow comma-separated env input while keeping strict tuple output."""
        return _parse_tuple_config(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
