"""Invoice orchestration for Razorpay + Zoho Books with customer email delivery."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs

import httpx

from app.core.secret_manager import get_secret, get_secret_uncached
from app.core.settings import get_settings
from app.services.email_sender import EmailAttachment, SmtpEmailSender
from app.services.payment_gateway import RazorpayGateway

logger = logging.getLogger(__name__)

PDF_MIME_TYPE = "application/pdf"
GST_RATE = 0.18
SAC_CODE = "998315"
DEFAULT_SUPPLIER_STATE_CODE = "27"

GST_STATE_CODE_TO_NAME: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}

PINCODE_PREFIX_TO_STATE_CODE: dict[str, str] = {
    "11": "07",
    "12": "06",
    "13": "06",
    "14": "03",
    "15": "03",
    "16": "04",
    "17": "02",
    "18": "01",
    "19": "01",
    "20": "05",
    "21": "09",
    "22": "09",
    "23": "09",
    "24": "05",
    "25": "05",
    "26": "05",
    "27": "09",
    "28": "09",
    "30": "08",
    "31": "08",
    "32": "08",
    "33": "08",
    "34": "08",
    "36": "24",
    "37": "24",
    "38": "24",
    "39": "24",
    "40": "27",
    "41": "27",
    "42": "27",
    "43": "27",
    "44": "27",
    "45": "27",
    "46": "23",
    "47": "23",
    "48": "22",
    "49": "22",
    "50": "36",
    "51": "36",
    "52": "37",
    "53": "37",
    "56": "29",
    "57": "29",
    "58": "29",
    "59": "29",
    "60": "33",
    "61": "33",
    "62": "33",
    "63": "33",
    "64": "33",
    "67": "32",
    "68": "32",
    "69": "32",
    "70": "19",
    "71": "19",
    "72": "19",
    "73": "19",
    "74": "19",
    "75": "21",
    "76": "21",
    "77": "21",
    "78": "18",
    "79": "18",
    "80": "10",
    "81": "20",
    "82": "10",
    "83": "10",
    "84": "10",
    "85": "10",
    "90": "36",
    "91": "17",
    "92": "17",
    "93": "16",
    "94": "12",
    "95": "13",
    "96": "14",
    "97": "15",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class InvoiceService:
    """Creates invoice records in both providers and emails the customer."""

    def __init__(
        self,
        *,
        gateway: RazorpayGateway,
        email_sender: SmtpEmailSender,
    ) -> None:
        self.gateway = gateway
        self.email_sender = email_sender
        self.settings = get_settings()
        self._cached_access_token: str | None = None

    def _require_enabled(self) -> None:
        if not self.settings.invoicing_enabled:
            raise ValueError("Invoice sync is disabled")
        if not self.settings.zoho_books_enabled:
            raise ValueError("Zoho Books sync is disabled")

    @staticmethod
    def _to_rupees(amount_paise: int) -> float:
        return round(float(amount_paise) / 100.0, 2)

    @staticmethod
    def _round_money(amount: float) -> float:
        return round(amount + 1e-9, 2)

    @staticmethod
    def _normalize_state_code(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if len(normalized) == 1 and normalized.isdigit():
            return f"0{normalized}"
        if len(normalized) == 2 and normalized.isdigit():
            return normalized
        return None

    def _extract_state_code_from_gstin(self, gstin: str | None) -> str | None:
        raw = str(gstin or "").strip().upper()
        if len(raw) < 2:
            return None
        return self._normalize_state_code(raw[:2])

    def _extract_state_code_from_address(self, address: str | None) -> str | None:
        lower = str(address or "").lower()
        if not lower:
            return None
        for code, state_name in GST_STATE_CODE_TO_NAME.items():
            if state_name.lower() in lower:
                return code
        return None

    def _extract_state_code_from_pincode(self, pincode: str | None) -> str | None:
        normalized = "".join(ch for ch in str(pincode or "") if ch.isdigit())
        if len(normalized) != 6:
            return None
        return PINCODE_PREFIX_TO_STATE_CODE.get(normalized[:2])

    def _resolve_tax_breakdown(
        self,
        *,
        amount_paise: int,
        invoice_gstin: str | None,
        invoice_pincode: str | None,
        invoice_address: str | None,
    ) -> dict[str, Any]:
        total_amount = self._to_rupees(amount_paise)
        taxable_amount = self._round_money(total_amount / (1 + GST_RATE))
        total_gst = self._round_money(total_amount - taxable_amount)

        customer_state_code = (
            self._extract_state_code_from_gstin(invoice_gstin)
            or self._extract_state_code_from_pincode(invoice_pincode)
            or self._extract_state_code_from_address(invoice_address)
        )
        supplier_state_code = DEFAULT_SUPPLIER_STATE_CODE
        tax_mode = "igst"
        igst_amount = total_gst
        cgst_amount = 0.0
        sgst_amount = 0.0

        if customer_state_code and customer_state_code == supplier_state_code:
            tax_mode = "cgst_sgst"
            cgst_amount = self._round_money(total_gst / 2)
            sgst_amount = self._round_money(total_gst - cgst_amount)
            igst_amount = 0.0

        return {
            "taxable_amount": taxable_amount,
            "total_gst": total_gst,
            "igst_amount": igst_amount,
            "cgst_amount": cgst_amount,
            "sgst_amount": sgst_amount,
            "tax_mode": tax_mode,
            "customer_state_code": customer_state_code,
            "supplier_state_code": supplier_state_code,
        }

    @staticmethod
    def _strip_payment_prefix(payment_id: str | None) -> str:
        """Remove Razorpay 'pay_' prefix for clean display in invoices and emails."""
        raw = str(payment_id or "").strip()
        if raw.lower().startswith("pay_"):
            return raw[4:]
        return raw

    @staticmethod
    def _split_contact_name(name: str) -> tuple[str, str]:
        chunks = [part for part in str(name or "").strip().split(" ") if part]
        if not chunks:
            return "Customer", ""
        if len(chunks) == 1:
            return chunks[0], ""
        return chunks[0], " ".join(chunks[1:])

    @staticmethod
    def _safe_invoice_filename(invoice_number: str) -> str:
        raw = str(invoice_number or "").strip()
        sanitized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw).strip("-_")
        return f"{sanitized or 'invoice'}.pdf"

    def _create_razorpay_invoice(self, *, subscription: dict[str, Any]) -> str:
        item_name = str(subscription.get("product_snapshot", {}).get("name") or subscription.get("product_id") or "Core subscription")
        payload = {
            "type": "invoice",
            "description": f"Subscription invoice for {item_name}",
            "customer": {
                "name": str(subscription.get("customer_name") or "Customer"),
                "email": str(subscription.get("customer_email") or ""),
                "contact": str(subscription.get("customer_phone") or ""),
            },
            "line_items": [
                {
                    "name": item_name,
                    "description": f"{subscription.get('tenure_months')} month subscription",
                    "amount": int(subscription.get("amount_paise") or 0),
                    "currency": str(subscription.get("currency") or "INR"),
                    "quantity": 1,
                }
            ],
            "currency": str(subscription.get("currency") or "INR"),
            "receipt": str(subscription.get("id") or ""),
            "notes": {
                "subscription_id": str(subscription.get("id") or ""),
                "tenant_id": str(subscription.get("tenant_id") or ""),
                "payment_id": self._strip_payment_prefix(subscription.get("razorpay_payment_id")),
            },
            "email_notify": 0,
            "sms_notify": 0,
        }
        invoice = self.gateway.create_invoice(payload=payload)
        invoice_id = str(invoice.get("id") or "").strip()
        if not invoice_id:
            raise ValueError("Unable to create Razorpay invoice")
        return invoice_id

    def _zoho_headers(self) -> dict[str, str]:
        access_token = self._resolve_zoho_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def _refresh_zoho_access_token(self) -> str | None:
        if not self.settings.zoho_books_auto_refresh_enabled:
            return None

        client_id = get_secret(self.settings.zoho_books_client_id_secret_id).strip()
        client_secret = get_secret(self.settings.zoho_books_client_secret_secret_id).strip()
        refresh_token = get_secret(self.settings.zoho_books_refresh_token_secret_id).strip()
        if not client_id or not client_secret or not refresh_token:
            return None

        with httpx.Client(timeout=self.settings.invoice_http_timeout_seconds) as client:
            token_response = client.post(
                f"{self.settings.zoho_oauth_api_base.rstrip('/')}/oauth/v2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        token_response.raise_for_status()
        payload = token_response.json()
        token = str(payload.get("access_token") or "").strip()
        if token:
            return token

        # Some providers return querystring payload in plain text.
        parsed = parse_qs(str(token_response.text or ""), keep_blank_values=False)
        fallback = str((parsed.get("access_token") or [""])[0]).strip()
        return fallback or None

    def _resolve_zoho_access_token(self) -> str:
        # Use per-invocation cached token first to avoid excessive refresh calls.
        if self._cached_access_token:
            return self._cached_access_token
        # Fall back to stored secret (may be fresh enough).
        return get_secret_uncached(self.settings.zoho_books_access_token_secret_id).strip()

    def _do_refresh_and_cache(self) -> str | None:
        try:
            refreshed = self._refresh_zoho_access_token()
            if refreshed:
                self._cached_access_token = refreshed
                return refreshed
        except Exception:
            logger.exception("Zoho access token refresh failed; using stored token fallback")
        return None

    def _zoho_request(
        self,
        client: httpx.Client,
        *,
        method: str,
        path: str,
        params: dict[str, Any],
        json_body: dict[str, Any] | None = None,
        accept_pdf: bool = False,
    ) -> httpx.Response:
        headers = self._zoho_headers()
        if accept_pdf:
            headers = {**headers, "Accept": PDF_MIME_TYPE}

        response = client.request(
            method=method,
            url=self._zoho_api(path),
            params=params,
            headers=headers,
            json=json_body,
        )
        if response.status_code != 401:
            return response

        self._cached_access_token = None
        refreshed = self._do_refresh_and_cache()
        if not refreshed:
            return response

        retry_headers = {
            "Authorization": f"Zoho-oauthtoken {refreshed}",
            "Content-Type": "application/json",
        }
        if accept_pdf:
            retry_headers["Accept"] = PDF_MIME_TYPE
        return client.request(
            method=method,
            url=self._zoho_api(path),
            params=params,
            headers=retry_headers,
            json=json_body,
        )

    def _zoho_org_id(self) -> str:
        value = get_secret(self.settings.zoho_books_organization_id_secret_id).strip()
        if not value:
            raise ValueError("Zoho Books organization id is missing")
        return value

    def _zoho_api(self, path: str) -> str:
        base = self.settings.zoho_books_api_base.rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def _find_or_create_zoho_contact(
        self,
        *,
        email: str,
        company_name: str,
        contact_person_name: str,
        phone: str | None,
        invoice_address: str | None,
        invoice_gstin: str | None,
    ) -> str:
        org_id = self._zoho_org_id()
        with httpx.Client(timeout=self.settings.invoice_http_timeout_seconds) as client:
            list_response = self._zoho_request(
                client,
                method="GET",
                path="contacts",
                params={"organization_id": org_id, "email_contains": email},
            )
            list_response.raise_for_status()
            payload = list_response.json()
            contacts = payload.get("contacts") or []
            if contacts:
                contact_id = str(contacts[0].get("contact_id") or "").strip()
                if contact_id:
                    return contact_id

            first_name, last_name = self._split_contact_name(contact_person_name)
            create_response = self._zoho_request(
                client,
                method="POST",
                path="contacts",
                params={"organization_id": org_id},
                json_body={
                    "contact_name": company_name,
                    "email": email,
                    "contact_type": "customer",
                    "phone": phone or "",
                    "gst_no": invoice_gstin or "",
                    "gst_treatment": "business_gst" if invoice_gstin else "consumer",
                    "place_of_contact": self._extract_state_code_from_gstin(invoice_gstin) or "",
                    "billing_address": {
                        "attention": contact_person_name,
                        "address": invoice_address or "",
                        "state_code": self._extract_state_code_from_gstin(invoice_gstin) or "",
                    },
                    "contact_persons": [
                        {
                            "first_name": first_name,
                            "last_name": last_name,
                            "email": email,
                            "phone": phone or "",
                            "is_primary_contact": True,
                        }
                    ],
                },
            )
            create_response.raise_for_status()
            created = create_response.json()
            contact = created.get("contact") or {}
            contact_id = str(contact.get("contact_id") or "").strip()
            if not contact_id:
                raise ValueError("Unable to create Zoho Books contact")
            return contact_id

    def _extract_invoice_contact_fields(self, *, subscription: dict[str, Any]) -> dict[str, Any]:
        email = str(subscription.get("customer_email") or "").strip().lower()
        if not email:
            raise ValueError("Customer email is required for invoice")
        contact_person_name = str(subscription.get("customer_name") or "Customer").strip() or "Customer"
        company_name = str(subscription.get("company_name") or "").strip() or contact_person_name
        invoice_address = str(subscription.get("invoice_address") or "").strip() or None
        invoice_gstin = str(subscription.get("invoice_gstin") or "").strip().upper() or None
        invoice_pincode = str(subscription.get("invoice_pincode") or "").strip() or None
        if not invoice_address:
            raise ValueError("Invoice address is required for invoice")
        if not invoice_gstin:
            raise ValueError("Invoice GSTIN is required for invoice")
        if not invoice_pincode:
            raise ValueError("Invoice pincode is required for invoice")
        return {
            "email": email,
            "contact_person_name": contact_person_name,
            "company_name": company_name,
            "phone": str(subscription.get("customer_phone") or "").strip() or None,
            "invoice_address": invoice_address,
            "invoice_gstin": invoice_gstin,
            "invoice_pincode": invoice_pincode,
        }

    def _build_zoho_invoice_payload(
        self,
        *,
        subscription: dict[str, Any],
        contact_id: str,
        company_name: str,
        invoice_address: str | None,
        invoice_gstin: str | None,
        invoice_pincode: str | None,
    ) -> dict[str, Any]:
        item_name = str(subscription.get("product_snapshot", {}).get("name") or subscription.get("product_id") or "Core subscription")
        transaction_id = self._strip_payment_prefix(subscription.get("razorpay_payment_id"))
        now = _now()
        invoice_date = now.strftime("%Y-%m-%d")
        # Make reference unique per invoice attempt to avoid Zoho duplicate rejection.
        ts_suffix = str(int(now.timestamp()))[-6:]
        reference_number = f"{transaction_id}-{ts_suffix}" if transaction_id else f"NA-{ts_suffix}"
        tax = self._resolve_tax_breakdown(
            amount_paise=int(subscription.get("amount_paise") or 0),
            invoice_gstin=invoice_gstin,
            invoice_pincode=invoice_pincode,
            invoice_address=invoice_address,
        )

        line_items: list[dict[str, Any]] = [
            {
                "name": item_name,
                "description": f"{subscription.get('tenure_months')} month subscription (SAC: {SAC_CODE})",
                "rate": tax["taxable_amount"],
                "quantity": 1,
                "hsn_or_sac": SAC_CODE,
            }
        ]
        if tax["tax_mode"] == "igst":
            line_items.append(
                {
                    "name": "IGST (18%)",
                    "description": "Integrated GST on subscription",
                    "rate": tax["igst_amount"],
                    "quantity": 1,
                }
            )
        else:
            line_items.extend(
                [
                    {
                        "name": "CGST (9%)",
                        "description": "Central GST on subscription",
                        "rate": tax["cgst_amount"],
                        "quantity": 1,
                    },
                    {
                        "name": "SGST (9%)",
                        "description": "State GST on subscription",
                        "rate": tax["sgst_amount"],
                        "quantity": 1,
                    },
                ]
            )

        customer_state_code = str(tax.get("customer_state_code") or "NA")
        payload: dict[str, Any] = {
            "customer_id": contact_id,
            "customer_name": company_name,
            "date": invoice_date,
            "reference_number": reference_number,
            "currency_code": str(subscription.get("currency") or "INR"),
            "place_of_supply": tax.get("customer_state_code") or "",
            "line_items": line_items,
            "notes": (
                f"Transaction ID: {transaction_id or 'NA'} | "
                f"Amount is GST inclusive | "
                f"SAC: {SAC_CODE} | "
                f"Tax mode: {'IGST' if tax['tax_mode'] == 'igst' else 'CGST+SGST'} | "
                f"Customer state code: {customer_state_code}"
            ),
        }
        return payload

    def _create_zoho_invoice(self, *, subscription: dict[str, Any]) -> dict[str, str]:
        org_id = self._zoho_org_id()
        fields = self._extract_invoice_contact_fields(subscription=subscription)
        contact_id = self._find_or_create_zoho_contact(
            email=fields["email"],
            company_name=fields["company_name"],
            contact_person_name=fields["contact_person_name"],
            phone=fields["phone"],
            invoice_address=fields["invoice_address"],
            invoice_gstin=fields["invoice_gstin"],
        )
        invoice_payload = self._build_zoho_invoice_payload(
            subscription=subscription,
            contact_id=contact_id,
            company_name=fields["company_name"],
            invoice_address=fields["invoice_address"],
            invoice_gstin=fields["invoice_gstin"],
            invoice_pincode=fields["invoice_pincode"],
        )
        with httpx.Client(timeout=self.settings.invoice_http_timeout_seconds) as client:
            invoice_response = self._zoho_request(
                client,
                method="POST",
                path="invoices",
                params={"organization_id": org_id},
                json_body=invoice_payload,
            )
            if not invoice_response.is_success:
                logger.error(
                    "Zoho invoice creation failed",
                    extra={
                        "status_code": invoice_response.status_code,
                        "zoho_response": invoice_response.text[:500],
                        "subscription_id": subscription.get("id"),
                    },
                )
                invoice_response.raise_for_status()
            created = invoice_response.json()
            invoice = created.get("invoice") or {}
            invoice_id = str(invoice.get("invoice_id") or "").strip()
            if not invoice_id:
                raise ValueError("Unable to create Zoho Books invoice")
            invoice_number = str(invoice.get("invoice_number") or "").strip() or invoice_id
            return {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
            }

    def _download_zoho_invoice_pdf(self, *, zoho_invoice_id: str) -> bytes:
        org_id = self._zoho_org_id()
        timeout = self.settings.invoice_http_timeout_seconds

        with httpx.Client(timeout=timeout) as client:
            # Try canonical PDF response from invoice detail endpoint.
            response = self._zoho_request(
                client,
                method="GET",
                path=f"invoices/{zoho_invoice_id}",
                params={"organization_id": org_id},
                accept_pdf=True,
            )
            if response.status_code < 400 and (
                PDF_MIME_TYPE in response.headers.get("content-type", "").lower()
                or response.content.startswith(b"%PDF")
            ):
                return bytes(response.content)

            # Fallback endpoint used by some Zoho Books deployments.
            response = self._zoho_request(
                client,
                method="GET",
                path=f"invoices/{zoho_invoice_id}/pdf",
                params={"organization_id": org_id},
                accept_pdf=True,
            )
            if response.status_code < 400 and (
                PDF_MIME_TYPE in response.headers.get("content-type", "").lower()
                or response.content.startswith(b"%PDF")
            ):
                return bytes(response.content)

        raise ValueError("Unable to download Zoho Books invoice PDF")

    def _send_invoice_email(
        self,
        *,
        to_email: str,
        contact_person_name: str,
        invoice_address: str | None,
        invoice_gstin: str | None,
        invoice_pincode: str | None,
        transaction_id: str,
        amount_paise: int,
        currency: str,
        razorpay_invoice_id: str | None,
        zoho_invoice_id: str,
        zoho_invoice_number: str,
        zoho_invoice_pdf: bytes,
        tax_breakdown: dict[str, Any],
        subscription: dict[str, Any],
    ) -> None:
        amount_display = f"{amount_paise / 100:,.2f}"
        tax_mode = str(tax_breakdown.get("tax_mode") or "igst")
        company_name = str(subscription.get("company_name") or subscription.get("customer_name") or "Customer")
        safe_company_name = html.escape(company_name)
        safe_contact_name = html.escape(contact_person_name or "Customer")
        safe_transaction_id = html.escape(transaction_id)
        safe_currency = html.escape(currency)
        safe_amount_display = html.escape(amount_display)
        safe_invoice_number = html.escape(zoho_invoice_number)
        safe_support_email = html.escape(self.settings.support_email)
        safe_gstin = html.escape(str(invoice_gstin or "").strip() or "-")
        tax_label = "IGST" if tax_mode == "igst" else "CGST + SGST"
        tax_amount = float(tax_breakdown.get("total_gst") or 0.0)
        taxable = float(tax_breakdown.get("taxable_amount") or 0.0)

        subject = f"Payment confirmed — Invoice {zoho_invoice_number}"
        body_text = (
            f"Hi {contact_person_name},\n\n"
            f"Your payment of {currency} {amount_display} has been received.\n\n"
            f"Company: {company_name}\n"
            f"GSTIN: {invoice_gstin or '-'}\n"
            f"Transaction ID: {transaction_id}\n"
            f"Invoice number: {zoho_invoice_number}\n"
            f"Taxable amount: {currency} {taxable:.2f}\n"
            f"GST ({tax_label}): {currency} {tax_amount:.2f}\n\n"
            "Your invoice is attached to this email.\n\n"
            f"Need help? Contact {self.settings.support_email}\n\n"
            "Thank you for choosing Core."
        )

        body_html = f"""<!doctype html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0"
        style="width:100%;max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 32px rgba(15,23,42,0.10);">
        <tr>
          <td style="background:linear-gradient(135deg,#0f172a,#1d4ed8);padding:28px 32px 24px;">
            <p style="margin:0 0 4px;color:#93c5fd;font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:700;">Core by Tuskus</p>
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;line-height:1.3;">Payment confirmed</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px 8px;">
            <p style="margin:0 0 20px;color:#1e293b;font-size:15px;line-height:1.6;">Hi <strong>{safe_contact_name}</strong>,</p>
            <p style="margin:0 0 24px;color:#334155;font-size:14px;line-height:1.6;">
              Your payment has been received. Your invoice is attached to this email.
            </p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
              style="border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
              <tr style="background:#f8fafc;">
                <td colspan="2" style="padding:12px 16px;border-bottom:1px solid #e2e8f0;">
                  <p style="margin:0;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">Payment summary</p>
                </td>
              </tr>
              <tr>
                <td style="padding:10px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9;">Company</td>
                <td style="padding:10px 16px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;border-bottom:1px solid #f1f5f9;">{safe_company_name}</td>
              </tr>
              <tr>
                <td style="padding:10px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9;">GSTIN</td>
                <td style="padding:10px 16px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;border-bottom:1px solid #f1f5f9;">{safe_gstin}</td>
              </tr>
              <tr>
                <td style="padding:10px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9;">Invoice no.</td>
                <td style="padding:10px 16px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;border-bottom:1px solid #f1f5f9;">{safe_invoice_number}</td>
              </tr>
              <tr>
                <td style="padding:10px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9;">Transaction ID</td>
                <td style="padding:10px 16px;font-size:13px;color:#0f172a;font-weight:600;text-align:right;border-bottom:1px solid #f1f5f9;">{safe_transaction_id}</td>
              </tr>
              <tr>
                <td style="padding:10px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9;">Taxable amount</td>
                <td style="padding:10px 16px;font-size:13px;color:#0f172a;text-align:right;border-bottom:1px solid #f1f5f9;">{safe_currency} {html.escape(f"{taxable:.2f}")}</td>
              </tr>
              <tr>
                <td style="padding:10px 16px;font-size:13px;color:#64748b;border-bottom:1px solid #f1f5f9;">GST ({html.escape(tax_label)})</td>
                <td style="padding:10px 16px;font-size:13px;color:#0f172a;text-align:right;border-bottom:1px solid #f1f5f9;">{safe_currency} {html.escape(f"{tax_amount:.2f}")}</td>
              </tr>
              <tr style="background:#f0f9ff;">
                <td style="padding:12px 16px;font-size:14px;color:#0f172a;font-weight:700;">Total paid</td>
                <td style="padding:12px 16px;font-size:14px;color:#1d4ed8;font-weight:700;text-align:right;">{safe_currency} {safe_amount_display}</td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px 32px;font-size:13px;color:#64748b;line-height:1.6;">
            Questions? Write to us at <a href="mailto:{safe_support_email}" style="color:#1d4ed8;text-decoration:none;font-weight:600;">{safe_support_email}</a>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        attachments: list[EmailAttachment] = [
            {
                "filename": self._safe_invoice_filename(zoho_invoice_number),
                "content": zoho_invoice_pdf,
                "mime_type": "application/pdf",
            }
        ]
        self.email_sender.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
        )
        amount_display = f"{amount_paise / 100:.2f}"
        safe_taxable_amount = html.escape(f"{float(tax_breakdown.get('taxable_amount') or 0.0):.2f}")
        safe_total_gst = html.escape(f"{float(tax_breakdown.get('total_gst') or 0.0):.2f}")
        safe_igst_amount = html.escape(f"{float(tax_breakdown.get('igst_amount') or 0.0):.2f}")
        safe_cgst_amount = html.escape(f"{float(tax_breakdown.get('cgst_amount') or 0.0):.2f}")
        safe_sgst_amount = html.escape(f"{float(tax_breakdown.get('sgst_amount') or 0.0):.2f}")
        tax_mode = str(tax_breakdown.get("tax_mode") or "igst")
        safe_tax_mode = "IGST" if tax_mode == "igst" else "CGST + SGST"
        company_name = str(subscription.get("company_name") or subscription.get("customer_name") or "Customer")
        safe_company_name = html.escape(company_name or "Customer")
        safe_contact_person_name = html.escape(contact_person_name or "Customer")
        customer_phone = str(subscription.get("customer_phone") or "").strip() or None
        safe_customer_phone = html.escape(str(customer_phone or "-").strip() or "-")
        safe_invoice_address = html.escape(str(invoice_address or "-").strip() or "-")
        safe_invoice_pincode = html.escape(str(invoice_pincode or "-").strip() or "-")
        safe_invoice_gstin = html.escape(str(invoice_gstin or "-").strip() or "-")
        safe_transaction_id = html.escape(transaction_id)
        safe_currency = html.escape(currency)
        safe_amount_display = html.escape(amount_display)
        safe_razorpay_invoice_id = html.escape((razorpay_invoice_id or "").strip())
        safe_zoho_invoice_id = html.escape(zoho_invoice_id)
        safe_zoho_invoice_number = html.escape(zoho_invoice_number)
        safe_support_email = html.escape(self.settings.support_email)

        subject = f"Payment confirmed - Invoice {zoho_invoice_number}"
        body_text = (
            f"Hi {contact_person_name},\n\n"
            "Your payment was successful, and your invoice details are ready.\n\n"
            f"Company name: {company_name}\n"
            f"Contact person name: {contact_person_name}\n"
            f"Email: {to_email}\n"
            f"Phone number: {customer_phone or '-'}\n"
            f"Address: {invoice_address or '-'}\n"
            f"Pincode: {invoice_pincode or '-'}\n"
            f"GST: {invoice_gstin or '-'}\n"
            f"Transaction ID: {transaction_id}\n"
            f"Amount (GST inclusive): {currency} {amount_display}\n"
            f"Taxable amount: {currency} {float(tax_breakdown.get('taxable_amount') or 0.0):.2f}\n"
            f"Total GST: {currency} {float(tax_breakdown.get('total_gst') or 0.0):.2f}\n"
            f"Tax mode: {safe_tax_mode}\n"
            f"IGST: {currency} {float(tax_breakdown.get('igst_amount') or 0.0):.2f}\n"
            f"CGST: {currency} {float(tax_breakdown.get('cgst_amount') or 0.0):.2f}\n"
            f"SGST: {currency} {float(tax_breakdown.get('sgst_amount') or 0.0):.2f}\n"
            f"SAC code: {SAC_CODE}\n"
            f"Invoice number: {zoho_invoice_number}\n"
            f"Zoho Books invoice id: {zoho_invoice_id}\n\n"
            f"If you need help, contact {self.settings.support_email}.\n\n"
            "Thank you for choosing Core."
        )
        if razorpay_invoice_id:
            body_text = body_text.replace(
                f"Zoho Books invoice id: {zoho_invoice_id}",
                f"Razorpay invoice id: {razorpay_invoice_id}\nZoho Books invoice id: {zoho_invoice_id}",
            )
        body_html = f"""
<!doctype html>
<html>
    <body style="margin:0;padding:0;background:#eaf0ff;font-family:'Segoe UI',Arial,sans-serif;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:28px 12px;">
            <tr><td align="center">
                <table role="presentation" width="560" cellpadding="0" cellspacing="0"
                    style="width:100%;max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 16px 48px rgba(15,23,42,0.12);">
                    <tr>
                        <td style="background:linear-gradient(135deg,#0f172a,#1d4ed8);padding:28px 32px;">
                            <p style="margin:0;color:#dbeafe;font-size:12px;letter-spacing:0.6px;text-transform:uppercase;font-weight:700;">Core Subscription</p>
                            <h1 style="margin:8px 0 0;color:#ffffff;font-size:24px;line-height:1.3;">Payment confirmed. Invoice details ready.</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:30px 32px 12px;">
                            <p style="margin:0 0 16px;color:#1e293b;font-size:15px;line-height:1.6;">Hi <strong>{safe_contact_person_name}</strong>,</p>
                            <p style="margin:0 0 18px;color:#1e293b;font-size:15px;line-height:1.6;">Thank you for your payment. Your invoice details are now available.</p>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;">
                                <tr>
                                    <td style="padding:18px 20px;color:#334155;font-size:13px;line-height:1.6;">
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Company name:</strong> {safe_company_name}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Contact person name:</strong> {safe_contact_person_name}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Email:</strong> {html.escape(to_email)}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Phone number:</strong> {safe_customer_phone}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Address:</strong> {safe_invoice_address}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Pincode:</strong> {safe_invoice_pincode}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">GST:</strong> {safe_invoice_gstin}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Transaction ID:</strong> {safe_transaction_id}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Amount (GST inclusive):</strong> {safe_currency} {safe_amount_display}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Taxable amount:</strong> {safe_currency} {safe_taxable_amount}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Total GST:</strong> {safe_currency} {safe_total_gst}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Tax mode:</strong> {safe_tax_mode}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">IGST:</strong> {safe_currency} {safe_igst_amount}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">CGST:</strong> {safe_currency} {safe_cgst_amount}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">SGST:</strong> {safe_currency} {safe_sgst_amount}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">SAC code:</strong> {SAC_CODE}</p>
                                        <p style="margin:0 0 8px;"><strong style="color:#0f172a;">Invoice number:</strong> {safe_zoho_invoice_number}</p>
                                        {f'<p style="margin:0 0 8px;"><strong style="color:#0f172a;">Razorpay invoice ID:</strong> {safe_razorpay_invoice_id}</p>' if safe_razorpay_invoice_id else ''}
                                        <p style="margin:0;"><strong style="color:#0f172a;">Zoho Books invoice ID:</strong> {safe_zoho_invoice_id}</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:10px 32px 28px;color:#475569;font-size:12px;line-height:1.6;">
                            Need help? Contact <a href="mailto:{safe_support_email}" style="color:#1e40af;text-decoration:underline;font-weight:700;">{safe_support_email}</a>.
                        </td>
                    </tr>
                </table>
            </td></tr>
        </table>
    </body>
</html>
"""
        attachments: list[EmailAttachment] = [
            {
                "filename": self._safe_invoice_filename(zoho_invoice_number),
                "content": zoho_invoice_pdf,
                "mime_type": "application/pdf",
            }
        ]
        self.email_sender.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
        )

    def create_and_send(self, *, subscription: dict[str, Any]) -> dict[str, Any]:
        """Create invoice records in both systems and email the customer."""
        self._require_enabled()
        to_email = str(subscription.get("customer_email") or "").strip().lower()
        if not to_email:
            raise ValueError("Customer email is required for invoice")

        zoho_invoice = self._create_zoho_invoice(subscription=subscription)
        zoho_invoice_id = zoho_invoice["invoice_id"]
        zoho_invoice_number = zoho_invoice["invoice_number"]
        zoho_invoice_pdf = self._download_zoho_invoice_pdf(zoho_invoice_id=zoho_invoice_id)
        invoice_gstin = str(subscription.get("invoice_gstin") or "").strip().upper() or None
        invoice_address = str(subscription.get("invoice_address") or "").strip() or None
        invoice_pincode = str(subscription.get("invoice_pincode") or "").strip() or None
        tax_breakdown = self._resolve_tax_breakdown(
            amount_paise=int(subscription.get("amount_paise") or 0),
            invoice_gstin=invoice_gstin,
            invoice_pincode=invoice_pincode,
            invoice_address=invoice_address,
        )

        razorpay_invoice_id: str | None
        try:
            razorpay_invoice_id = self._create_razorpay_invoice(subscription=subscription)
        except Exception:
            razorpay_invoice_id = None

        self._send_invoice_email(
            to_email=to_email,
            contact_person_name=str(subscription.get("customer_name") or "Customer"),
            invoice_address=invoice_address,
            invoice_gstin=invoice_gstin,
            invoice_pincode=invoice_pincode,
            transaction_id=self._strip_payment_prefix(subscription.get("razorpay_payment_id")),
            amount_paise=int(subscription.get("amount_paise") or 0),
            currency=str(subscription.get("currency") or "INR"),
            razorpay_invoice_id=razorpay_invoice_id,
            zoho_invoice_id=zoho_invoice_id,
            zoho_invoice_number=zoho_invoice_number,
            zoho_invoice_pdf=zoho_invoice_pdf,
            tax_breakdown=tax_breakdown,
            subscription=subscription,
        )

        sent_at = _now()
        return {
            "razorpay_invoice_id": razorpay_invoice_id or "",
            "zoho_invoice_id": zoho_invoice_id,
            "zoho_invoice_number": zoho_invoice_number,
            "invoice_customer_email": to_email,
            "invoice_email_sent_at": sent_at,
            "invoice_sync_status": "completed",
            "invoice_sync_error": None,
        }
