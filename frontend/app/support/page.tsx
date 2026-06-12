import { PageShell } from "@/components/page-shell";

export default function SupportPage() {
  return (
    <PageShell
      eyebrow="Support"
      title="Operational support and handoff"
      description="Use this area for tenant onboarding, billing assistance, and backend-supported escalation notes."
      compactHeader
    >
      <section className="cards">
        <article className="card">
          <div className="card-kicker">Tenant onboarding</div>
          <strong>Guided setup notes</strong>
          <p className="card-copy">Capture product, tenure, and module requirements before the backend creates records.</p>
        </article>
        <article className="card">
          <div className="card-kicker">Billing support</div>
          <strong>Reconciliation escalations</strong>
          <p className="card-copy">Review captured payments, failed orders, and webhook replay events.</p>
        </article>
        <article className="card">
          <div className="card-kicker">Audit trail</div>
          <strong>Reviewable operator notes</strong>
          <p className="card-copy">Keep support summaries aligned to immutable backend records.</p>
        </article>
      </section>
    </PageShell>
  );
}