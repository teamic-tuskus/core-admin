"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { PageShell } from "@/components/page-shell";
import {
  listSubscriptions,
  reconcileSubscription,
  type AdminSubscription,
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

function formatContractSummary(item: AdminSubscription): string {
  const productName = item.product_snapshot?.name || item.product_snapshot?.code || "Snapshot unavailable";
  const users = item.max_users;
  const tenure = item.tenure_months;
  const version = item.version || 1;
  return `${productName} · ${users} users · ${tenure} mo · v${version}`;
}

function formatCouponSummary(item: AdminSubscription): string {
  if (!item.coupon_snapshot) {
    return item.coupon_code || "No coupon";
  }

  const coupon = item.coupon_snapshot.code;
  let discount = "Coupon applied";
  if (item.coupon_snapshot.discount_percent) {
    discount = `${item.coupon_snapshot.discount_percent}% off`;
  } else if (item.coupon_snapshot.discount_amount_paise) {
    discount = `₹${(item.coupon_snapshot.discount_amount_paise / 100).toLocaleString("en-IN")} off`;
  }
  return `${coupon} · ${discount}`;
}

export default function BillingPage() {
  const { token, user } = useAuth();
  const [rows, setRows] = useState<AdminSubscription[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const authToken = token || "";

  const pendingCount = useMemo(
    () => rows.filter((item) => item.status !== "active").length,
    [rows],
  );

  const load = async () => {
    setError(null);
    setLoading(true);
    try {
      const data = await listSubscriptions(authToken);
      setRows(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load subscriptions");
    } finally {
      setLoading(false);
    }
  };

  const reconcile = async (id: string) => {
    setError(null);
    setBusyId(id);
    try {
      const updated = await reconcileSubscription(id, authToken);
      setRows((current) => current.map((item) => (item.id === id ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reconciliation failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageShell
      eyebrow="Billing"
      title="Subscription and payment operations"
      description="Review intent creation, confirmed payments, active subscriptions, and manual reconciliation notes from a single operational view."
      compactHeader
    >
      <section className="cards">
        <article className="card">
          <div className="card-kicker">Payment intents</div>
          <strong>Pending orders awaiting confirmation</strong>
          <p className="card-copy">Pending reconciliations right now: {pendingCount}</p>
        </article>
        <article className="card">
          <div className="card-kicker">Captured payments</div>
          <strong>Webhook-verified activations</strong>
          <p className="card-copy">Use webhook-driven state changes to keep subscriptions synchronized with payments.</p>
        </article>
        <article className="card">
          <div className="card-kicker">Coupons</div>
          <strong>Redemption visibility</strong>
          <p className="card-copy">Track exclusive coupons and redemption counts after successful activation only.</p>
        </article>
      </section>

      <section className="split">
        <article className="form-card">
          <div className="section-kicker">Authorized access</div>
          <h2 className="section-title">Load subscription operations</h2>
          <div className="form-grid">
              {!user || !authToken ? (
                <p className="subtle">
                  Sign in from <Link href="/">home</Link> before loading billing operations.
                </p>
              ) : (
                <p className="subtle">Signed in as {user.email || user.uid}</p>
              )}
              <button className="button" type="button" onClick={load} disabled={loading || !authToken}>
              {loading ? "Loading subscriptions..." : "Fetch subscriptions"}
            </button>
            {error ? <p className="subtle status-error">{error}</p> : null}
          </div>
        </article>

        <article className="note-card">
          <div className="section-kicker">Reconciliation mode</div>
          <strong>Manual retry is backend-validated.</strong>
          <p className="note-copy">
            Every reconcile action calls the server endpoint, which consults payment gateway state and updates subscription status.
          </p>
        </article>
      </section>

      <section className="table-card">
        <div className="section-kicker">Live subscriptions</div>
        <h2 className="section-title">State and gateway alignment</h2>
        <section className="table-shell" aria-label="Live subscriptions table">
        <table className="table billing-table">
          <thead>
            <tr>
              <th>Tenant</th>
              <th>Contract</th>
              <th>Coupon</th>
              <th>Status</th>
              <th>Gateway</th>
              <th>Amount</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-state">No records loaded yet.</td>
              </tr>
            ) : (
              rows.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div>{maskIdentifier(item.tenant_id)}</div>
                    <div className="subtle">Tenant record masked</div>
                  </td>
                  <td>
                    <div>{formatContractSummary(item)}</div>
                    <div className="subtle">{item.product_snapshot?.modules?.join(", ") || "Contract snapshot unavailable"}</div>
                    <div className="subtle">{item.is_current === false ? "Historical version" : "Current version"}{item.change_reason ? ` · ${item.change_reason.replaceAll("_", " ")}` : ""}</div>
                  </td>
                  <td>
                    <div>{formatCouponSummary(item)}</div>
                    <div className="subtle">{item.coupon_snapshot?.exclusive_for_tenant_id ? `Tenant lock: ${maskIdentifier(item.coupon_snapshot.exclusive_for_tenant_id)}` : "No tenant lock"}</div>
                  </td>
                  <td>
                    <span className={item.status === "active" ? "badge" : "badge pending"}>{item.status}</span>
                  </td>
                  <td>{item.gateway_status || "unknown"}</td>
                  <td>{formatCurrency(item.currency, item.amount_paise)}</td>
                  <td>
                    <button
                      className="button"
                      type="button"
                      onClick={() => reconcile(item.id)}
                        disabled={!authToken || busyId === item.id}
                    >
                      {busyId === item.id ? "Reconciling..." : "Reconcile"}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        </section>
      </section>
    </PageShell>
  );
}