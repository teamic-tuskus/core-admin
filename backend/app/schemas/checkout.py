"""Checkout and subscription schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CheckoutIntentRequest(BaseModel):
    """Create checkout intent payload."""

    tenant_id: str = Field(min_length=2, max_length=128)
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


class CheckoutIntentResponse(BaseModel):
    """Checkout intent response."""

    subscription_id: str
    razorpay_order_id: str | None = None
    razorpay_subscription_id: str | None = None
    currency: str
    amount_paise: int
    applied_coupon_code: str | None
    entitlement_modules: list[str]
    entitlement_max_users: int
    entitlement_storage_gb: float
    entitlement_tenure_months: int

    @model_validator(mode="after")
    def validate_gateway_identifier(self) -> "CheckoutIntentResponse":
        if not self.razorpay_order_id and not self.razorpay_subscription_id:
            raise ValueError("Checkout intent requires a Razorpay order or subscription id")
        return self


class CheckoutConfirmRequest(BaseModel):
    """Razorpay callback confirmation payload."""

    subscription_id: str = Field(min_length=2, max_length=128)
    razorpay_order_id: str | None = Field(default=None, min_length=2, max_length=128)
    razorpay_subscription_id: str | None = Field(default=None, min_length=2, max_length=128)
    razorpay_payment_id: str = Field(min_length=2, max_length=128)
    razorpay_signature: str = Field(min_length=10, max_length=512)
    test_payment_bypass: bool = False

    @model_validator(mode="after")
    def validate_gateway_identifier(self) -> "CheckoutConfirmRequest":
        if not self.razorpay_order_id and not self.razorpay_subscription_id:
            raise ValueError("Either razorpay_order_id or razorpay_subscription_id is required")
        return self


class PostPaymentTaskRequest(BaseModel):
    """Internal payload for durable post-payment task processing."""

    subscription_id: str = Field(min_length=2, max_length=128)


class SubscriptionResponse(BaseModel):
    """Subscription response."""

    id: str
    tenant_id: str
    product_id: str
    status: str
    start_at: datetime | None
    end_at: datetime | None
    modules: list[str]
    max_users: int
    tenure_months: int
    currency: str
    amount_paise: int
    coupon_code: str | None
    created_at: datetime
    updated_at: datetime
