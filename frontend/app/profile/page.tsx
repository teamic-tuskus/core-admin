"use client";

import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { PageShell } from "@/components/page-shell";

export default function ProfilePage() {
  const { user, token, loading, signOutUser } = useAuth();

  const claims = (() => {
    if (!token) return {} as Record<string, unknown>;
    try {
      const payload = token.split(".")[1];
      if (!payload) return {};
      const normalized = payload.replaceAll("-", "+").replaceAll("_", "/");
      const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
      return JSON.parse(atob(padded)) as Record<string, unknown>;
    } catch {
      return {};
    }
  })();

  const agentNumber = typeof claims.agent_number === "string" ? claims.agent_number : "-";
  const fullName = typeof claims.full_name === "string" ? claims.full_name : (user?.displayName || "-");
  const designation = typeof claims.designation === "string" ? claims.designation : "-";

  return (
    <PageShell
      eyebrow="Profile"
      title="Operator profile"
      description="Review your current session identity and sign out when done."
      compactHeader
    >
      <section className="split">
        <article className="form-card">
          <div className="section-kicker">Session</div>
          <h2 className="section-title">Authenticated operator</h2>
          <div className="form-grid">
            {!user || !token ? (
              <p className="subtle">
                No active session. Sign in at <Link href="/">home</Link>.
              </p>
            ) : (
              <>
                <p className="subtle">Agent Number: {agentNumber}</p>
                <p className="subtle">Name: {fullName}</p>
                <p className="subtle">Designation: {designation}</p>
                <p className="subtle">Email: {user.email || "Not available"}</p>
                <p className="subtle status-success">Session token is active.</p>
              </>
            )}
            <button className="button secondary" type="button" disabled={loading || !user} onClick={signOutUser}>
              Sign out
            </button>
          </div>
        </article>

        <article className="note-card">
          <div className="section-kicker">Security</div>
          <strong>Use least privilege access.</strong>
          <p className="note-copy">
            Keep operator access scoped to authorized admins only, and sign out from shared devices after completing product or coupon operations.
          </p>
        </article>
      </section>
    </PageShell>
  );
}
