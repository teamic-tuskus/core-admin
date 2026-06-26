"""Public sales-facing schemas with strict surface contracts."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.product import BillingCyclesResponse, CheckoutViewContent, HomeViewContent, PricingOption


class SalesCheckoutIntentRequest(BaseModel):
    """Checkout intent payload accepted from public sales surfaces."""

    product_id: str = Field(min_length=2, max_length=128)
    tenure_months: int = Field(ge=1, le=60)
    requested_users: int | None = Field(default=None, ge=1, le=100000)
    coupon_code: str | None = Field(default=None, max_length=64)
    customer_name: str = Field(min_length=1, max_length=128)
    customer_email: str = Field(min_length=3, max_length=255)
    customer_phone: str | None = Field(default=None, max_length=32)
    company_name: str | None = Field(default=None, max_length=128)
    invoice_gstin: str | None = Field(default=None, max_length=15)
    invoice_address: str | None = Field(default=None, max_length=400)
    invoice_pincode: str | None = Field(default=None, min_length=6, max_length=6)
    idempotency_key: str = Field(min_length=8, max_length=255)


class PublicSalesProductResponse(BaseModel):
    """Public sales product response object."""

    id: str
    code: str
    name: str
    description: str | None
    features: str | None = None
    modules: list[str]
    base_max_users: int
    base_storage_gb: float = 5.0
    pricing: list[PricingOption]
    billing_cycles: BillingCyclesResponse | None = None
    home_view: HomeViewContent | None = None
    checkout_view: CheckoutViewContent | None = None
    is_most_popular: bool = False
    is_live: bool = True
    series_order: int = 100


class PublicSalesCheckoutConfigResponse(BaseModel):
    """Public checkout configuration required by the sales frontend."""

    razorpay_key_id: str
    test_payment_bypass_enabled: bool = False


class PublicSalesOnboardingResumeResponse(BaseModel):
    """Public onboarding resume context resolved from a signed resume token."""

    subscription_id: str
    customer_name: str
    customer_email: str
    customer_phone: str | None = None
    selected_plan: str
    company_name: str | None = None


class SalesContactRequest(BaseModel):
    """Enterprise/contact-us lead payload accepted from public sales surfaces."""

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=32)
    message: str = Field(min_length=10, max_length=2000)


class SalesContactResponse(BaseModel):
    """Acknowledgement payload for sales contact submission."""

    accepted: bool = True
    message: str = "Thank you. Our team will contact you shortly."
