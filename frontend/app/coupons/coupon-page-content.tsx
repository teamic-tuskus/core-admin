"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { PageShell } from "@/components/page-shell";
import { decodeTokenClaims, hasAdvanceCouponModuleAccess, hasCouponModuleAccess } from "@/lib/access";
import { isAdvanceCoupon } from "@/lib/coupon-mode";
import {
  createCoupon,
  deleteCoupon,
  listCoupons,
  listProducts,
  pauseCoupon,
  type CouponCreateInput,
  type CouponItem,
  type ProductItem,
} from "@/lib/api-client";

type CouponMode = "normal" | "advance";

function formatDiscountSummary(item: CouponItem): string {
  const parts: string[] = [];
  if (item.discount_percent) {
    parts.push(`${item.discount_percent}% off`);
  }
  if (item.discount_amount_paise) {
    parts.push(`INR ${(item.discount_amount_paise / 100).toLocaleString("en-IN")}`);
  }
  return parts.join(" + ") || "No discount";
}

function formatWindowSummary(validFrom: string | null, validUntil: string | null): string {
  if (!validFrom && !validUntil) {
    return "No limit";
  }

  const formatDate = (value: string) => new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date(value));

  if (validFrom && validUntil) {
    return `${formatDate(validFrom)} to ${formatDate(validUntil)}`;
  }

  if (validFrom) {
    return `From ${formatDate(validFrom)}`;
  }
  return `Until ${formatDate(validUntil as string)}`;
}

function formatOverrideSummary(item: CouponItem): string {
  const parts: string[] = [];
  if (item.override_tenure_months) {
    parts.push(`${item.override_tenure_months} mo`);
  }
  if (item.override_max_users) {
    parts.push(`${item.override_max_users} users`);
  }
  if (item.override_modules?.length) {
    parts.push(item.override_modules.join(", "));
  }
  return parts.join(" · ") || "No overrides";
}

function generateCouponCode(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const length = 10 + Math.floor(Math.random() * 7);
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes)
    .map((b) => chars[b % chars.length])
    .join("");
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

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

export function CouponPageContent({ mode }: Readonly<{ mode: CouponMode }>) {
  const { token, user } = useAuth();
  const [rows, setRows] = useState<CouponItem[]>([]);
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [expandedCouponId, setExpandedCouponId] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null);
  const [actioningCouponId, setActioningCouponId] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const [productId, setProductId] = useState("");
  const [discountPercent, setDiscountPercent] = useState("");
  const [discountAmountRupees, setDiscountAmountRupees] = useState("");
  const [exclusiveTenantId, setExclusiveTenantId] = useState("");
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [overrideTenureMonths, setOverrideTenureMonths] = useState("");
  const [overrideMaxUsers, setOverrideMaxUsers] = useState("");
  const [overrideModules, setOverrideModules] = useState<string[]>([]);

  const MODULE_OPTIONS = [
    { label: "Execution", values: ["execution", "dpr"] },
    { label: "accounts", values: ["accounts", "expense"] },
    { label: "HR", values: ["attendance", "hr"] },
    { label: "Store", values: ["store"] },
    { label: "Survey", values: ["survey"] },
  ] as const;

  function toggleModuleGroup(values: readonly string[]) {
    setOverrideModules((prev) => {
      const next = new Set(prev);
      const allSelected = values.every((value) => next.has(value));
      if (allSelected) {
        values.forEach((value) => next.delete(value));
      } else {
        values.forEach((value) => next.add(value));
      }
      return Array.from(next);
    });
  }

  const authToken = token || "";
  const isAdvanceMode = mode === "advance";
  const claims = useMemo(() => decodeTokenClaims(token), [token]);
  const canAccessCoupons = useMemo(() => hasCouponModuleAccess(claims), [claims]);
  const canAccessAdvanceCoupons = useMemo(() => hasAdvanceCouponModuleAccess(claims), [claims]);
  const canAccessCurrentMode = isAdvanceMode ? canAccessAdvanceCoupons : canAccessCoupons;

  const pageTitle = isAdvanceMode ? "Advance coupons" : "Coupons";
  const pageDescription = isAdvanceMode
    ? "Amend an active tenant subscription immediately with a new subscription version."
    : "Create and manage standard discount campaigns.";
  let createActionLabel = "Create coupon";
  if (isAdvanceMode) {
    createActionLabel = "Apply advance coupon";
  }
  if (saving) {
    createActionLabel = "Creating...";
  }

  const copyCode = async () => {
    if (!code.trim()) return;
    try {
      await navigator.clipboard.writeText(code.trim());
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 1800);
    } catch {
      // clipboard not available
    }
  };

  const copyRowCode = async (id: string, codeValue: string) => {
    try {
      await navigator.clipboard.writeText(codeValue);
      setCopiedRowId(id);
      setTimeout(() => setCopiedRowId(null), 1800);
    } catch {
      // clipboard not available
    }
  };

  const resetForm = () => {
    setCode("");
    setProductId(products[0]?.id || "");
    setDiscountPercent("");
    setDiscountAmountRupees("");
    setExclusiveTenantId("");
    setMaxRedemptions("");
    setOverrideTenureMonths("");
    setOverrideMaxUsers("");
    setOverrideModules([]);
    setCodeCopied(false);
  };

  const openCreateForm = () => {
    resetForm();
    setIsFormOpen(true);
  };

  const closeForm = () => {
    setIsFormOpen(false);
    resetForm();
  };

  const modeRows = useMemo(() => {
    return rows.filter((item) => (isAdvanceMode ? isAdvanceCoupon(item) : !isAdvanceCoupon(item)));
  }, [isAdvanceMode, rows]);

  const filteredCoupons = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return modeRows;
    }

    return modeRows.filter((item) => {
      const productName = products.find((product) => product.id === item.product_id)?.name || "";
      const haystack = [item.code, productName, item.product_id || "all"].join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }, [modeRows, products, search]);

  const effectiveExpandedCouponId = useMemo(() => {
    if (!expandedCouponId) {
      return null;
    }
    return filteredCoupons.some((item) => item.id === expandedCouponId) ? expandedCouponId : null;
  }, [expandedCouponId, filteredCoupons]);

  const loadDashboard = async () => {
    if (!canAccessCurrentMode) {
      setError("This module is disabled for your account.");
      return;
    }
    setError(null);
    setMessage(null);
    setLoading(true);
    try {
      const [productList, couponList] = await Promise.all([listProducts(authToken), listCoupons(authToken)]);
      setProducts(productList);
      setRows(couponList);
      setProductId((current) => current || productList[0]?.id || "");
    } catch {
      setError("Unable to load coupons dashboard.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authToken || !canAccessCurrentMode) {
      return;
    }

    let active = true;
    const bootstrap = async () => {
      if (active) {
        setLoading(true);
      }
      try {
        const [productList, couponList] = await Promise.all([listProducts(authToken), listCoupons(authToken)]);
        if (!active) {
          return;
        }
        setProducts(productList);
        setProductId((current) => current || productList[0]?.id || "");
        setRows(couponList);
      } catch {
        if (!active) {
          return;
        }
        setProducts([]);
        setRows([]);
        setError("Unable to load coupons dashboard.");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void bootstrap();

    return () => {
      active = false;
    };
  }, [authToken, canAccessCurrentMode]);

  const createCouponAction = async () => {
    setError(null);
    setMessage(null);

    const hasPercent = discountPercent.trim().length > 0;
    const hasAmount = discountAmountRupees.trim().length > 0;
    if (!isAdvanceMode && hasPercent === hasAmount) {
      setError("Set exactly one discount type: percent or amount.");
      return;
    }

    const hasAdvanceFields = Boolean(
      overrideTenureMonths.trim()
      || overrideMaxUsers.trim()
      || overrideModules.length > 0,
    );

    if (isAdvanceMode && !exclusiveTenantId.trim()) {
      setError("Tenant id is required for an advance coupon.");
      return;
    }

    if (isAdvanceMode && !hasAdvanceFields) {
      setError("Set at least one subscription addition for an advance coupon.");
      return;
    }

    if (isAdvanceMode) {
      const confirmedTenantId = globalThis.window.prompt(
        "This will affect the subscription immediately and create a new subscription version. Enter the tenant id again to confirm.",
      );
      if (confirmedTenantId === null) {
        return;
      }
      if (confirmedTenantId.trim() !== exclusiveTenantId.trim()) {
        setError("Tenant id confirmation did not match.");
        return;
      }
    }

    setSaving(true);
    try {
      const payload: CouponCreateInput = {
        code: isAdvanceMode ? `ADV-${generateCouponCode()}` : code.trim(),
      };
      if (isAdvanceMode) {
        payload.exclusive_for_tenant_id = exclusiveTenantId.trim() || null;
        payload.override_tenure_months = overrideTenureMonths.trim() ? Number(overrideTenureMonths) : null;
        payload.override_max_users = overrideMaxUsers.trim() ? Number(overrideMaxUsers) : null;
        payload.override_modules = overrideModules.length > 0 ? overrideModules : null;
      } else {
        payload.product_id = productId.trim() || null;
        payload.discount_percent = hasPercent ? Number(discountPercent) : null;
        payload.discount_amount_paise = hasAmount ? Math.round(Number(discountAmountRupees) * 100) : null;
        payload.max_redemptions = maxRedemptions.trim() ? Number(maxRedemptions) : null;
      }
      await createCoupon(payload, authToken);
      setIsFormOpen(false);
      resetForm();
      await loadDashboard();
      setMessage(isAdvanceMode ? "Advance coupon applied. A new subscription version is now active." : "Coupon created successfully.");
    } catch {
      setError("Unable to create coupon.");
    } finally {
      setSaving(false);
    }
  };

  const pauseCouponAction = async (couponId: string) => {
    if (!authToken) {
      return;
    }
    setError(null);
    setMessage(null);
    setActioningCouponId(couponId);
    try {
      await pauseCoupon(couponId, authToken);
      await loadDashboard();
      setMessage("Coupon paused. It can no longer be redeemed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to pause coupon.");
    } finally {
      setActioningCouponId(null);
    }
  };

  const deleteCouponAction = async (couponId: string, couponCode: string) => {
    if (!authToken) {
      return;
    }
    const confirmed = globalThis.confirm(`Delete ${couponCode}? This action cannot be undone.`);
    if (!confirmed) {
      return;
    }
    setError(null);
    setMessage(null);
    setActioningCouponId(couponId);
    try {
      await deleteCoupon(couponId, authToken);
      await loadDashboard();
      setMessage("Coupon deleted successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete coupon.");
    } finally {
      setActioningCouponId(null);
    }
  };

  if (authToken && !canAccessCurrentMode) {
    return (
      <PageShell
        eyebrow="Coupons"
        title={pageTitle}
        description="Access denied for this module based on backend permissions."
        compactHeader
      >
        <p className="subtle status-error">This module is disabled for your account.</p>
      </PageShell>
    );
  }

  return (
    <PageShell
      eyebrow="Coupons"
      title={pageTitle}
      description={pageDescription}
      compactHeader
      headerActions={
        <div className="product-hero-actions">
          <button className="button secondary product-hero-button" type="button" onClick={loadDashboard} disabled={loading || !authToken} aria-label={loading ? "Refreshing coupons" : "Refresh coupons"} title={loading ? "Refreshing coupons" : "Refresh coupons"}>
            <RefreshIcon />
          </button>
          <Link
            href={isAdvanceMode ? "/coupons" : "/coupons/advance"}
            className="button secondary product-hero-button"
          >
            <span>{isAdvanceMode ? "Normal" : "Advance"}</span>
          </Link>
          <button className="button product-hero-button" type="button" onClick={openCreateForm} disabled={!authToken}>
            <AddIcon />
            <span>Add</span>
          </button>
        </div>
      }
    >
      <section className="table-card">
        <h2 className="section-title">{isAdvanceMode ? "Advance coupons" : "Coupons"}</h2>
        <div className="table-toolbar">
          <input
            className="input table-search"
            type="search"
            placeholder="Search by code or product"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="table-shell coupon-table-shell">
          <table className="table coupon-table">
            <thead>
              <tr>
                <th>Coupon</th>
                <th>Discount</th>
                <th>Window</th>
                <th>Redemptions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={4} className="empty-state table-loading-state">
                    <span className="loading-ring" aria-hidden="true" />
                    <span>Loading coupons...</span>
                  </td>
                </tr>
              ) : null}
              {!loading && filteredCoupons.length === 0 ? (
                <tr>
                  <td colSpan={4} className="empty-state">No matching coupons found.</td>
                </tr>
              ) : null}
              {!loading && filteredCoupons.length > 0 ? (
                filteredCoupons.map((item) => {
                  const isExpanded = effectiveExpandedCouponId === item.id;
                  const detailId = `coupon-details-${item.id}`;
                  const productName = products.find((product) => product.id === item.product_id)?.name || item.product_id || "All products";

                  return (
                    <Fragment key={item.id}>
                      <tr className={`coupon-summary-row ${isExpanded ? "coupon-summary-row-open" : ""}`.trim()}>
                        <td className="coupon-cell-code">
                          <div className="coupon-name-cell">
                            <div className="coupon-code-row">
                              <button
                                className="coupon-name-toggle"
                                type="button"
                                onClick={() => setExpandedCouponId((prev) => (prev === item.id ? null : item.id))}
                                aria-expanded={isExpanded}
                                aria-controls={detailId}
                              >
                                <strong>{item.code}</strong>
                              </button>
                              <button
                                className="coupon-row-copy-btn"
                                type="button"
                                onClick={() => copyRowCode(item.id, item.code)}
                                aria-label={copiedRowId === item.id ? "Copied!" : `Copy ${item.code}`}
                                title={copiedRowId === item.id ? "Copied!" : "Copy code"}
                              >
                                {copiedRowId === item.id ? (
                                  <span className="coupon-row-copy-tick" aria-hidden="true">✓</span>
                                ) : (
                                  <CopyIcon />
                                )}
                              </button>
                            </div>
                            <span className="subtle coupon-product-label">{productName}</span>
                            <span className="subtle coupon-product-label">Status: {item.status}</span>
                          </div>
                        </td>
                        <td className="coupon-cell-discount">{formatDiscountSummary(item)}</td>
                        <td className="coupon-cell-window">{formatWindowSummary(item.valid_from, item.valid_until)}</td>
                        <td className="coupon-cell-redemptions">
                          <div className="product-pricing-cell">
                            <span className="product-pricing-value">{`${item.redemption_count} / ${item.max_redemptions ?? "-"}`}</span>
                            <button
                              className="product-price-toggle"
                              type="button"
                              onClick={() => setExpandedCouponId((prev) => (prev === item.id ? null : item.id))}
                              aria-expanded={isExpanded}
                              aria-controls={detailId}
                              aria-label={isExpanded ? `Collapse ${item.code}` : `Expand ${item.code}`}
                              title={isExpanded ? `Collapse ${item.code}` : `Expand ${item.code}`}
                            >
                              <span className="product-price-chevron" aria-hidden="true">▾</span>
                            </button>
                          </div>
                        </td>
                      </tr>
                      {isExpanded ? (
                        <tr className="coupon-detail-row" id={detailId}>
                          <td colSpan={4}>
                            <section className="coupon-detail-panel" aria-label={`Details for coupon ${item.code}`}>
                              <section className="coupon-detail-group">
                                <p className="product-detail-kicker">Overview</p>
                                <div className="coupon-overview-meta">
                                  <article className="coupon-overview-stat">
                                    <span className="product-overview-label">Product</span>
                                    <strong>{productName}</strong>
                                  </article>
                                  <article className="coupon-overview-stat">
                                    <span className="product-overview-label">Discount</span>
                                    <strong>{formatDiscountSummary(item)}</strong>
                                  </article>
                                  <article className="coupon-overview-stat">
                                    <span className="product-overview-label">Window</span>
                                    <strong>{formatWindowSummary(item.valid_from, item.valid_until)}</strong>
                                  </article>
                                  <article className="coupon-overview-stat">
                                    <span className="product-overview-label">Status</span>
                                    <strong>{item.status}</strong>
                                  </article>
                                </div>
                              </section>
                              <section className="coupon-detail-group">
                                <p className="product-detail-kicker">Redemptions</p>
                                <div className="product-usage-summary-grid">
                                  <article className="product-usage-summary-card">
                                    <span className="product-usage-summary-title">Usage</span>
                                    <div className="product-usage-pairs">
                                      <div className="product-usage-pair">
                                        <strong>{item.redemption_count}</strong>
                                        <span className="subtle">Used</span>
                                      </div>
                                      <div className="product-usage-pair">
                                        <strong>{item.max_redemptions ?? "-"}</strong>
                                        <span className="subtle">Max</span>
                                      </div>
                                    </div>
                                  </article>
                                </div>
                              </section>
                              {isAdvanceMode ? (
                                <section className="coupon-detail-group">
                                  <p className="product-detail-kicker">Overrides</p>
                                  <p className="product-detail-copy">{formatOverrideSummary(item)}</p>
                                  {item.exclusive_for_tenant_id ? <p className="subtle">Exclusive tenant: {item.exclusive_for_tenant_id}</p> : null}
                                </section>
                              ) : null}
                              {item.status === "deleted" ? null : (
                                <section className="coupon-detail-group">
                                  <p className="product-detail-kicker">Actions</p>
                                  <div className="product-editor-actions">
                                    <button
                                      className="button secondary"
                                      type="button"
                                      onClick={() => pauseCouponAction(item.id)}
                                      disabled={item.status !== "active" || actioningCouponId === item.id}
                                    >
                                      {actioningCouponId === item.id ? "Working..." : "Pause"}
                                    </button>
                                    <button
                                      className="button secondary"
                                      type="button"
                                      onClick={() => deleteCouponAction(item.id, item.code)}
                                      disabled={actioningCouponId === item.id}
                                    >
                                      {actioningCouponId === item.id ? "Working..." : "Delete"}
                                    </button>
                                  </div>
                                </section>
                              )}
                            </section>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {isFormOpen ? (
        <dialog open className="product-editor-overlay" aria-label="Coupon editor">
          <button type="button" aria-label="Close coupon editor" className="product-editor-backdrop" onClick={closeForm} />
          <aside className="product-editor-panel">
            <div className="product-editor-header">
              <div>
                <h2 className="section-title">{isAdvanceMode ? "New advance coupon" : "New coupon"}</h2>
              </div>
              <button className="button secondary" type="button" onClick={closeForm}>
                Close
              </button>
            </div>

            <div className="form-grid product-editor-form">
              {!user || !authToken ? (
                <p className="subtle">
                  Sign in from <Link href="/">home</Link> to call protected coupon APIs.
                </p>
              ) : (
                <p className="subtle">Authenticated</p>
              )}
              {isAdvanceMode ? (
                <p className="subtle">Coupon code is auto-generated. Saving this amendment updates the tenant subscription immediately and creates a new version.</p>
              ) : (
                <>
                  <div className="field">
                    <div className="coupon-code-label-row">
                      <span>Coupon code</span>
                      <div className="coupon-code-actions">
                        <button
                          type="button"
                          className="coupon-code-action-btn"
                          onClick={() => setCode(generateCouponCode())}
                          title="Auto-generate code"
                          aria-label="Auto-generate coupon code"
                        >
                          Generate
                        </button>
                        <button
                          type="button"
                          className="coupon-code-action-btn"
                          onClick={copyCode}
                          title={codeCopied ? "Copied!" : "Copy code"}
                          aria-label={codeCopied ? "Copied to clipboard" : "Copy coupon code"}
                          disabled={!code.trim()}
                        >
                          {codeCopied ? "Copied!" : "Copy"}
                        </button>
                      </div>
                    </div>
                    <input placeholder="SUMMER-2026" value={code} onChange={(event) => setCode(event.target.value)} />
                  </div>
                  <label className="field">
                    <span>Product</span>
                    <select value={productId} onChange={(event) => setProductId(event.target.value)}>
                      <option value="">All products</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name} ({product.code})
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="row">
                    <label className="field">
                      <span>Discount %</span>
                      <input
                        placeholder="10"
                        value={discountPercent}
                        onChange={(event) => {
                          setDiscountPercent(event.target.value);
                          if (event.target.value.trim()) {
                            setDiscountAmountRupees("");
                          }
                        }}
                      />
                    </label>
                    <label className="field">
                      <span>Discount amount (INR)</span>
                      <input
                        type="text"
                        inputMode="decimal"
                        autoComplete="off"
                        placeholder="50"
                        value={discountAmountRupees}
                        onChange={(event) => {
                          setDiscountAmountRupees(event.target.value);
                          if (event.target.value.trim()) {
                            setDiscountPercent("");
                          }
                        }}
                      />
                    </label>
                  </div>
                  <label className="field">
                    <span>Max redemptions per code</span>
                    <input inputMode="numeric" placeholder="25" value={maxRedemptions} onChange={(event) => setMaxRedemptions(event.target.value)} />
                  </label>
                </>
              )}

              {isAdvanceMode ? (
                <>
                  <label className="field">
                    <span>Tenant id</span>
                    <input placeholder="ten_..." value={exclusiveTenantId} onChange={(event) => setExclusiveTenantId(event.target.value)} />
                  </label>
                  <div className="row">
                    <label className="field">
                      <span>Add tenure months</span>
                      <input type="number" placeholder="2" value={overrideTenureMonths} onChange={(event) => setOverrideTenureMonths(event.target.value)} />
                    </label>
                    <label className="field">
                      <span>Add max users</span>
                      <input type="number" placeholder="25" value={overrideMaxUsers} onChange={(event) => setOverrideMaxUsers(event.target.value)} />
                    </label>
                  </div>
                  <div className="field">
                    <span>Add modules</span>
                    <div className="checklist">
                      {MODULE_OPTIONS.map((option) => {
                        const active = option.values.every((value) => overrideModules.includes(value));
                        return (
                          <label key={option.label} className="check-item">
                            <input type="checkbox" checked={active} onChange={() => toggleModuleGroup(option.values)} />
                            <span className="subtle">{option.label}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                </>
              ) : null}

              <div className="product-editor-actions">
                <button className="button" type="button" onClick={createCouponAction} disabled={saving || !authToken}>
                  {createActionLabel}
                </button>
                <button className="button secondary" type="button" onClick={closeForm}>
                  Cancel
                </button>
              </div>

              {error ? <p className="subtle status-error">{error}</p> : null}
              {message ? <p className="subtle status-success">{message}</p> : null}
            </div>
          </aside>
        </dialog>
      ) : null}
    </PageShell>
  );
}
