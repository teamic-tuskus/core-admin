"""Tests for invoice_service.py changes:
- DEFAULT_SUPPLIER_STATE_CODE = "27" (Maharashtra)
- _strip_payment_prefix removes "pay_" prefix
- _resolve_tax_breakdown: same-state (MH) -> CGST+SGST, different state -> IGST
- _build_zoho_invoice_payload: place_of_supply populated
- _find_or_create_zoho_contact: gst_treatment and place_of_contact set
- _send_invoice_email: clean simplified HTML with invoice PDF attached
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

import os
os.environ.setdefault("COREADMIN_GCP_PROJECT_ID", "test-project")
os.environ.setdefault("COREADMIN_STORAGE_BACKEND", "memory")

from app.services.invoice_service import InvoiceService, DEFAULT_SUPPLIER_STATE_CODE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> InvoiceService:
    gateway = MagicMock()
    email_sender = MagicMock()
    settings = MagicMock()
    settings.invoicing_enabled = True
    settings.zoho_books_enabled = True
    settings.zoho_books_api_base = "https://www.zohoapis.in/books/v3"
    settings.zoho_oauth_api_base = "https://accounts.zoho.in"
    settings.zoho_books_auto_refresh_enabled = False
    settings.invoice_http_timeout_seconds = 20
    settings.zoho_books_organization_id_secret_id = "zoho-org-id"
    settings.zoho_books_access_token_secret_id = "zoho-access-token"
    settings.zoho_books_refresh_token_secret_id = "zoho-refresh-token"
    settings.zoho_books_client_id_secret_id = "zoho-client-id"
    settings.zoho_books_client_secret_secret_id = "zoho-client-secret"
    settings.support_email = "support@tuskus.com"
    settings.invoice_email_subject_prefix = "Core Invoice"

    svc = InvoiceService.__new__(InvoiceService)
    svc.gateway = gateway
    svc.email_sender = email_sender
    svc.settings = settings
    svc._cached_access_token = None
    return svc


def _make_subscription(
    *,
    gstin: str = "27AAJCC4178R1ZT",
    pincode: str = "400001",
    address: str = "Mumbai, Maharashtra",
    payment_id: str = "pay_TestABC123",
    amount_paise: int = 118000,
) -> dict:
    return {
        "id": "sub_001",
        "tenant_id": "tenant_001",
        "customer_name": "Rajesh Patel",
        "company_name": "Patel Constructions",
        "customer_email": "rajesh@patel.com",
        "customer_phone": "9876543210",
        "invoice_gstin": gstin,
        "invoice_address": address,
        "invoice_pincode": pincode,
        "razorpay_payment_id": payment_id,
        "amount_paise": amount_paise,
        "currency": "INR",
        "tenure_months": 1,
        "product_id": "core-starter",
        "product_snapshot": {"name": "Core Starter"},
    }


# ---------------------------------------------------------------------------
# 1. Supplier state code is Maharashtra (27)
# ---------------------------------------------------------------------------

def test_default_supplier_state_code_is_maharashtra():
    assert DEFAULT_SUPPLIER_STATE_CODE == "27", (
        f"Supplier state code must be 27 (Maharashtra), got {DEFAULT_SUPPLIER_STATE_CODE!r}"
    )


# ---------------------------------------------------------------------------
# 2. _strip_payment_prefix
# ---------------------------------------------------------------------------

class TestStripPaymentPrefix:
    def setup_method(self):
        self.svc = _make_service()

    def test_removes_pay_prefix(self):
        assert self.svc._strip_payment_prefix("pay_ABC123XYZ") == "ABC123XYZ"

    def test_case_insensitive_removal(self):
        assert self.svc._strip_payment_prefix("PAY_ABC") == "ABC"

    def test_no_prefix_unchanged(self):
        assert self.svc._strip_payment_prefix("ABC123") == "ABC123"

    def test_none_returns_empty_string(self):
        assert self.svc._strip_payment_prefix(None) == ""

    def test_empty_returns_empty_string(self):
        assert self.svc._strip_payment_prefix("") == ""

    def test_only_prefix_returns_empty(self):
        assert self.svc._strip_payment_prefix("pay_") == ""


# ---------------------------------------------------------------------------
# 3. _resolve_tax_breakdown: Maharashtra customer -> CGST+SGST
# ---------------------------------------------------------------------------

class TestTaxBreakdown:
    def setup_method(self):
        self.svc = _make_service()

    def test_maharashtra_customer_produces_cgst_sgst(self):
        # GSTIN starting with "27" = Maharashtra
        tax = self.svc._resolve_tax_breakdown(
            amount_paise=118000,
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            invoice_address="Mumbai, Maharashtra",
        )
        assert tax["tax_mode"] == "cgst_sgst", "Same state (MH) must use CGST+SGST"
        assert tax["igst_amount"] == 0.0
        assert tax["cgst_amount"] > 0
        assert tax["sgst_amount"] > 0
        assert abs(tax["cgst_amount"] - tax["sgst_amount"]) <= 0.01

    def test_different_state_produces_igst(self):
        # GSTIN starting with "29" = Karnataka
        tax = self.svc._resolve_tax_breakdown(
            amount_paise=118000,
            invoice_gstin="29AAJCC4178R1ZT",
            invoice_pincode="560001",
            invoice_address="Bengaluru, Karnataka",
        )
        assert tax["tax_mode"] == "igst", "Different state must use IGST"
        assert tax["igst_amount"] > 0
        assert tax["cgst_amount"] == 0.0
        assert tax["sgst_amount"] == 0.0

    def test_delhi_gstin_produces_igst(self):
        # GSTIN starting with "07" = Delhi
        tax = self.svc._resolve_tax_breakdown(
            amount_paise=118000,
            invoice_gstin="07AAJCC4178R1ZT",
            invoice_pincode="110001",
            invoice_address="New Delhi",
        )
        assert tax["tax_mode"] == "igst"

    def test_gst_is_18_percent(self):
        # ₹1180 total = ₹1000 taxable + ₹180 GST (18%)
        tax = self.svc._resolve_tax_breakdown(
            amount_paise=118000,
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            invoice_address="Mumbai",
        )
        assert abs(tax["taxable_amount"] - 1000.0) < 0.5
        assert abs(tax["total_gst"] - 180.0) < 0.5

    def test_supplier_state_code_is_27(self):
        tax = self.svc._resolve_tax_breakdown(
            amount_paise=118000,
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            invoice_address="Mumbai",
        )
        assert tax["supplier_state_code"] == "27"


# ---------------------------------------------------------------------------
# 4. _build_zoho_invoice_payload: place_of_supply and stripped transaction id
# ---------------------------------------------------------------------------

class TestBuildZohoInvoicePayload:
    def setup_method(self):
        self.svc = _make_service()

    def test_place_of_supply_set_from_gstin(self):
        sub = _make_subscription(gstin="27AAJCC4178R1ZT", payment_id="pay_XYZ")
        payload = self.svc._build_zoho_invoice_payload(
            subscription=sub,
            contact_id="cid_001",
            company_name="Patel Constructions",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
        )
        assert payload["place_of_supply"] == "27"

    def test_reference_number_has_no_pay_prefix(self):
        sub = _make_subscription(payment_id="pay_ABC123")
        payload = self.svc._build_zoho_invoice_payload(
            subscription=sub,
            contact_id="cid_001",
            company_name="Patel Constructions",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
        )
        # reference_number = stripped_id + timestamp suffix
        ref = payload["reference_number"]
        assert not ref.startswith("pay_"), f"reference_number must not start with pay_: {ref!r}"
        assert "ABC123" in ref

    def test_maharashtra_invoice_has_cgst_sgst_line_items(self):
        sub = _make_subscription(gstin="27AAJCC4178R1ZT")
        payload = self.svc._build_zoho_invoice_payload(
            subscription=sub,
            contact_id="cid_001",
            company_name="Patel Constructions",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
        )
        item_names = [li["name"] for li in payload["line_items"]]
        assert any("CGST" in n for n in item_names), f"Expected CGST line item, got: {item_names}"
        assert any("SGST" in n for n in item_names), f"Expected SGST line item, got: {item_names}"
        assert not any("IGST" in n for n in item_names), f"Should not have IGST for MH->MH"

    def test_karnataka_invoice_has_igst_line_item(self):
        sub = _make_subscription(gstin="29AAJCC4178R1ZT", pincode="560001", address="Bangalore")
        payload = self.svc._build_zoho_invoice_payload(
            subscription=sub,
            contact_id="cid_001",
            company_name="Test Corp",
            invoice_address="Bangalore",
            invoice_gstin="29AAJCC4178R1ZT",
            invoice_pincode="560001",
        )
        item_names = [li["name"] for li in payload["line_items"]]
        assert any("IGST" in n for n in item_names), f"Expected IGST line item, got: {item_names}"
        assert not any("CGST" in n for n in item_names)


# ---------------------------------------------------------------------------
# 5. _send_invoice_email: clean email, PDF attached, stripped transaction id
# ---------------------------------------------------------------------------

class TestSendInvoiceEmail:
    def setup_method(self):
        self.svc = _make_service()

    def _build_tax(self, tax_mode="cgst_sgst"):
        if tax_mode == "cgst_sgst":
            return {
                "tax_mode": "cgst_sgst",
                "taxable_amount": 1000.0,
                "total_gst": 180.0,
                "igst_amount": 0.0,
                "cgst_amount": 90.0,
                "sgst_amount": 90.0,
                "customer_state_code": "27",
                "supplier_state_code": "27",
            }
        return {
            "tax_mode": "igst",
            "taxable_amount": 1000.0,
            "total_gst": 180.0,
            "igst_amount": 180.0,
            "cgst_amount": 0.0,
            "sgst_amount": 0.0,
            "customer_state_code": "29",
            "supplier_state_code": "27",
        }

    def test_pdf_is_attached(self):
        sub = _make_subscription()
        self.svc._send_invoice_email(
            to_email="rajesh@patel.com",
            contact_person_name="Rajesh Patel",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            transaction_id="ABC123",
            amount_paise=118000,
            currency="INR",
            razorpay_invoice_id=None,
            zoho_invoice_id="zoho_inv_001",
            zoho_invoice_number="INV-001",
            zoho_invoice_pdf=b"%PDF-1.4 fake-pdf",
            tax_breakdown=self._build_tax(),
            subscription=sub,
        )
        call_kwargs = self.svc.email_sender.send_email.call_args.kwargs
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["mime_type"] == "application/pdf"
        assert attachments[0]["content"] == b"%PDF-1.4 fake-pdf"
        assert "INV-001" in attachments[0]["filename"]

    def test_subject_contains_invoice_number(self):
        sub = _make_subscription()
        self.svc._send_invoice_email(
            to_email="rajesh@patel.com",
            contact_person_name="Rajesh Patel",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            transaction_id="ABC123",
            amount_paise=118000,
            currency="INR",
            razorpay_invoice_id=None,
            zoho_invoice_id="zoho_inv_001",
            zoho_invoice_number="INV-2026-001",
            zoho_invoice_pdf=b"%PDF",
            tax_breakdown=self._build_tax(),
            subscription=sub,
        )
        call_kwargs = self.svc.email_sender.send_email.call_args.kwargs
        assert "INV-2026-001" in call_kwargs["subject"]

    def test_transaction_id_has_no_pay_prefix_in_email(self):
        """The caller should pass already-stripped ID; verify it appears correctly."""
        sub = _make_subscription(payment_id="pay_XYZ789")
        # Simulate what create_and_send does: strip before passing
        stripped = self.svc._strip_payment_prefix(sub["razorpay_payment_id"])
        self.svc._send_invoice_email(
            to_email="rajesh@patel.com",
            contact_person_name="Rajesh Patel",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            transaction_id=stripped,
            amount_paise=118000,
            currency="INR",
            razorpay_invoice_id=None,
            zoho_invoice_id="zoho_inv_001",
            zoho_invoice_number="INV-001",
            zoho_invoice_pdf=b"%PDF",
            tax_breakdown=self._build_tax(),
            subscription=sub,
        )
        call_kwargs = self.svc.email_sender.send_email.call_args.kwargs
        html_body = call_kwargs["body_html"]
        text_body = call_kwargs["body_text"]
        assert "XYZ789" in html_body
        assert "pay_XYZ789" not in html_body
        assert "pay_XYZ789" not in text_body

    def test_email_shows_cgst_sgst_label_for_same_state(self):
        sub = _make_subscription()
        self.svc._send_invoice_email(
            to_email="rajesh@patel.com",
            contact_person_name="Rajesh Patel",
            invoice_address="Mumbai",
            invoice_gstin="27AAJCC4178R1ZT",
            invoice_pincode="400001",
            transaction_id="ABC123",
            amount_paise=118000,
            currency="INR",
            razorpay_invoice_id=None,
            zoho_invoice_id="z001",
            zoho_invoice_number="INV-001",
            zoho_invoice_pdf=b"%PDF",
            tax_breakdown=self._build_tax("cgst_sgst"),
            subscription=sub,
        )
        html_body = self.svc.email_sender.send_email.call_args.kwargs["body_html"]
        assert "CGST + SGST" in html_body

    def test_email_shows_igst_label_for_different_state(self):
        sub = _make_subscription(gstin="29AAJCC4178R1ZT", pincode="560001", address="Bangalore")
        self.svc._send_invoice_email(
            to_email="test@corp.com",
            contact_person_name="Arun Kumar",
            invoice_address="Bangalore",
            invoice_gstin="29AAJCC4178R1ZT",
            invoice_pincode="560001",
            transaction_id="KA123",
            amount_paise=118000,
            currency="INR",
            razorpay_invoice_id=None,
            zoho_invoice_id="z002",
            zoho_invoice_number="INV-002",
            zoho_invoice_pdf=b"%PDF",
            tax_breakdown=self._build_tax("igst"),
            subscription=sub,
        )
        html_body = self.svc.email_sender.send_email.call_args.kwargs["body_html"]
        assert "IGST" in html_body


# ---------------------------------------------------------------------------
# 6. Zoho contact creation: gst_treatment and place_of_contact
# ---------------------------------------------------------------------------

class TestZohoContactFields:
    def setup_method(self):
        self.svc = _make_service()

    def test_contact_creation_payload_has_gst_treatment_and_place(self):
        """Verify the JSON body sent to Zoho includes gst_treatment and place_of_contact."""
        captured_body = {}

        import httpx

        def fake_request(client, *, method, path, params, json_body=None, accept_pdf=False):
            if method == "GET" and path == "contacts":
                # simulate: no existing contact found
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {"contacts": []}
                resp.raise_for_status = MagicMock()
                return resp
            if method == "POST" and path == "contacts":
                captured_body.update(json_body or {})
                resp = MagicMock()
                resp.status_code = 200
                resp.raise_for_status = MagicMock()
                resp.json.return_value = {"contact": {"contact_id": "cid_mocked"}}
                return resp
            raise AssertionError(f"Unexpected request: {method} {path}")

        with patch.object(self.svc, "_zoho_request", side_effect=fake_request), \
             patch.object(self.svc, "_zoho_org_id", return_value="org_123"), \
             patch("app.services.invoice_service.get_secret", return_value="fake-token"):
            contact_id = self.svc._find_or_create_zoho_contact(
                email="rajesh@patel.com",
                company_name="Patel Constructions",
                contact_person_name="Rajesh Patel",
                phone="9876543210",
                invoice_address="Mumbai, Maharashtra",
                invoice_gstin="27AAJCC4178R1ZT",
            )

        assert contact_id == "cid_mocked"
        assert captured_body.get("gst_treatment") == "business_gst"
        assert captured_body.get("place_of_contact") == "27"
        billing = captured_body.get("billing_address", {})
        assert billing.get("state_code") == "27"
        assert captured_body.get("gst_no") == "27AAJCC4178R1ZT"
