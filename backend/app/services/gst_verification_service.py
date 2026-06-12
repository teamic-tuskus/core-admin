"""GST verification with Firebase gst_pool cache and Deepvue fallback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx

from app.core.secret_manager import get_secret
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

GST_UNAVAILABLE_MESSAGE = "GST verification service is temporarily unavailable. Please try again shortly."
GST_NOT_FOUND_MESSAGE = "No taxpayer details found for this GSTIN. Please verify the number."
FALLBACK_BUSINESS_NAME_PREFIX = "GST-"


class GstVerificationService:
    """Cache-first GST verification backed by Deepvue when enabled."""

    def __init__(self, *, gst_pool_repo) -> None:
        self.gst_pool_repo = gst_pool_repo
        self.settings = get_settings()
        self._cached_token: str | None = None
        self._cached_token_expires_at: datetime | None = None

    @staticmethod
    def _clean_str(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _pick_first_from_mapping(payload: dict[str, Any], keys: list[str]) -> Any:
        lowered = {str(key).lower(): value for key, value in payload.items()}
        for key in keys:
            candidate = lowered.get(key.lower())
            if candidate not in (None, ""):
                return candidate
        for value in payload.values():
            nested = GstVerificationService._pick_first(value, keys)
            if nested not in (None, ""):
                return nested
        return None

    @staticmethod
    def _pick_first_from_sequence(payload: list[Any], keys: list[str]) -> Any:
        for item in payload:
            nested = GstVerificationService._pick_first(item, keys)
            if nested not in (None, ""):
                return nested
        return None

    @staticmethod
    def _pick_first(payload: Any, keys: list[str]) -> Any:
        if isinstance(payload, dict):
            return GstVerificationService._pick_first_from_mapping(payload, keys)
        if isinstance(payload, list):
            return GstVerificationService._pick_first_from_sequence(payload, keys)
        return None

    @staticmethod
    def _append_address_values(node: dict[str, Any], *, keys: tuple[str, ...], parts: list[str], seen: set[str]) -> None:
        lowered = {str(key).lower(): value for key, value in node.items()}
        for key in keys:
            value = lowered.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            marker = normalized.lower()
            if normalized and marker not in seen:
                parts.append(normalized)
                seen.add(marker)

    @staticmethod
    def _collect_address_parts(node: Any, *, keys: tuple[str, ...], parts: list[str], seen: set[str]) -> None:
        if isinstance(node, dict):
            GstVerificationService._append_address_values(node, keys=keys, parts=parts, seen=seen)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    GstVerificationService._collect_address_parts(child, keys=keys, parts=parts, seen=seen)
        elif isinstance(node, list):
            for child in node:
                if isinstance(child, (dict, list)):
                    GstVerificationService._collect_address_parts(child, keys=keys, parts=parts, seen=seen)

    @staticmethod
    def _stitch_address_parts(payload: Any) -> str | None:
        keys = (
            "address",
            "line1",
            "line2",
            "street",
            "city",
            "district",
            "state",
            "pin",
            "postal_code",
            "country",
        )
        parts: list[str] = []
        seen: set[str] = set()
        GstVerificationService._collect_address_parts(payload, keys=keys, parts=parts, seen=seen)
        return ", ".join(parts) if parts else None

    @staticmethod
    def _ttl_seconds_from(expires_in: Any) -> int:
        if isinstance(expires_in, (int, float)):
            return max(60, int(expires_in))
        if isinstance(expires_in, str) and expires_in.isdigit():
            return max(60, int(expires_in))
        return 300

    @staticmethod
    def _normalize_phone(phone: str | None) -> str | None:
        digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
        return digits or None

    @staticmethod
    def _serialize_raw(raw: Any) -> str | None:
        if raw in (None, ""):
            return None
        try:
            return json.dumps(raw, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _principal_node(data_obj: dict[str, Any]) -> dict[str, Any]:
        contact = data_obj.get("contact_details") if isinstance(data_obj, dict) else None
        principal = contact.get("principal") if isinstance(contact, dict) else None
        return principal if isinstance(principal, dict) else {}

    @classmethod
    def _clean_str_list(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = cls._clean_str(item)
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @classmethod
    def _extract_business_profile(cls, data_obj: dict[str, Any]) -> dict[str, Any]:
        """Extract the rich business profile fields from the GST advanced response."""
        principal = cls._principal_node(data_obj)
        return {
            "pan_number": cls._clean_str(cls._pick_first(data_obj, ["pan_number", "pan"])),
            "gstin_status": cls._clean_str(cls._pick_first(data_obj, ["gstin_status", "status", "sts"])),
            "constitution_of_business": cls._clean_str(
                cls._pick_first(data_obj, ["constitution_of_business", "ctb"])
            ),
            "taxpayer_type": cls._clean_str(cls._pick_first(data_obj, ["taxpayer_type", "dty"])),
            "date_of_registration": cls._clean_str(cls._pick_first(data_obj, ["date_of_registration", "rgdt"])),
            "center_jurisdiction": cls._clean_str(cls._pick_first(data_obj, ["center_jurisdiction", "ctj"])),
            "state_jurisdiction": cls._clean_str(cls._pick_first(data_obj, ["state_jurisdiction", "stj"])),
            "nature_of_business": cls._clean_str(principal.get("nature_of_business")),
            "nature_of_core_business_activity_description": cls._clean_str(
                cls._pick_first(data_obj, ["nature_of_core_business_activity_description"])
            ),
            "annual_turnover": cls._clean_str(cls._pick_first(data_obj, ["annual_turnover"])),
            "annual_turnover_fy": cls._clean_str(cls._pick_first(data_obj, ["annual_turnover_fy"])),
            "promoters": cls._clean_str_list(data_obj.get("promoters")),
            "nature_bus_activities": cls._clean_str_list(data_obj.get("nature_bus_activities")),
        }

    def _build_cached_response(
        self,
        *,
        gstin: str,
        cached: dict[str, Any],
        fallback_email: str | None,
        fallback_phone: str | None,
        source: str,
    ) -> dict[str, Any]:
        return {
            "transaction_id": str(cached.get("transaction_id") or f"gst_{uuid4().hex}"),
            "data": {
                "gstin": gstin,
                "business_name": str(cached.get("business_name") or cached.get("legal_name") or ""),
                "legal_name": str(cached.get("legal_name") or cached.get("business_name") or ""),
                "contact_details": {
                    "principal": {
                        "email": cached.get("contact_email") or (fallback_email or None),
                        "mobile": cached.get("contact_phone") or self._normalize_phone(fallback_phone),
                        "address": cached.get("address") or None,
                    }
                },
                "business_profile": cached.get("business_profile") or None,
                "verification_source": source,
            },
        }

    @classmethod
    def _extract_email(cls, payload: dict[str, Any]) -> str | None:
        return cls._clean_str(
            cls._pick_first(
                payload,
                [
                    "email",
                    "email_id",
                    "contact_email",
                    "business_email",
                    "trade_email",
                    "principal_email",
                ],
            )
        )

    @classmethod
    def _extract_phone(cls, payload: dict[str, Any]) -> str | None:
        raw = cls._pick_first(
            payload,
            [
                "mobile",
                "mobile_no",
                "phone",
                "phone_number",
                "contact_number",
                "business_phone",
                "principal_mobile",
            ],
        )
        if not isinstance(raw, str):
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        return digits or None

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(tz=timezone.utc)

    def _full_url(self, endpoint_or_url: str) -> str:
        if endpoint_or_url.startswith(("http://", "https://")):
            return endpoint_or_url
        return urljoin(self.settings.deepvue_base_url.rstrip("/") + "/", endpoint_or_url.lstrip("/"))

    def _get_access_token(self) -> str:
        now = self._utc_now()
        if self._cached_token and self._cached_token_expires_at and now < self._cached_token_expires_at:
            return self._cached_token

        client_id = get_secret(self.settings.deepvue_client_id_secret_id)
        client_secret = get_secret(self.settings.deepvue_client_secret_secret_id)
        with httpx.Client(timeout=self.settings.deepvue_timeout_seconds) as client:
            response = client.post(
                self._full_url(self.settings.deepvue_auth_endpoint),
                data={"client_id": client_id, "client_secret": client_secret},
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            logger.error("Deepvue auth failed with status=%s", response.status_code)
            raise ValueError(GST_UNAVAILABLE_MESSAGE)
        payload = response.json() if response.content else {}
        token = self._pick_first(payload, ["access_token", "token", "auth_token"])
        if not isinstance(token, str) or not token.strip():
            raise ValueError(GST_UNAVAILABLE_MESSAGE)
        expires_in = self._pick_first(payload, ["expires_in", "expiry", "expires"])
        ttl_seconds = self._ttl_seconds_from(expires_in)
        self._cached_token = token.strip()
        self._cached_token_expires_at = now.replace(microsecond=0) + timedelta(seconds=ttl_seconds - 30)
        return self._cached_token

    def _deepvue_lookup(self, *, gstin: str) -> dict[str, Any]:
        if not self.settings.deepvue_enabled:
            raise ValueError(GST_UNAVAILABLE_MESSAGE)

        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": get_secret(self.settings.deepvue_client_secret_secret_id),
            "Accept": "application/json",
        }
        with httpx.Client(timeout=self.settings.deepvue_timeout_seconds) as client:
            response = client.get(
                self._full_url(self.settings.deepvue_gstin_verify_endpoint),
                params={"gstin_number": gstin},
                headers=headers,
            )
        if response.status_code >= 400:
            logger.error("Deepvue GST lookup failed status=%s for gstin=%s", response.status_code, gstin)
            raise ValueError(GST_UNAVAILABLE_MESSAGE)

        raw = response.json() if response.content else {}
        return self._parse_deepvue_payload(raw)

    def _parse_deepvue_payload(self, raw: Any) -> dict[str, Any]:
        """Parse the GST advanced response into the internal payload shape."""
        data_obj = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else {}
        # GST advanced returns legal_name/business_name directly; keep lite keys as fallback.
        legal_name = self._clean_str(self._pick_first(data_obj, ["legal_name", "lgnm", "legalName"]))
        business_name = (
            self._clean_str(self._pick_first(data_obj, ["business_name", "tradeNam", "trade_name", "tradeName"]))
            or legal_name
        )
        if not legal_name and not business_name:
            raise ValueError(GST_NOT_FOUND_MESSAGE)
        transaction_id = (
            self._clean_str(self._pick_first(raw, ["transaction_id", "transactionId", "reference_id", "request_id"]))
            or f"gst_{uuid4().hex}"
        )
        principal = self._principal_node(data_obj)
        address = (
            self._clean_str(principal.get("address"))
            or self._stitch_address_parts(data_obj)
            or self._stitch_address_parts(raw)
        )
        email = self._clean_str(principal.get("email")) or self._extract_email(data_obj) or self._extract_email(raw)
        phone = self._normalize_phone(principal.get("mobile")) or self._extract_phone(data_obj) or self._extract_phone(raw)
        return {
            "transaction_id": transaction_id,
            "legal_name": legal_name or business_name or "",
            "business_name": business_name or legal_name or "",
            "address": address,
            "email": (email or "").strip().lower() or None,
            "phone": phone,
            "business_profile": self._extract_business_profile(data_obj),
            "raw": raw,
        }

    def _store_deepvue_result(
        self,
        *,
        normalized_gstin: str,
        payload: dict[str, Any],
        fallback_email: str | None,
        fallback_phone: str | None,
    ) -> dict[str, Any]:
        return self.gst_pool_repo.set(
            normalized_gstin,
            {
                "transaction_id": payload["transaction_id"],
                "legal_name": payload["legal_name"],
                "business_name": payload["business_name"],
                "contact_email": payload.get("email") or (fallback_email or "").strip().lower() or None,
                "contact_phone": payload.get("phone") or self._normalize_phone(fallback_phone),
                "address": payload.get("address"),
                "business_profile": payload.get("business_profile"),
                "verification_source": "deepvue",
                # Firestore rejects nested arrays (e.g. filing_status); store raw as a JSON string.
                "raw": self._serialize_raw(payload.get("raw")),
            },
        )

    def _store_fallback_result(
        self,
        *,
        normalized_gstin: str,
        message: str,
        fallback_email: str | None,
        fallback_phone: str | None,
    ) -> dict[str, Any]:
        normalized_email = (fallback_email or "").strip().lower() or None
        normalized_phone = self._normalize_phone(fallback_phone)
        if not normalized_email and not normalized_phone:
            raise ValueError(message)
        # Resilient fallback: allow onboarding to continue with customer-provided contact details.
        return self.gst_pool_repo.set(
            normalized_gstin,
            {
                "transaction_id": f"gst_{uuid4().hex}",
                "legal_name": f"{FALLBACK_BUSINESS_NAME_PREFIX}{normalized_gstin}",
                "business_name": f"{FALLBACK_BUSINESS_NAME_PREFIX}{normalized_gstin}",
                "contact_email": normalized_email,
                "contact_phone": normalized_phone,
                "address": None,
                "business_profile": None,
                "verification_source": "fallback",
                "raw": {"reason": message},
            },
        )

    def _resolve_uncached_gst(
        self,
        *,
        normalized_gstin: str,
        fallback_email: str | None,
        fallback_phone: str | None,
    ) -> tuple[dict[str, Any], str]:
        try:
            payload = self._deepvue_lookup(gstin=normalized_gstin)
        except ValueError as exc:
            message = str(exc)
            if message == GST_NOT_FOUND_MESSAGE:
                raise
            cached = self._store_fallback_result(
                normalized_gstin=normalized_gstin,
                message=message,
                fallback_email=fallback_email,
                fallback_phone=fallback_phone,
            )
            return cached, "fallback"
        cached = self._store_deepvue_result(
            normalized_gstin=normalized_gstin,
            payload=payload,
            fallback_email=fallback_email,
            fallback_phone=fallback_phone,
        )
        return cached, "deepvue"

    def verify_gst(
        self,
        *,
        gstin: str,
        fallback_email: str | None,
        fallback_phone: str | None,
    ) -> dict[str, Any]:
        normalized_gstin = str(gstin).strip().upper()
        cached = self.gst_pool_repo.get(normalized_gstin)
        if cached is None:
            cached, source = self._resolve_uncached_gst(
                normalized_gstin=normalized_gstin,
                fallback_email=fallback_email,
                fallback_phone=fallback_phone,
            )
        else:
            source = str(cached.get("verification_source") or "cache")
        return self._build_cached_response(
            gstin=normalized_gstin,
            cached=cached,
            fallback_email=fallback_email,
            fallback_phone=fallback_phone,
            source=source,
        )
