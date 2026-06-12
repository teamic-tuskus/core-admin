"use client";

import { useState } from "react";

import { PageShell } from "@/components/page-shell";
import {
  confirmCheckout,
  createCheckoutIntent,
  type CheckoutIntentResult,
  type CheckoutSubscription,
} from "@/lib/api-client";

function formatCurrency(currency: string, amountPaise: number) {
  const amount = amountPaise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function maskIdentifier(value: string): string {
  if (!value) {
    return "-";
  }
  if (value.length <= 10) {
    return value;
  }
  return `${value.slice(0, 4)}…${value.slice(-4)}`;
}

export default function CheckoutPage() {
  const [tenantId, setTenantId] = useState("");
  const [productId, setProductId] = useState("");
  const [tenureMonths, setTenureMonths] = useState("12");
  const [requestedUsers, setRequestedUsers] = useState("");
  const [couponCode, setCouponCode] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState("");

  const [intentLoading, setIntentLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [intent, setIntent] = useState<CheckoutIntentResult | null>(null);
  const [confirmed, setConfirmed] = useState<CheckoutSubscription | null>(null);
  const [paymentId, setPaymentId] = useState("");
  const [signature, setSignature] = useState("");

  const createIntent = async () => {
    setError(null);
    setMessage(null);
    setConfirmed(null);
    setIntentLoading(true);
    try {
      const tenure = Number(tenureMonths);
      const users = requestedUsers.trim() ? Number(requestedUsers) : null;
      if (!Number.isInteger(tenure) || tenure <= 0) {
        throw new Error("Tenure must be a positive whole number");
      }
      if (users !== null && (!Number.isInteger(users) || users <= 0)) {
        throw new Error("Requested users must be a positive whole number");
      }

      const result = await createCheckoutIntent({
        tenant_id: tenantId.trim(),
        product_id: productId.trim(),
        tenure_months: tenure,
        requested_users: users,
        coupon_code: couponCode.trim() || null,
        customer_name: customerName.trim(),
        customer_email: customerEmail.trim(),
        idempotency_key: idempotencyKey.trim(),
      });
      setIntent(result);
      setMessage("Checkout intent created. Proceed with payment confirmation.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create checkout intent");
    } finally {
      setIntentLoading(false);
    }
  };

  const confirmPayment = async () => {
    if (!intent) {
      return;
    }
    setError(null);
    setMessage(null);
    setConfirmLoading(true);
    try {
      const activated = await confirmCheckout({
        subscription_id: intent.subscription_id,
        razorpay_order_id: intent.razorpay_order_id,
        razorpay_payment_id: paymentId.trim(),
        razorpay_signature: signature.trim(),
      });
      setConfirmed(activated);
      setMessage("Subscription confirmed and activated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to confirm checkout");
    } finally {
      setConfirmLoading(false);
    }
  };

  return (
    <PageShell
      eyebrow="Checkout"
      title="Confirm payment and reconcile subscription state"
      description="Create checkout intents from backend pricing contracts and confirm payment signatures to activate subscriptions."
      compactHeader
    >
      <section className="split">
        <article className="form-card">
          <div className="section-kicker">Intent payload</div>
          <h2 className="section-title">Create checkout intent</h2>
          <div className="form-grid">
            <label className="field">
              <span>Tenant id</span>
              <input placeholder="ten_..." value={tenantId} onChange={(event) => setTenantId(event.target.value)} />
            </label>
            <label className="field">
              <span>Product id</span>
              <input placeholder="prd_..." value={productId} onChange={(event) => setProductId(event.target.value)} />
            </label>
            <div className="row">
              <label className="field">
                <span>Tenure months</span>
                <input value={tenureMonths} onChange={(event) => setTenureMonths(event.target.value)} />
              </label>
              <label className="field">
                <span>Requested users</span>
                <input
                  placeholder="Optional"
                  value={requestedUsers}
                  onChange={(event) => setRequestedUsers(event.target.value)}
                />
              </label>
            </div>
            <label className="field">
              <span>Coupon code</span>
              <input
                placeholder="EXCLUSIVE-2026"
                value={couponCode}
                onChange={(event) => setCouponCode(event.target.value)}
              />
            </label>
            <div className="row">
              <label className="field">
                <span>Customer name</span>
                <input value={customerName} onChange={(event) => setCustomerName(event.target.value)} />
              </label>
              <label className="field">
                <span>Customer email</span>
                <input value={customerEmail} onChange={(event) => setCustomerEmail(event.target.value)} />
              </label>
            </div>
            <label className="field">
              <span>Idempotency key</span>
              <input value={idempotencyKey} onChange={(event) => setIdempotencyKey(event.target.value)} />
            </label>
            <button
              className="button secondary"
              type="button"
              onClick={() => setIdempotencyKey(`idem-${Date.now()}`)}
            >
              Generate idempotency key
            </button>
            <button className="button" type="button" onClick={createIntent} disabled={intentLoading}>
              {intentLoading ? "Creating intent..." : "Create intent"}
            </button>
          </div>
        </article>

        <article className="note-card">
          <div className="section-kicker">Intent result</div>
          {intent ? (
            <>
              <strong>Order ready for payment gateway checkout.</strong>
              <p className="note-copy">Subscription reference: {maskIdentifier(intent.subscription_id)}</p>
              <p className="note-copy">Order reference: {maskIdentifier(intent.razorpay_order_id)}</p>
              <p className="note-copy">Amount: {formatCurrency(intent.currency, intent.amount_paise)}</p>
              <p className="note-copy">Entitlement modules: {intent.entitlement_modules.join(", ") || "-"}</p>
              <p className="note-copy">Max users: {intent.entitlement_max_users}</p>
              <p className="note-copy">Tenure months: {intent.entitlement_tenure_months}</p>
              <p className="note-copy">Coupon: {intent.applied_coupon_code || "none"}</p>
            </>
          ) : (
            <>
              <strong>All pricing and entitlement logic runs in backend APIs.</strong>
              <p className="note-copy">
                The portal only sends input and renders API responses. Monetary and entitlement calculation remains server-authoritative.
              </p>
            </>
          )}
          {error ? <p className="subtle status-error">{error}</p> : null}
          {message ? <p className="subtle status-success">{message}</p> : null}
        </article>
      </section>

      <section className="split">
        <article className="form-card">
          <div className="section-kicker">Payment callback</div>
          <h2 className="section-title">Confirm checkout signature</h2>
          <div className="form-grid">
            <label className="field">
              <span>Razorpay payment id</span>
              <input
                placeholder="pay_..."
                value={paymentId}
                onChange={(event) => setPaymentId(event.target.value)}
                disabled={!intent}
              />
            </label>
            <label className="field">
              <span>Razorpay signature</span>
              <input
                placeholder="sig_..."
                value={signature}
                onChange={(event) => setSignature(event.target.value)}
                disabled={!intent}
              />
            </label>
            <button className="button" type="button" onClick={confirmPayment} disabled={!intent || confirmLoading}>
              {confirmLoading ? "Confirming..." : "Confirm checkout"}
            </button>
          </div>
        </article>

        <article className="note-card">
          <div className="section-kicker">Activation result</div>
          {confirmed ? (
            <>
              <strong>Subscription is now {confirmed.status}.</strong>
              <p className="note-copy">Subscription reference: {maskIdentifier(confirmed.id)}</p>
              <p className="note-copy">Tenant reference: {maskIdentifier(confirmed.tenant_id)}</p>
              <p className="note-copy">Product reference: {maskIdentifier(confirmed.product_id)}</p>
              <p className="note-copy">Window: {confirmed.start_at || "-"} to {confirmed.end_at || "-"}</p>
              <p className="note-copy">Modules: {confirmed.modules.join(", ") || "-"}</p>
            </>
          ) : (
            <>
              <strong>Awaiting payment confirmation.</strong>
              <p className="note-copy">
                Once payment id and signature are submitted, backend validates signature and activates the subscription.
              </p>
            </>
          )}
        </article>
      </section>
    </PageShell>
  );
}