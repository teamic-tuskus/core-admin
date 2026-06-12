"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { PageShell } from "@/components/page-shell";
import {
  createTenant,
  listTenants,
  updateTenant,
  type TenantCreateInput,
  type TenantItem,
} from "@/lib/api-client";

export default function TenantsPage() {
  const { token, user } = useAuth();
  const [rows, setRows] = useState<TenantItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [companyEmail, setCompanyEmail] = useState("");
  const [contactName, setContactName] = useState("");
  const [phone, setPhone] = useState("");

  const authToken = token || "";

  const loadTenants = async () => {
    setError(null);
    setMessage(null);
    setLoading(true);
    try {
      const data = await listTenants(authToken);
      setRows(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load tenants");
    } finally {
      setLoading(false);
    }
  };

  const createTenantAction = async () => {
    setError(null);
    setMessage(null);
    setSaving(true);
    try {
      const payload: TenantCreateInput = {
        name: name.trim(),
        company_email: companyEmail.trim(),
        contact_name: contactName.trim(),
        phone: phone.trim() || null,
      };
      await createTenant(payload, authToken);
      setMessage("Tenant created. Refreshing list...");
      await loadTenants();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create tenant");
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (tenantId: string, status: string) => {
    setError(null);
    setMessage(null);
    setUpdatingId(tenantId);
    try {
      const updated = await updateTenant(tenantId, { status }, authToken);
      setRows((current) => current.map((item) => (item.id === tenantId ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update tenant status");
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <PageShell
      eyebrow="Tenants"
      title="Tenant management"
      description="Create and manage tenant records for billing, entitlement assignment, and subscription operations."
      compactHeader
    >
      <section className="split">
        <article className="form-card">
          <div className="section-kicker">New tenant</div>
          <h2 className="section-title">Create tenant profile</h2>
          <div className="form-grid">
            {!user || !authToken ? (
              <p className="subtle">
                Sign in from <Link href="/">home</Link> to call tenant admin APIs.
              </p>
            ) : (
              <p className="subtle">Signed in as {user.email || user.uid}</p>
            )}
            <label className="field">
              <span>Company name</span>
              <input placeholder="Blue Peak Logistics" value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="field">
              <span>Company email</span>
              <input placeholder="ops@bluepeak.example" value={companyEmail} onChange={(event) => setCompanyEmail(event.target.value)} />
            </label>
            <label className="field">
              <span>Contact name</span>
              <input placeholder="Asha Kumar" value={contactName} onChange={(event) => setContactName(event.target.value)} />
            </label>
            <label className="field">
              <span>Phone (optional)</span>
              <input placeholder="+91-9999999999" value={phone} onChange={(event) => setPhone(event.target.value)} />
            </label>
            <button className="button" type="button" onClick={createTenantAction} disabled={saving || !authToken}>
              {saving ? "Creating..." : "Create tenant"}
            </button>
            <button className="button secondary" type="button" onClick={loadTenants} disabled={loading || !authToken}>
              {loading ? "Loading..." : "Fetch tenants"}
            </button>
            {error ? <p className="subtle status-error">{error}</p> : null}
            {message ? <p className="subtle status-success">{message}</p> : null}
          </div>
        </article>

        <article className="note-card">
          <div className="section-kicker">Governance</div>
          <strong>Tenant status controls access lifecycle.</strong>
          <p className="note-copy">
            Use status transitions to control operational readiness, while backend authorization remains the source of truth.
          </p>
        </article>
      </section>

      <section className="table-card">
        <div className="section-kicker">Live tenants</div>
        <h2 className="section-title">Tenant directory</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Email</th>
              <th>Contact</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty-state">No records loaded yet.</td>
              </tr>
            ) : (
              rows.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td>{item.company_email}</td>
                  <td>{item.contact_name}</td>
                  <td>
                    <span className={item.status === "active" ? "badge" : "badge pending"}>{item.status}</span>
                  </td>
                  <td>
                    <div className="row">
                      <button
                        className="button ghost"
                        type="button"
                        onClick={() => setStatus(item.id, "active")}
                        disabled={!authToken || updatingId === item.id}
                      >
                        Activate
                      </button>
                      <button
                        className="button ghost"
                        type="button"
                        onClick={() => setStatus(item.id, "suspended")}
                        disabled={!authToken || updatingId === item.id}
                      >
                        Suspend
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>
    </PageShell>
  );
}