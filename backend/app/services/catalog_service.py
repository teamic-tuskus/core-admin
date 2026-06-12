"""Product and coupon domain services."""

from __future__ import annotations

from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta

from app.services.repositories import CouponRepository, ProductRepository, SubscriptionRepository, TenantRepository


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class CatalogService:
    """Business operations for products and coupons."""

    def __init__(
        self,
        product_repo: ProductRepository,
        coupon_repo: CouponRepository,
        subscription_repo: SubscriptionRepository,
        tenant_repo: TenantRepository,
    ) -> None:
        self.product_repo = product_repo
        self.coupon_repo = coupon_repo
        self.subscription_repo = subscription_repo
        self.tenant_repo = tenant_repo

    @staticmethod
    def _is_advance_coupon_payload(payload: dict) -> bool:
        return bool(
            payload.get("exclusive_for_tenant_id")
            or payload.get("override_tenure_months") is not None
            or payload.get("override_max_users") is not None
            or payload.get("override_modules")
            or payload.get("valid_from")
            or payload.get("valid_until")
        )

    @staticmethod
    def _build_coupon_snapshot(coupon: dict) -> dict:
        return {
            "id": coupon["id"],
            "code": coupon["code"],
            "product_id": coupon.get("product_id"),
            "discount_percent": coupon.get("discount_percent"),
            "discount_amount_paise": coupon.get("discount_amount_paise"),
            "override_modules": list(coupon["override_modules"]) if coupon.get("override_modules") else None,
            "override_max_users": coupon.get("override_max_users"),
            "override_tenure_months": coupon.get("override_tenure_months"),
            "exclusive_for_tenant_id": coupon.get("exclusive_for_tenant_id"),
            "valid_from": coupon.get("valid_from"),
            "valid_until": coupon.get("valid_until"),
            "max_redemptions": coupon.get("max_redemptions"),
        }

    @staticmethod
    def _normalize_home_view(home_view: dict | None) -> dict | None:
        if home_view is None:
            return None

        payload = dict(home_view)
        payload["modules"] = CatalogService._normalize_home_modules(payload.get("modules"))

        users_text = payload.get("users_text")
        if isinstance(users_text, str):
            users_text = users_text.strip()
            payload["users_text"] = users_text or None

        description_text = payload.get("description_text")
        if isinstance(description_text, str):
            description_text = description_text.strip()
            payload["description_text"] = description_text or None

        return payload

    @staticmethod
    def _normalize_home_modules(modules: object) -> list[dict] | None:
        if not isinstance(modules, list):
            return None

        rows: list[dict] = []
        seen_orders: set[int] = set()
        for item in modules:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            order = int(item.get("order") or 0)
            if not label or order <= 0:
                continue
            if order in seen_orders:
                raise ValueError("Home view module order values must be unique")
            seen_orders.add(order)
            rows.append({"label": label, "order": order})

        if not rows:
            return None
        return sorted(rows, key=lambda row: row["order"])

    @staticmethod
    def _normalize_checkout_view(checkout_view: dict | None) -> dict | None:
        if checkout_view is None:
            return None

        payload = dict(checkout_view)
        for key in ("summary_plan_name_template", "summary_price_line_template", "commitment_note_text"):
            value = payload.get(key)
            if isinstance(value, str):
                value = value.strip()
                payload[key] = value or None

        trust_rows = payload.get("trust_rows")
        if isinstance(trust_rows, list):
            cleaned = [str(item).strip() for item in trust_rows if str(item).strip()]
            payload["trust_rows"] = cleaned or None

        return payload

    @staticmethod
    def _compute_billing_cycles(pricing: list[dict]) -> dict:
        monthly = next((item for item in pricing if int(item.get("tenure_months") or 0) == 1), None)
        yearly = next((item for item in pricing if int(item.get("tenure_months") or 0) == 12), None)
        if monthly is None or yearly is None:
            raise ValueError("Both monthly and yearly pricing tiers are required")

        monthly_amount = int(monthly.get("amount_paise") or 0)
        yearly_amount = int(yearly.get("amount_paise") or 0)
        if monthly_amount <= 0 or yearly_amount <= 0:
            raise ValueError("Monthly and yearly amounts must be positive")
        if yearly_amount >= monthly_amount * 12:
            raise ValueError("Yearly amount must include a discount compared to 12 monthly payments")

        monthly_baseline = monthly_amount * 12
        discount_percent = round(((monthly_baseline - yearly_amount) / monthly_baseline) * 100, 2)
        return {
            "monthly_amount_paise": monthly_amount,
            "yearly_amount_paise": yearly_amount,
            "yearly_discount_percent": discount_percent,
        }

    @staticmethod
    def _normalize_pricing(payload: dict) -> list[dict]:
        billing_cycles = payload.get("billing_cycles")
        if isinstance(billing_cycles, dict):
            return CatalogService._pricing_from_billing_cycles(billing_cycles)

        pricing = payload.get("pricing")
        if not isinstance(pricing, list) or not pricing:
            raise ValueError("Both monthly and yearly pricing tiers are required")

        cleaned = CatalogService._clean_pricing_rows(pricing)
        CatalogService._compute_billing_cycles(cleaned)
        return sorted(cleaned, key=lambda item: item["tenure_months"])

    @staticmethod
    def _pricing_from_billing_cycles(billing_cycles: dict) -> list[dict]:
        monthly_amount = int(billing_cycles.get("monthly_amount_paise") or 0)
        yearly_amount = int(billing_cycles.get("yearly_amount_paise") or 0)
        if monthly_amount <= 0 or yearly_amount <= 0:
            raise ValueError("Monthly and yearly amounts must be positive")
        if yearly_amount >= monthly_amount * 12:
            raise ValueError("Yearly amount must include a discount compared to 12 monthly payments")
        return [
            {"tenure_months": 1, "amount_paise": monthly_amount},
            {"tenure_months": 12, "amount_paise": yearly_amount},
        ]

    @staticmethod
    def _clean_pricing_rows(pricing: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        seen_tenures: set[int] = set()
        for item in pricing:
            if not isinstance(item, dict):
                continue
            tenure_months = int(item.get("tenure_months") or 0)
            amount_paise = int(item.get("amount_paise") or 0)
            if tenure_months <= 0 or amount_paise <= 0:
                continue
            if tenure_months in seen_tenures:
                raise ValueError("Pricing tiers must have unique tenure_months")
            seen_tenures.add(tenure_months)
            cleaned.append({"tenure_months": tenure_months, "amount_paise": amount_paise})
        return cleaned

    @staticmethod
    def _with_billing_cycles(item: dict) -> dict:
        pricing = list(item.get("pricing") or [])
        enriched = dict(item)
        enriched["is_most_popular"] = bool(item.get("is_most_popular", False))
        enriched["is_live"] = bool(item.get("is_live", True))
        try:
            series_order = int(item.get("series_order", 100))
        except (TypeError, ValueError):
            series_order = 100
        enriched["series_order"] = max(series_order, 1)
        try:
            enriched["billing_cycles"] = CatalogService._compute_billing_cycles(pricing)
        except ValueError:
            enriched["billing_cycles"] = None
        enriched["pricing"] = pricing
        return enriched

    def _apply_advance_coupon_to_subscription(self, *, coupon: dict, active_subscription: dict) -> None:
        additional_modules = list(coupon.get("override_modules") or [])
        next_modules = sorted(set(list(active_subscription.get("modules") or []) + additional_modules))

        next_max_users = int(active_subscription.get("max_users") or 0)
        if coupon.get("override_max_users") is not None:
            next_max_users += int(coupon["override_max_users"])

        next_tenure_months = int(active_subscription.get("tenure_months") or 0)
        if coupon.get("override_tenure_months") is not None:
            next_tenure_months += int(coupon["override_tenure_months"])

        next_end_at = active_subscription.get("end_at")
        if next_end_at and coupon.get("override_tenure_months") is not None:
            next_end_at = next_end_at + relativedelta(months=int(coupon["override_tenure_months"]))

        self.subscription_repo.create_version(
            active_subscription["id"],
            {
                "tenant_id": active_subscription["tenant_id"],
                "product_id": active_subscription["product_id"],
                "product_snapshot": active_subscription.get("product_snapshot"),
                "modules": next_modules,
                "max_users": next_max_users,
                "tenure_months": next_tenure_months,
                "currency": active_subscription["currency"],
                "amount_paise": int(active_subscription["amount_paise"]),
                "coupon_code": coupon["code"],
                "coupon_snapshot": self._build_coupon_snapshot(coupon),
                "customer_name": active_subscription.get("customer_name"),
                "customer_email": active_subscription.get("customer_email"),
                "customer_phone": active_subscription.get("customer_phone"),
                "start_at": active_subscription.get("start_at"),
                "end_at": next_end_at,
                "razorpay_order_id": active_subscription.get("razorpay_order_id"),
                "razorpay_payment_id": active_subscription.get("razorpay_payment_id"),
                "status": "active",
                "change_reason": "advance_coupon",
            },
        )
        self.coupon_repo.reserve_redemption(coupon["id"])

    def create_product(self, payload: dict) -> dict:
        """Create a product with deterministic module ordering."""
        normalized_pricing = self._normalize_pricing(payload)
        data = {
            **payload,
            "code": payload["code"].strip().upper(),
            "modules": sorted(set(payload["modules"])),
            "pricing": normalized_pricing,
            "home_view": self._normalize_home_view(payload.get("home_view")),
            "checkout_view": self._normalize_checkout_view(payload.get("checkout_view")),
            "is_most_popular": bool(payload.get("is_most_popular", False)),
            "is_live": bool(payload.get("is_live", True)),
            "series_order": max(int(payload.get("series_order", 100)), 1),
        }
        data.pop("billing_cycles", None)
        created = self.product_repo.create(data)
        return self._with_billing_cycles(created)

    def list_products(self) -> list[dict]:
        """List all products."""
        return [self._with_billing_cycles(item) for item in self.product_repo.list()]

    def update_product(self, product_id: str, payload: dict) -> dict:
        """Update product with deterministic module ordering and normalized code."""
        data = dict(payload)
        if "modules" in data and data["modules"] is not None:
            data["modules"] = sorted(set(data["modules"]))
        if "code" in data and data["code"] is not None:
            data["code"] = str(data["code"]).strip().upper()
        if "billing_cycles" in data or "pricing" in data:
            data["pricing"] = self._normalize_pricing(data)
        data.pop("billing_cycles", None)
        if "home_view" in data:
            data["home_view"] = self._normalize_home_view(data.get("home_view"))
        if "checkout_view" in data:
            data["checkout_view"] = self._normalize_checkout_view(data.get("checkout_view"))
        if "is_most_popular" in data:
            data["is_most_popular"] = bool(data.get("is_most_popular"))
        if "is_live" in data:
            data["is_live"] = bool(data.get("is_live"))
        if "series_order" in data and data["series_order"] is not None:
            try:
                data["series_order"] = max(int(data["series_order"]), 1)
            except (TypeError, ValueError) as exc:
                raise ValueError("Series order must be a positive number") from exc

        item = self.product_repo.update(product_id, data)
        if item is None:
            raise ValueError("Product not found")
        return self._with_billing_cycles(item)

    def delete_product(self, product_id: str) -> bool:
        """Delete product by id."""
        deleted = self.product_repo.delete(product_id)
        if not deleted:
            raise ValueError("Product not found")
        return True

    def create_coupon(self, payload: dict) -> dict:
        """Create coupon and enforce code normalization."""
        data = {
            **payload,
            "code": payload["code"].strip().upper(),
        }
        is_advance_coupon = self._is_advance_coupon_payload(data)
        active_subscription: dict | None = None

        if is_advance_coupon:
            tenant_id = str(data.get("exclusive_for_tenant_id") or "").strip()
            if self.tenant_repo.get(tenant_id) is None:
                raise ValueError("Tenant not found")
            active_subscription = self.subscription_repo.find_active_by_tenant(tenant_id)
            if active_subscription is None:
                raise ValueError("No active subscription found for this tenant")
            data["max_redemptions"] = 1

        coupon = self.coupon_repo.create(data)
        if is_advance_coupon and active_subscription is not None:
            self._apply_advance_coupon_to_subscription(coupon=coupon, active_subscription=active_subscription)
        return coupon

    def list_coupons(self) -> list[dict]:
        """List all coupons."""
        return [item for item in self.coupon_repo.list() if str(item.get("status") or "active") != "deleted"]

    def pause_coupon(self, coupon_id: str) -> dict:
        """Pause an active coupon."""
        item = self.coupon_repo.pause(coupon_id)
        if item is None:
            raise ValueError("Coupon not found")
        return item

    def delete_coupon(self, coupon_id: str) -> bool:
        """Soft-delete a coupon so it cannot be redeemed further."""
        item = self.coupon_repo.soft_delete(coupon_id)
        if item is None:
            raise ValueError("Coupon not found")
        return True

    def resolve_coupon(self, coupon_code: str | None, tenant_id: str, product_id: str) -> dict | None:
        """Validate coupon scope and validity."""
        if not coupon_code:
            return None

        coupon = self.coupon_repo.get_by_code(coupon_code)
        if coupon is None:
            raise ValueError("Invalid coupon code")

        now = _utc_now()
        if coupon.get("valid_from") and now < coupon["valid_from"]:
            raise ValueError("Coupon is not active yet")
        if coupon.get("valid_until") and now > coupon["valid_until"]:
            raise ValueError("Coupon has expired")
        if str(coupon.get("status") or "active") != "active":
            raise ValueError("Coupon is not active")
        if coupon.get("product_id") and coupon["product_id"] != product_id:
            raise ValueError("Coupon not applicable for this product")
        if coupon.get("exclusive_for_tenant_id") and coupon["exclusive_for_tenant_id"] != tenant_id:
            raise ValueError("Coupon not applicable for this tenant")
        max_redemptions = coupon.get("max_redemptions")
        if max_redemptions is not None and coupon["redemption_count"] >= max_redemptions:
            raise ValueError("Coupon redemption limit reached")
        return coupon

    def increment_coupon_redemption(self, coupon_code: str) -> None:
        """Mark a coupon as redeemed after successful activation."""
        coupon = self.coupon_repo.get_by_code(coupon_code)
        if coupon is None:
            raise ValueError("Invalid coupon code")
        self.coupon_repo.reserve_redemption(coupon["id"])
