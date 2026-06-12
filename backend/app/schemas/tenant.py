"""Tenant administration schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TenantCreateRequest(BaseModel):
    """Create tenant payload."""

    name: str = Field(min_length=2, max_length=128)
    company_email: str = Field(min_length=3, max_length=255)
    contact_name: str = Field(min_length=2, max_length=128)
    phone: str | None = Field(default=None, max_length=32)


class TenantUpdateRequest(BaseModel):
    """Update tenant payload."""

    name: str | None = Field(default=None, min_length=2, max_length=128)
    company_email: str | None = Field(default=None, min_length=3, max_length=255)
    contact_name: str | None = Field(default=None, min_length=2, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)


class TenantResponse(BaseModel):
    """Tenant response object."""

    id: str
    name: str
    company_email: str
    contact_name: str
    phone: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SubscriptionAdminResponse(BaseModel):
    """Subscription management response."""

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
    product_snapshot: dict[str, Any] | None = None
    coupon_snapshot: dict[str, Any] | None = None
    version: int = 1
    root_subscription_id: str | None = None
    previous_subscription_id: str | None = None
    is_current: bool = True
    change_reason: str | None = None
    superseded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    gateway_status: str | None = None
    reconciled_at: datetime | None = None


class SubscriptionStatusUpdateRequest(BaseModel):
    """Update subscription status payload."""

    status: str = Field(min_length=3, max_length=32)
