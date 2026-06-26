"""CoreAdmin backend entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_v1_router
from app.core.secret_manager import get_secret_manager, init_secret_manager
from app.core.settings import get_settings
from app.exceptions.quota import QuotaExceededError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="CoreAdmin API")


def _build_cors_origins() -> list[str]:
    settings = get_settings()
    configured = [origin for origin in settings.cors_allowed_origins if origin]
    portal_origin = settings.coreadmin_portal_base_url.rstrip("/")
    origins = {portal_origin, *configured}
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize providers and verify required secrets are available."""
    settings = get_settings()
    # Set both root logger and this module's logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))
    logger.setLevel(getattr(logging, settings.log_level))
    init_secret_manager(
        project_id=settings.gcp_project_id,
        default_version=settings.gcp_secret_version,
    )
    # Skip secret warmup in test bypass mode (no Razorpay needed)
    if settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled:
        # Fail fast by validating that every required secret is available in GCP.
        get_secret_manager().warmup(settings.secret_ids)
    if settings.smtp_enabled and (settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled):
        get_secret_manager().warmup(
            (
                settings.smtp_username_secret_id,
                settings.smtp_password_secret_id,
                settings.smtp_from_email_secret_id,
            )
        )
    if settings.sms_enabled and (settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled):
        get_secret_manager().warmup((settings.sms_msg91_auth_key_secret_id,))
    if settings.deepvue_enabled and (settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled):
        get_secret_manager().warmup(
            (
                settings.deepvue_client_id_secret_id,
                settings.deepvue_client_secret_secret_id,
            )
        )
    if settings.core_subscription_sync_enabled and (settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled):
        get_secret_manager().warmup((settings.core_subscription_sync_token_secret_id,))
    if settings.invoicing_enabled and (settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled):
        get_secret_manager().warmup(
            (
                settings.zoho_books_access_token_secret_id,
                settings.zoho_books_organization_id_secret_id,
            )
        )
    if (
        settings.post_payment_async_enabled
        and settings.post_payment_async_mode == "cloud_tasks"
        and (settings.environment == "production" or not settings.checkout_test_payment_bypass_enabled)
    ):
        get_secret_manager().warmup((settings.post_payment_tasks_token_secret_id,))
    logger.info("CoreAdmin startup complete with GCP Secret Manager validation")


@app.exception_handler(QuotaExceededError)
async def quota_exceeded_exception_handler(request: Request, exc: QuotaExceededError) -> JSONResponse:
    """Handle quota exceeded errors with 402 Payment Required."""
    return JSONResponse(
        status_code=402,
        content={
            "success": False,
            "error": exc.quota_type,
            "detail": exc.message,
            "upgrade_url": "https://coreadmin.tuskus.com/billing",
        },
    )


app.include_router(api_v1_router, prefix="/api/v1")