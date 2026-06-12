"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { PageShell } from "@/components/page-shell";
import {
  acceptPortalAccessInvitation,
  cancelPortalAccessInvitation,
  getSuperAdminState,
  getMyPortalAccessInvitation,
  getPortalAccessState,
  inviteSuperAdmin,
  invitePortalAccessWithScope,
  rejectPortalAccessInvitation,
  resendPortalAccessInvitation,
  type SuperAdminState,
  updatePortalOperatorAccess,
  type PortalAccessInvitation,
  type PortalAccessState,
  type PortalOperator,
} from "@/lib/api-client";

type AccessTemplate = "admin" | "manager" | "remove_access";
type AccessScope = "product" | "coupon" | "advance_coupon" | "both" | "all";
type AccessModule = "product" | "coupon" | "advance_coupon";
type Draft = { template: AccessTemplate; scope: AccessScope };
type InviteRole = "admin" | "manager";

const SUGGESTED_MAX_DISCOUNT_PERCENT = 30;

function lower(value: unknown): string {
  return typeof value === "string" ? value.toLowerCase() : "";
}

function decodeTokenClaims(token: string | null): Record<string, unknown> {
  if (!token) return {};
  try {
    const payload = token.split(".")[1];
    if (!payload) return {};
    const normalized = payload.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function hasAdminAccess(claims: Record<string, unknown>): boolean {
  const role = lower(claims.role);
  const roles = Array.isArray(claims.roles)
    ? claims.roles.map((item) => String(item).toLowerCase())
    : [];
  return role === "admin" || role === "super_admin" || roles.includes("admin") || roles.includes("super_admin");
}

function isSuperAdmin(claims: Record<string, unknown>): boolean {
  const role = lower(claims.role);
  const roles = Array.isArray(claims.roles)
    ? claims.roles.map((item) => String(item).toLowerCase())
    : [];
  return role === "super_admin" || roles.includes("super_admin");
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? "-" : new Date(timestamp).toLocaleString();
}

function formatOperatorScope(operator: PortalOperator): string {
  const hasProducts = operator.permissions.includes("products");
  const hasCoupons = operator.permissions.includes("coupons");
  const hasAdvanceCoupons = operator.permissions.includes("advance_coupons");
  if (hasProducts && hasCoupons && hasAdvanceCoupons) return "Products + Coupons + Advance Coupons";
  if (hasProducts && hasCoupons) return "Products + Coupons";
  if (hasAdvanceCoupons && hasCoupons) return "Advance Coupons";
  if (hasAdvanceCoupons) return "Advance Coupons";
  if (hasProducts) return "Products";
  if (hasCoupons) return "Coupons";
  return "No scope";
}

function formatInvitationScope(invitation: PortalAccessInvitation): string {
  if (invitation.role === "super_admin") return "Super admin";
  if (invitation.access_scope === "all") return "Products + Coupons + Advance Coupons";
  if (invitation.access_scope === "both") return "Products + Coupons";
  if (invitation.access_scope === "advance_coupon") return "Advance Coupons";
  if (invitation.access_scope === "product") return "Products";
  if (invitation.access_scope === "coupon") return "Coupons";
  return "No scope";
}

function deriveScope(hasProducts: boolean, hasCoupons: boolean, hasAdvanceCoupons = false): AccessScope {
  if (hasProducts && hasAdvanceCoupons) return "all";
  if (hasAdvanceCoupons && !hasProducts) return "advance_coupon";
  if (hasProducts && hasCoupons) return "both";
  if (hasProducts) return "product";
  if (hasCoupons) return "coupon";
  return "both";
}

function scopeToModules(scope: AccessScope): AccessModule[] {
  if (scope === "all") return ["product", "coupon", "advance_coupon"];
  if (scope === "both") return ["product", "coupon"];
  if (scope === "advance_coupon") return ["coupon", "advance_coupon"];
  if (scope === "product") return ["product"];
  return ["coupon"];
}

function normalizeInviteModules(modules: AccessModule[]): AccessModule[] {
  const set = new Set<AccessModule>(modules);
  if (set.has("advance_coupon")) {
    set.add("coupon");
  }
  return (["product", "coupon", "advance_coupon"] as const).filter((module) => set.has(module));
}

function modulesToScope(modules: AccessModule[]): AccessScope {
  const normalized = normalizeInviteModules(modules);
  const hasProducts = normalized.includes("product");
  const hasCoupons = normalized.includes("coupon");
  const hasAdvanceCoupons = normalized.includes("advance_coupon");

  if (hasProducts && hasAdvanceCoupons) return "all";
  if (hasAdvanceCoupons) return "advance_coupon";
  if (hasProducts && hasCoupons) return "both";
  if (hasProducts) return "product";
  if (hasCoupons) return "coupon";
  throw new Error("Select at least one module.");
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M20 4v6h-6" />
    </svg>
  );
}

function AddIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </svg>
  );
}

function draftFromOperator(operator: PortalOperator): Draft {
  const hasProducts = operator.permissions.includes("products");
  const hasCoupons = operator.permissions.includes("coupons");
  const hasAdvanceCoupons = operator.permissions.includes("advance_coupons");
  const scope = deriveScope(hasProducts, hasCoupons, hasAdvanceCoupons);
  return { template: operator.role === "manager" ? "manager" : "admin", scope };
}

type WithTokenAction = (fn: (activeToken: string) => Promise<void>, okMessage: string) => void;

function InviteAccessCard(props: Readonly<{
  adminAccess: boolean;
  inviteEmail: string;
  inviteName: string;
  inviteDesignation: string;
  inviteAgentNumber: string;
  invitePhoneNumber: string;
  inviteRole: InviteRole;
  inviteModules: AccessModule[];
  normalCouponMaxDiscountPercent: string;
  busy: boolean;
  setInviteEmail: (value: string) => void;
  setInviteName: (value: string) => void;
  setInviteDesignation: (value: string) => void;
  setInviteAgentNumber: (value: string) => void;
  setInvitePhoneNumber: (value: string) => void;
  setInviteRole: (value: InviteRole) => void;
  setInviteModules: (value: AccessModule[]) => void;
  setNormalCouponMaxDiscountPercent: (value: string) => void;
  onInvite: () => void;
}>) {
  return (
    <article className="form-card users-panel-card">
      <h2 className="section-title">Invite user</h2>
      {props.adminAccess ? (
        <div className="form-grid">
          <input
            className="input"
            placeholder="operator@company.com"
            value={props.inviteEmail}
            onChange={(event) => props.setInviteEmail(event.target.value)}
          />
          <div className="row">
            <input
              className="input"
              placeholder="Full name"
              value={props.inviteName}
              onChange={(event) => props.setInviteName(event.target.value)}
            />
            <input
              className="input"
              placeholder="Designation"
              value={props.inviteDesignation}
              onChange={(event) => props.setInviteDesignation(event.target.value)}
            />
          </div>
          <input
            className="input"
            placeholder="Agent number (e.g. AG-1021)"
            value={props.inviteAgentNumber}
            onChange={(event) => props.setInviteAgentNumber(event.target.value.toUpperCase())}
          />
          <input
            className="input"
            placeholder="Phone number (e.g. +919999999999)"
            value={props.invitePhoneNumber}
            onChange={(event) => props.setInvitePhoneNumber(event.target.value)}
          />
          <div className="row">
            <select
              className="input"
              value={props.inviteRole}
              onChange={(event) => props.setInviteRole(event.target.value as InviteRole)}
            >
              <option value="admin">Admin</option>
              <option value="manager">Manager</option>
            </select>
            <fieldset className="form-grid" style={{ border: "none", padding: 0, margin: 0 }}>
              <legend className="subtle" style={{ marginBottom: "0.25rem" }}>Module access</legend>
              <label className="subtle" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={props.inviteModules.includes("product")}
                  onChange={(event) => {
                    const next: AccessModule[] = event.target.checked
                      ? [...props.inviteModules, "product"]
                      : props.inviteModules.filter((module) => module !== "product");
                    props.setInviteModules(normalizeInviteModules(next));
                  }}
                />
                <span>Product</span>
              </label>
              <label className="subtle" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={props.inviteModules.includes("coupon")}
                  onChange={(event) => {
                    if (!event.target.checked && props.inviteModules.includes("advance_coupon")) {
                      return;
                    }
                    const next: AccessModule[] = event.target.checked
                      ? [...props.inviteModules, "coupon"]
                      : props.inviteModules.filter((module) => module !== "coupon");
                    props.setInviteModules(normalizeInviteModules(next));
                  }}
                />
                <span>Coupons</span>
              </label>
              <label className="subtle" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={props.inviteModules.includes("advance_coupon")}
                  onChange={(event) => {
                    const next: AccessModule[] = event.target.checked
                      ? [...props.inviteModules, "advance_coupon"]
                      : props.inviteModules.filter((module) => module !== "advance_coupon");
                    props.setInviteModules(normalizeInviteModules(next));
                  }}
                />
                <span>Advance Coupons</span>
              </label>
            </fieldset>
          </div>
          <label className="field">
            <span>Coupon max discount (suggested {SUGGESTED_MAX_DISCOUNT_PERCENT}%)</span>
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              placeholder={String(SUGGESTED_MAX_DISCOUNT_PERCENT)}
              value={props.normalCouponMaxDiscountPercent}
              onChange={(event) => props.setNormalCouponMaxDiscountPercent(event.target.value)}
            />
          </label>
          <button className="button" type="button" disabled={props.busy} onClick={props.onInvite}>
            {props.busy ? "Sending..." : "Send access invite"}
          </button>
        </div>
      ) : (
        <p className="subtle">Admin access required.</p>
      )}
    </article>
  );
}

function MyInvitationCard(props: Readonly<{
  myInvite: PortalAccessInvitation | null;
  busy: boolean;
  withToken: WithTokenAction;
}>) {
  return (
    <article className="form-card users-panel-card">
      <h2 className="section-title">Invitation response</h2>
      {props.myInvite ? (
        <div className="form-grid">
          <p className="subtle">Status: {props.myInvite.status}</p>
          <p className="subtle">Expires: {formatDate(props.myInvite.expires_at)}</p>
          <div className="product-editor-actions">
            <button
              className="button"
              type="button"
              disabled={props.busy}
              onClick={() => props.withToken(async (activeToken) => {
                await acceptPortalAccessInvitation(props.myInvite!.id, activeToken);
              }, "Portal access activated.")}
            >
              Accept
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={props.busy}
              onClick={() => props.withToken(async (activeToken) => {
                await rejectPortalAccessInvitation(props.myInvite!.id, activeToken);
              }, "Portal access invitation rejected.")}
            >
              Reject
            </button>
          </div>
        </div>
      ) : (
        <p className="subtle">No pending invitation for your account.</p>
      )}
    </article>
  );
}

function SuperAdminCard(props: Readonly<{
  adminAccess: boolean;
  superAdminAccess: boolean;
  superAdminState: SuperAdminState | null;
  inviteEmail: string;
  busy: boolean;
  setInviteEmail: (value: string) => void;
  onInvite: () => void;
}>) {
  if (!props.adminAccess || !props.superAdminAccess) return null;

  const current = props.superAdminState?.current_super_admin;
  const pending = props.superAdminState?.pending_invitation;

  return (
    <section className="table-card users-glow-card">
      <h2 className="section-title">Super admin transfer</h2>
      <p className="subtle">Current: {current ? `${current.email}` : "Not assigned"}</p>
      <p className="subtle">Pending: {pending ? `${pending.invitee_email} (${pending.status})` : "None"}</p>
      <div className="form-grid">
        <input
          className="input"
          placeholder="new-super-admin@company.com"
          value={props.inviteEmail}
          onChange={(event) => props.setInviteEmail(event.target.value)}
        />
        <p className="subtle">Invite a new super admin. They must accept the invitation to complete transfer.</p>
        <button className="button" type="button" disabled={props.busy} onClick={props.onInvite}>
          {props.busy ? "Sending..." : "Send super admin invite"}
        </button>
      </div>
    </section>
  );
}

function OperatorEditorCard(props: Readonly<{
  selectedOperator: PortalOperator | null;
  selectedDraft: Draft | null;
  busy: boolean;
  setDrafts: React.Dispatch<React.SetStateAction<Record<string, Draft>>>;
  withToken: WithTokenAction;
}>) {
  if (!props.selectedOperator || !props.selectedDraft) {
    return (
      <aside className="operator-editor-card">
        <p className="subtle">Select an operator to edit access.</p>
      </aside>
    );
  }

  const operator = props.selectedOperator;
  const draft = props.selectedDraft;

  return (
    <aside className="operator-editor-card">
      <div className="form-grid">
        <p className="subtle">Editing: {operator.email}</p>
        {operator.role === "super_admin" ? (
          <p className="subtle">This account is super admin. Use the Super Admin transfer section.</p>
        ) : null}
        <select
          className="input"
          value={draft.template}
          onChange={(event) => {
            props.setDrafts((current) => ({
              ...current,
              [operator.uid]: {
                ...draft,
                template: event.target.value as AccessTemplate,
              },
            }));
          }}
          disabled={operator.role === "super_admin"}
        >
          <option value="admin">Admin</option>
          <option value="manager">Manager</option>
          <option value="remove_access">Remove access</option>
        </select>
        <select
          className="input"
          value={draft.scope}
          onChange={(event) => {
            props.setDrafts((current) => ({
              ...current,
              [operator.uid]: {
                ...draft,
                scope: event.target.value as AccessScope,
              },
            }));
          }}
          disabled={draft.template === "remove_access" || operator.role === "super_admin"}
        >
          <option value="all">Products + Coupons + Advance Coupons</option>
          <option value="advance_coupon">Advance Coupons</option>
          <option value="both">Products + Coupons</option>
          <option value="product">Products</option>
          <option value="coupon">Coupons</option>
        </select>
        <button
          className="button"
          type="button"
          disabled={props.busy || operator.role === "super_admin"}
          onClick={() => {
            props.withToken(async (activeToken) => {
              if (draft.template === "remove_access") {
                await updatePortalOperatorAccess(operator.uid, "remove_access", activeToken, null);
                return;
              }
              await updatePortalOperatorAccess(
                operator.uid,
                draft.template === "manager" ? "set_manager" : "set_admin",
                activeToken,
                draft.scope,
              );
            }, "Operator access updated.");
          }}
        >
          Apply access change
        </button>
      </div>
    </aside>
  );
}

function OperatorsCard(props: Readonly<{
  adminAccess: boolean;
  operators: PortalOperator[];
  selectedUid: string | null;
  onEditAccess: (uid: string) => void;
  selectedOperator: PortalOperator | null;
  selectedDraft: Draft | null;
  busy: boolean;
  setDrafts: React.Dispatch<React.SetStateAction<Record<string, Draft>>>;
  withToken: WithTokenAction;
}>) {
  if (!props.adminAccess) return null;

  return (
    <section className="table-card users-glow-card">
      <h2 className="section-title">Operators</h2>
      <div className="table-toolbar">
        <span className="count-pill">{props.operators.length} managed operator{props.operators.length === 1 ? "" : "s"}</span>
      </div>
      <div className="table-shell users-table-shell">
        <table className="table users-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>User</th>
              <th>Role</th>
              <th>Scope</th>
              <th>Permissions</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {props.operators.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty-state">No operators found.</td>
              </tr>
            ) : (
              props.operators.map((operator) => (
                <tr
                  key={operator.uid}
                  className={`users-summary-row ${operator.uid === props.selectedUid ? "users-summary-row-active" : ""}`.trim()}
                >
                  <td>{operator.agent_number || "-"}</td>
                  <td>{operator.email}</td>
                  <td>
                    <span className="users-chip users-chip-accent">{operator.role}</span>
                  </td>
                  <td>{formatOperatorScope(operator)}</td>
                  <td>{operator.permissions.length}</td>
                  <td>
                    <button className="button secondary" type="button" onClick={() => props.onEditAccess(operator.uid)}>
                      Edit access
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InvitationHistoryCard(props: Readonly<{
  adminAccess: boolean;
  portalState: PortalAccessState | null;
  busy: boolean;
  withToken: WithTokenAction;
}>) {
  if (!props.adminAccess || !props.portalState) return null;

  return (
    <section className="table-card users-glow-card">
      <h2 className="section-title">Invitations</h2>
      <div className="table-shell users-table-shell">
        <table className="table users-table">
          <thead>
            <tr>
              <th>Invitee</th>
              <th>Status</th>
              <th>Role</th>
              <th>Scope</th>
              <th>Invited</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {props.portalState.invitations.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty-state">No invitations found.</td>
              </tr>
            ) : (
              props.portalState.invitations.map((invitation) => (
                <tr key={invitation.id} className="users-summary-row">
                  <td>{invitation.invitee_email}</td>
                  <td>
                    <span className="users-chip users-chip-accent">{invitation.status}</span>
                  </td>
                  <td>{invitation.role}</td>
                  <td>{formatInvitationScope(invitation)}</td>
                  <td>{formatDate(invitation.invited_at)}</td>
                  <td>
                    {invitation.status === "pending" ? (
                      <div className="product-editor-actions users-table-actions">
                        <button
                          className="button secondary"
                          type="button"
                          disabled={props.busy}
                          onClick={() => props.withToken(async (activeToken) => {
                            const result = await resendPortalAccessInvitation(invitation.id, activeToken);
                            if (result.delivery_status !== "sent") {
                              throw new Error("Invitation was updated, but resend email delivery failed. Please verify SMTP and try again.");
                            }
                          }, "Portal invitation resent.")}
                        >
                          Resend
                        </button>
                        <button
                          className="button secondary"
                          type="button"
                          disabled={props.busy}
                          onClick={() => props.withToken(async (activeToken) => {
                            await cancelPortalAccessInvitation(invitation.id, activeToken);
                          }, "Portal invitation cancelled.")}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <span className="subtle">No actions</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UsersPageContent() {
  const { token, refreshToken, user } = useAuth();
  const searchParams = useSearchParams();

  const claims = useMemo(() => decodeTokenClaims(token), [token]);
  const adminAccess = useMemo(() => hasAdminAccess(claims), [claims]);
  const superAdminAccess = useMemo(() => isSuperAdmin(claims), [claims]);

  const [portalState, setPortalState] = useState<PortalAccessState | null>(null);
  const [superAdminState, setSuperAdminState] = useState<SuperAdminState | null>(null);
  const [myInvite, setMyInvite] = useState<PortalAccessInvitation | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteDesignation, setInviteDesignation] = useState("");
  const [inviteAgentNumber, setInviteAgentNumber] = useState("");
  const [invitePhoneNumber, setInvitePhoneNumber] = useState("");
  const [superAdminInviteEmail, setSuperAdminInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<InviteRole>("admin");
  const [inviteModules, setInviteModules] = useState<AccessModule[]>(scopeToModules("both"));
  const [normalCouponMaxDiscountPercent, setNormalCouponMaxDiscountPercent] = useState(String(SUGGESTED_MAX_DISCOUNT_PERCENT));

  const [selectedUid, setSelectedUid] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"invite" | "edit">("invite");

  const currentEmail = (user?.email || "").trim().toLowerCase();
  const currentUid = user?.uid || "";

  const reload = useCallback(async () => {
    if (!token) return;
    if (adminAccess) {
      const [state, superState, mine] = await Promise.all([
        getPortalAccessState(token),
        getSuperAdminState(token),
        getMyPortalAccessInvitation(token),
      ]);
      setPortalState(state);
      setSuperAdminState(superState);
      setMyInvite(mine);
      return;
    }
    const mine = await getMyPortalAccessInvitation(token);
    setPortalState(null);
    setSuperAdminState(null);
    setMyInvite(mine);
  }, [token, adminAccess]);

  useEffect(() => {
    let active = true;
    if (!token) return;
    const run = async () => {
      try {
        await reload();
      } catch (e: unknown) {
        if (!active) return;
        setError(e instanceof Error ? e.message : "Failed to load users access data.");
      }
    };
    void run();
    return () => {
      active = false;
    };
  }, [token, reload]);

  const operators = useMemo(() => {
    return (portalState?.operators || []).filter((operator) => {
      return !(operator.uid === currentUid || operator.email.toLowerCase() === currentEmail);
    });
  }, [portalState, currentUid, currentEmail]);

  const resolvedSelectedUid = useMemo(() => {
    if (!operators.length) return null;
    if (selectedUid && operators.some((operator) => operator.uid === selectedUid)) {
      return selectedUid;
    }
    return operators[0].uid;
  }, [operators, selectedUid]);

  const selectedOperator = operators.find((operator) => operator.uid === resolvedSelectedUid) || null;
  const selectedDraft = selectedOperator ? drafts[selectedOperator.uid] || draftFromOperator(selectedOperator) : null;

  const runAction = async (fn: () => Promise<void>, okMessage: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      await refreshToken();
      await reload();
      setNotice(okMessage);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  };

  const withToken: WithTokenAction = (fn, okMessage) => {
    if (!token) {
      setError("Sign in required.");
      return;
    }
    void runAction(() => fn(token), okMessage);
  };

  const onInvite = () => {
    withToken(async (activeToken) => {
      if (!inviteEmail.trim()) {
        throw new Error("Enter an email to send onboarding access invitation.");
      }
      if (!inviteName.trim()) {
        throw new Error("Enter user name.");
      }
      if (!inviteDesignation.trim()) {
        throw new Error("Enter user designation.");
      }
      if (!inviteAgentNumber.trim()) {
        throw new Error("Enter agent number.");
      }
      if (!invitePhoneNumber.trim()) {
        throw new Error("Enter phone number.");
      }
      const limit = Number(normalCouponMaxDiscountPercent);
      if (!Number.isFinite(limit) || limit < 1 || limit > 100) {
        throw new Error("Coupon max discount must be between 1 and 100.");
      }
      const accessScope = modulesToScope(inviteModules);
      const result = await invitePortalAccessWithScope(
        {
          invitee_email: inviteEmail.trim(),
          invitee_name: inviteName.trim(),
          invitee_designation: inviteDesignation.trim(),
          invitee_agent_number: inviteAgentNumber.trim().toUpperCase(),
          invitee_phone: invitePhoneNumber.trim(),
          role: inviteRole,
          access_scope: accessScope,
          normal_coupon_max_discount_percent: normalCouponMaxDiscountPercent.trim()
            ? Number(normalCouponMaxDiscountPercent)
            : null,
        },
        activeToken,
      );
      if (result.delivery_status !== "sent") {
        throw new Error(
          `Invitation created (ID: ${result.invitation.id}), but initial email delivery failed. Please verify SMTP and use Resend.`,
        );
      }
      setInviteEmail("");
      setInviteName("");
      setInviteDesignation("");
      setInviteAgentNumber("");
      setInvitePhoneNumber("");
      setInviteModules(scopeToModules("both"));
    }, "Portal access invitation sent.");
  };

  const onInviteSuperAdmin = () => {
    withToken(async (activeToken) => {
      if (!superAdminInviteEmail.trim()) {
        throw new Error("Enter an email to invite as super admin.");
      }
      const result = await inviteSuperAdmin(superAdminInviteEmail.trim(), activeToken);
      if (result.delivery_status !== "sent") {
        throw new Error(
          `Super admin invitation created (ID: ${result.invitation.id}), but email delivery failed. Please verify SMTP settings.`,
        );
      }
      setSuperAdminInviteEmail("");
    }, "Super admin invitation sent.");
  };

  const refreshUsersView = () => {
    if (!token) {
      setError("Sign in required.");
      return;
    }
    void runAction(async () => {
      await reload();
    }, "Users refreshed.");
  };

  const openInviteForm = () => {
    setFormMode("invite");
    setIsFormOpen(true);
  };

  const openEditForm = (uid: string) => {
    setSelectedUid(uid);
    setFormMode("edit");
    setIsFormOpen(true);
  };

  return (
    <PageShell
      eyebrow="Users"
      title="User access"
      description="Manage access and invitations."
      compactHeader
      headerActions={
        <div className="product-hero-actions">
          <button
            className="button secondary product-hero-button"
            type="button"
            onClick={refreshUsersView}
            disabled={busy || !token}
            aria-label={busy ? "Refreshing users" : "Refresh users"}
            title={busy ? "Refreshing users" : "Refresh users"}
          >
            <RefreshIcon />
          </button>
          <button className="button product-hero-button" type="button" onClick={openInviteForm} disabled={!adminAccess || busy}>
            <AddIcon />
            <span>Add</span>
          </button>
        </div>
      }
    >
      {notice ? <p className="subtle status-success">{notice}</p> : null}
      {error ? <p className="subtle status-error">{error}</p> : null}

      <MyInvitationCard myInvite={myInvite} busy={busy} withToken={withToken} />

      {searchParams.get("portalToken") ? (
        <section className="table-card users-glow-card">
          <a
            className="button"
            href={`/invite?portalToken=${encodeURIComponent(searchParams.get("portalToken") || "")}`}
          >
            Open invite link
          </a>
        </section>
      ) : null}

      <OperatorsCard
        adminAccess={adminAccess}
        operators={operators}
        selectedUid={resolvedSelectedUid}
        onEditAccess={openEditForm}
        selectedOperator={selectedOperator}
        selectedDraft={selectedDraft}
        busy={busy}
        setDrafts={setDrafts}
        withToken={withToken}
      />

      <InvitationHistoryCard
        adminAccess={adminAccess}
        portalState={portalState}
        busy={busy}
        withToken={withToken}
      />

      {isFormOpen ? (
        <dialog open className="product-editor-overlay" aria-label="Users editor">
          <button type="button" aria-label="Close users editor" className="product-editor-backdrop" onClick={() => setIsFormOpen(false)} />
          <aside className="product-editor-panel">
            <div className="product-editor-header">
              <div>
                <h2 className="section-title">{formMode === "edit" ? "Edit access" : "Access setup"}</h2>
              </div>
              <button className="button secondary" type="button" onClick={() => setIsFormOpen(false)}>
                Close
              </button>
            </div>

            <div className="form-grid product-editor-form">
              {formMode === "edit" ? (
                <OperatorEditorCard
                  selectedOperator={selectedOperator}
                  selectedDraft={selectedDraft}
                  busy={busy}
                  setDrafts={setDrafts}
                  withToken={withToken}
                />
              ) : (
                <InviteAccessCard
                  adminAccess={adminAccess}
                  inviteEmail={inviteEmail}
                  inviteName={inviteName}
                  inviteDesignation={inviteDesignation}
                  inviteAgentNumber={inviteAgentNumber}
                  invitePhoneNumber={invitePhoneNumber}
                  inviteRole={inviteRole}
                  inviteModules={inviteModules}
                  normalCouponMaxDiscountPercent={normalCouponMaxDiscountPercent}
                  busy={busy}
                  setInviteEmail={setInviteEmail}
                  setInviteName={setInviteName}
                  setInviteDesignation={setInviteDesignation}
                  setInviteAgentNumber={setInviteAgentNumber}
                  setInvitePhoneNumber={setInvitePhoneNumber}
                  setInviteRole={setInviteRole}
                  setInviteModules={setInviteModules}
                  setNormalCouponMaxDiscountPercent={setNormalCouponMaxDiscountPercent}
                  onInvite={onInvite}
                />
              )}
            </div>
          </aside>
        </dialog>
      ) : null}

      <SuperAdminCard
        adminAccess={adminAccess}
        superAdminAccess={superAdminAccess}
        superAdminState={superAdminState}
        inviteEmail={superAdminInviteEmail}
        busy={busy}
        setInviteEmail={setSuperAdminInviteEmail}
        onInvite={onInviteSuperAdmin}
      />
    </PageShell>
  );
}

export default function UsersPage() {
  return (
    <Suspense
      fallback={(
        <PageShell
          eyebrow="Users"
          title="Access onboarding"
          description="Loading users onboarding..."
          compactHeader
        >
          <p className="subtle">Loading...</p>
        </PageShell>
      )}
    >
      <UsersPageContent />
    </Suspense>
  );
}
