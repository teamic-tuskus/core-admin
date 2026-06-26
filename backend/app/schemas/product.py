"""Product and plan schemas."""

from __future__ import annotations

from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator

ALLOWED_TEMPLATE_TOKENS = {"plan_name", "users_text", "price", "period"}


def _validate_template_tokens(value: str) -> str:
    """Allow only whitelisted template placeholders used by sales surfaces."""
    tokens = re.findall(r"\{([a-z_]+)\}", value)
    invalid = sorted({token for token in tokens if token not in ALLOWED_TEMPLATE_TOKENS})
    if invalid:
        raise ValueError(
            "Template contains unsupported token(s). Allowed: {plan_name}, {users_text}, {price}, {period}."
        )
    return value


class PricingOption(BaseModel):
    """Tenure-specific pricing in minor currency units."""

    tenure_months: int = Field(ge=1, le=60)
    amount_paise: int = Field(ge=1)


class BillingCyclesInput(BaseModel):
    """Explicit pricing inputs for monthly and yearly billing cycles."""

    monthly_amount_paise: int = Field(ge=1)
    yearly_amount_paise: int = Field(ge=1)

    @field_validator("yearly_amount_paise")
    @classmethod
    def validate_yearly_discount(cls, yearly_amount_paise: int, info):
        monthly_amount_paise = int(info.data.get("monthly_amount_paise") or 0)
        if monthly_amount_paise > 0 and yearly_amount_paise >= monthly_amount_paise * 12:
            raise ValueError("Yearly amount must include a discount compared to 12 monthly payments")
        return yearly_amount_paise


class BillingCyclesResponse(BillingCyclesInput):
    """Explicit cycle pricing plus computed yearly discount percent."""

    yearly_discount_percent: float = Field(ge=0, le=100)


class HomeModuleRow(BaseModel):
    """Single display row for home pricing module checklist."""

    label: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1, le=99)


class HomeViewContent(BaseModel):
    """Admin-controlled content shown in CoreSalesWeb home pricing card."""

    users_text: str | None = Field(default=None, min_length=1, max_length=120)
    description_text: str | None = Field(default=None, min_length=1, max_length=400)
    modules: list[HomeModuleRow] | None = Field(default=None, min_length=1, max_length=12)

    @field_validator("modules")
    @classmethod
    def validate_unique_module_order(cls, modules: list[HomeModuleRow] | None) -> list[HomeModuleRow] | None:
        if not modules:
            return modules
        seen: set[int] = set()
        for row in modules:
            if row.order in seen:
                raise ValueError("Home view module order values must be unique")
            seen.add(row.order)
        return sorted(modules, key=lambda row: row.order)


class CheckoutViewContent(BaseModel):
    """Admin-controlled content shown in CoreSalesWeb checkout summary card."""

    summary_plan_name_template: str | None = Field(default=None, min_length=1, max_length=160)
    summary_price_line_template: str | None = Field(default=None, min_length=1, max_length=160)
    commitment_note_text: str | None = Field(default=None, min_length=1, max_length=400)
    trust_rows: list[str] | None = Field(default=None, min_length=1, max_length=8)

    @field_validator("summary_plan_name_template", "summary_price_line_template")
    @classmethod
    def validate_templates(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_template_tokens(value)

    @field_validator("trust_rows")
    @classmethod
    def validate_trust_rows(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("At least one trust row is required when checkout trust rows are provided")
        for row in cleaned:
            if len(row) > 200:
                raise ValueError("Each checkout trust row must be 200 characters or fewer")
        return cleaned


class ProductCreateRequest(BaseModel):
    """Create product payload."""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    features: str | None = Field(default=None, max_length=8000)
    modules: list[str] = Field(min_length=1)
    base_max_users: int = Field(ge=1, le=100000)
    base_storage_gb: float = Field(default=5.0, ge=1.0, le=10000.0)
    pricing: list[PricingOption] | None = Field(default=None, min_length=1)
    billing_cycles: BillingCyclesInput | None = None
    home_view: HomeViewContent | None = None
    checkout_view: CheckoutViewContent | None = None
    is_most_popular: bool = False
    is_live: bool = True
    series_order: int = Field(default=100, ge=1, le=999)


class ProductUpdateRequest(BaseModel):
    """Partial product update payload."""

    code: str | None = Field(default=None, min_length=2, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    features: str | None = Field(default=None, max_length=8000)
    modules: list[str] | None = Field(default=None, min_length=1)
    base_max_users: int | None = Field(default=None, ge=1, le=100000)
    base_storage_gb: float | None = Field(default=None, ge=1.0, le=10000.0)
    pricing: list[PricingOption] | None = Field(default=None, min_length=1)
    billing_cycles: BillingCyclesInput | None = None
    home_view: HomeViewContent | None = None
    checkout_view: CheckoutViewContent | None = None
    is_most_popular: bool | None = None
    is_live: bool | None = None
    series_order: int | None = Field(default=None, ge=1, le=999)


class ProductResponse(BaseModel):
    """Product response object."""

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
    created_at: datetime


class ProductDeleteResponse(BaseModel):
    """Delete response payload."""

    id: str
    deleted: bool
