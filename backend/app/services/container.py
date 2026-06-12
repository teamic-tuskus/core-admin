"""Service container for dependency wiring."""

from __future__ import annotations

from functools import lru_cache

from app.core.settings import get_settings
from app.services.catalog_service import CatalogService
from app.services.checkout_service import CheckoutService
from app.services.core_subscription_sync import CoreSubscriptionSyncService
from app.services.email_sender import SmtpEmailSender
from app.services.invoice_service import InvoiceService
from app.services.firestore_repositories import (
    FirestoreCouponRepository,
    FirestoreGstPoolRepository,
    FirestoreIdempotencyRepository,
    FirestoreOnboardingSessionRepository,
    FirestoreOtpChallengeRepository,
    FirestoreProductRepository,
    FirestoreRateLimitRepository,
    FirestoreSubscriptionRepository,
    FirestoreTenantRepository,
    FirestoreWebhookEventRepository,
)
from app.services.gst_verification_service import GstVerificationService
from app.services.onboarding_service import OnboardingService
from app.services.otp_service import OtpPolicy, OtpService
from app.services.payment_gateway import RazorpayGateway
from app.services.rate_limiter import RateLimiterService
from app.services.sms_sender import SmsSender
from app.services.repositories import (
    CouponRepository,
    GstPoolRepository,
    IdempotencyRepository,
    OnboardingSessionRepository,
    OtpChallengeRepository,
    ProductRepository,
    RateLimitRepository,
    SubscriptionRepository,
    TenantRepository,
    WebhookEventRepository,
)
from app.core.secret_manager import get_secret


@lru_cache(maxsize=1)
def get_service_bundle() -> dict[str, object]:
    settings = get_settings()
    if settings.storage_backend == "firestore":
        product_repo = FirestoreProductRepository()
        coupon_repo = FirestoreCouponRepository()
        gst_pool_repo = FirestoreGstPoolRepository()
        subscription_repo = FirestoreSubscriptionRepository()
        idempotency_repo = FirestoreIdempotencyRepository()
        webhook_repo = FirestoreWebhookEventRepository()
        rate_limit_repo = FirestoreRateLimitRepository()
        otp_repo = FirestoreOtpChallengeRepository()
        tenant_repo = FirestoreTenantRepository()
        onboarding_repo = FirestoreOnboardingSessionRepository()
    else:
        product_repo = ProductRepository()
        coupon_repo = CouponRepository()
        gst_pool_repo = GstPoolRepository()
        subscription_repo = SubscriptionRepository()
        idempotency_repo = IdempotencyRepository()
        webhook_repo = WebhookEventRepository()
        rate_limit_repo = RateLimitRepository()
        otp_repo = OtpChallengeRepository()
        tenant_repo = TenantRepository()
        onboarding_repo = OnboardingSessionRepository()

    catalog_service = CatalogService(
        product_repo=product_repo,
        coupon_repo=coupon_repo,
        subscription_repo=subscription_repo,
        tenant_repo=tenant_repo,
    )
    gateway = RazorpayGateway()
    invoice_service = None
    if settings.invoicing_enabled and settings.zoho_books_enabled:
        invoice_service = InvoiceService(
            gateway=gateway,
            email_sender=SmtpEmailSender(),
        )
    checkout_service = CheckoutService(
        product_repo=product_repo,
        subscription_repo=subscription_repo,
        idempotency_repo=idempotency_repo,
        webhook_repo=webhook_repo,
        catalog_service=catalog_service,
        gateway=gateway,
        invoice_service=invoice_service,
        email_sender=SmtpEmailSender(),
    )
    otp_service = OtpService(
        otp_repo=otp_repo,
        email_sender=SmtpEmailSender(),
        sms_sender=SmsSender(),
        otp_hash_pepper=get_secret(settings.otp_hash_pepper_secret_id),
        policy=OtpPolicy(
            code_length=settings.otp_code_length,
            expiry_minutes=settings.otp_expiry_minutes,
            resend_cooldown_seconds=settings.otp_resend_cooldown_seconds,
            max_attempts=settings.otp_max_attempts,
            max_sends_per_window=settings.otp_max_sends_per_window,
            send_window_minutes=settings.otp_send_window_minutes,
        ),
    )
    gst_verification_service = GstVerificationService(gst_pool_repo=gst_pool_repo)
    onboarding_service = OnboardingService(
        subscription_repo=subscription_repo,
        tenant_repo=tenant_repo,
        onboarding_repo=onboarding_repo,
        gst_verification_service=gst_verification_service,
        otp_service=otp_service,
        email_sender=SmtpEmailSender(),
        core_subscription_sync_service=(
            CoreSubscriptionSyncService(
                base_url=settings.core_api_base_url,
                sync_token=get_secret(settings.core_subscription_sync_token_secret_id),
                timeout_seconds=settings.core_subscription_sync_timeout_seconds,
            )
            if settings.core_subscription_sync_enabled
            else None
        ),
    )
    rate_limiter = RateLimiterService(repo=rate_limit_repo)
    return {
        "product_repo": product_repo,
        "coupon_repo": coupon_repo,
        "gst_pool_repo": gst_pool_repo,
        "subscription_repo": subscription_repo,
        "idempotency_repo": idempotency_repo,
        "webhook_repo": webhook_repo,
        "rate_limit_repo": rate_limit_repo,
        "otp_repo": otp_repo,
        "tenant_repo": tenant_repo,
        "onboarding_repo": onboarding_repo,
        "catalog_service": catalog_service,
        "checkout_service": checkout_service,
        "otp_service": otp_service,
        "gst_verification_service": gst_verification_service,
        "onboarding_service": onboarding_service,
        "rate_limiter": rate_limiter,
    }


def get_catalog_service() -> CatalogService:
    return get_service_bundle()["catalog_service"]  # type: ignore[return-value]


def get_checkout_service() -> CheckoutService:
    return get_service_bundle()["checkout_service"]  # type: ignore[return-value]


def get_otp_service() -> OtpService:
    return get_service_bundle()["otp_service"]  # type: ignore[return-value]


def get_onboarding_service() -> OnboardingService:
    return get_service_bundle()["onboarding_service"]  # type: ignore[return-value]


def get_rate_limiter() -> RateLimiterService:
    return get_service_bundle()["rate_limiter"]  # type: ignore[return-value]
