"""Coupon and discount schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CouponCreateRequest(BaseModel):
    """Create coupon payload."""

    code: str = Field(min_length=3, max_length=64)
    product_id: str | None = None
    discount_percent: int | None = Field(default=None, ge=1, le=100)
    discount_amount_paise: int | None = Field(default=None, ge=1)
    override_tenure_months: int | None = Field(default=None, ge=1, le=60)
    override_max_users: int | None = Field(default=None, ge=1, le=100000)
    override_modules: list[str] | None = None
    exclusive_for_tenant_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_redemptions: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_discount_or_override(self) -> "CouponCreateRequest":
        has_discount = self.discount_percent is not None or self.discount_amount_paise is not None
        has_override = any(
            value is not None
            for value in (
                self.override_tenure_months,
                self.override_max_users,
                self.override_modules if self.override_modules else None,
            )
        )
        is_advance_coupon = bool(
            self.exclusive_for_tenant_id
            or has_override
            or self.valid_from is not None
            or self.valid_until is not None
        )

        if is_advance_coupon:
            if not self.exclusive_for_tenant_id:
                raise ValueError("exclusive_for_tenant_id is required for advance coupons")
            if self.valid_from is not None or self.valid_until is not None:
                raise ValueError("Advance coupons apply immediately and cannot use valid_from or valid_until")
            if has_discount:
                raise ValueError("Advance coupons cannot include discount values")
            if self.product_id is not None:
                raise ValueError("Advance coupons do not use product_id")
            if not has_override:
                raise ValueError("Advance coupon must add at least one subscription value")
        else:
            if not has_discount:
                raise ValueError("Coupon must include a discount")
            if self.discount_percent is not None and self.discount_amount_paise is not None:
                raise ValueError("Set exactly one discount type: percent or amount")

        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class CouponResponse(BaseModel):
    """Coupon response object."""

    id: str
    code: str
    product_id: str | None
    discount_percent: int | None
    discount_amount_paise: int | None
    override_tenure_months: int | None
    override_max_users: int | None
    override_modules: list[str] | None
    exclusive_for_tenant_id: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    max_redemptions: int | None
    redemption_count: int
    status: str = "active"
    paused_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class CouponDeleteResponse(BaseModel):
    """Coupon delete response payload."""

    id: str
    deleted: bool
