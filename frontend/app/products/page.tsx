"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { PageShell } from "@/components/page-shell";
import { decodeTokenClaims, hasProductModuleAccess } from "@/lib/access";
import {
  createProduct,
  deleteProduct,
  listProducts,
  listSubscriptions,
  updateProduct,
  type AdminSubscription,
  type ProductCreateInput,
  type ProductItem,
  type ProductUpdateInput,
} from "@/lib/api-client";

const moduleOptions = [
  { label: "Execution", values: ["execution", "dpr"] },
  { label: "accounts", values: ["accounts", "expense"] },
  { label: "HR", values: ["attendance", "hr"] },
  { label: "Store", values: ["store"] },
  { label: "Survey", values: ["survey"] },
  { label: "Command", values: ["command"] },
];

type ProductUsage = {
  totalSubscriptions: number;
  activeSubscriptions: number;
  totalTenants: number;
  activeTenants: number;
};

type DashboardState = {
  products: ProductItem[];
  subscriptions: AdminSubscription[];
};

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

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20h4l10.5-10.5a2.12 2.12 0 1 0-3-3L5 17v3z" />
      <path d="M13.5 6.5l4 4" />
    </svg>
  );
}

function DeleteIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 7h14" />
      <path d="M9 7V5h6v2" />
      <path d="M8 7l1 12h6l1-12" />
      <path d="M10 11v5" />
      <path d="M14 11v5" />
    </svg>
  );
}

function formatInr(amountPaise: number): string {
  return `₹${(amountPaise / 100).toLocaleString("en-IN")}`;
}

function formatPricingLines(pricing: ProductItem["pricing"]): string[] {
  if (!pricing.length) {
    return ["No pricing tiers"];
  }

  return pricing.map((item) => `${item.tenure_months}m · ${formatInr(item.amount_paise)}`);
}

function formatPricingSummary(pricing: ProductItem["pricing"]): string {
  if (!pricing.length) {
    return "No pricing tiers";
  }

  const sorted = [...pricing].sort((a, b) => a.amount_paise - b.amount_paise);
  const first = sorted[0];
  if (!first) {
    return "No pricing tiers";
  }

  const moreCount = sorted.length - 1;
  return moreCount > 0
    ? `From ${formatInr(first.amount_paise)} · +${moreCount} tiers`
    : `${first.tenure_months}m · ${formatInr(first.amount_paise)}`;
}

function formatMonthlyPricing(pricing: ProductItem["pricing"]): string {
  if (!pricing.length) {
    return "-";
  }

  const monthlyValues = pricing
    .filter((item) => item.tenure_months > 0)
    .map((item) => item.amount_paise / item.tenure_months / 100);

  if (!monthlyValues.length) {
    return "-";
  }

  const minimumMonthly = Math.min(...monthlyValues);
  return `₹${Math.round(minimumMonthly).toLocaleString("en-IN")}/m`;
}

function resolveBillingCycles(product: ProductItem): ProductItem["billing_cycles"] {
  if (product.billing_cycles) {
    return product.billing_cycles;
  }

  const monthly = product.pricing.find((item) => item.tenure_months === 1);
  const yearly = product.pricing.find((item) => item.tenure_months === 12);
  if (!monthly || !yearly) {
    return null;
  }

  const monthlyAmount = Number(monthly.amount_paise || 0);
  const yearlyAmount = Number(yearly.amount_paise || 0);
  if (monthlyAmount <= 0 || yearlyAmount <= 0 || yearlyAmount >= monthlyAmount * 12) {
    return null;
  }

  const discountPercent = Math.max(0, ((monthlyAmount * 12 - yearlyAmount) / (monthlyAmount * 12)) * 100);
  return {
    monthly_amount_paise: monthlyAmount,
    yearly_amount_paise: yearlyAmount,
    yearly_discount_percent: Math.round(discountPercent * 100) / 100,
  };
}

const ALLOWED_RICH_TEXT_TAGS = new Set(["A", "B", "STRONG", "I", "EM", "U", "BR", "P", "UL", "OL", "LI"]);

function unwrapElement(element: HTMLElement): void {
  const parent = element.parentNode;
  if (!parent) {
    return;
  }
  while (element.firstChild) {
    parent.insertBefore(element.firstChild, element);
  }
  element.remove();
}

function sanitizeAnchorAttributes(element: HTMLElement): void {
  const attributes = [...element.attributes];
  for (const attribute of attributes) {
    const key = attribute.name.toLowerCase();
    if (key !== "href" && key !== "target" && key !== "rel") {
      element.removeAttribute(attribute.name);
      continue;
    }
    if (key === "href") {
      const value = attribute.value.trim();
      if (!/^https?:\/\//i.test(value) && !value.startsWith("mailto:")) {
        element.removeAttribute("href");
      }
    }
  }
  element.setAttribute("target", "_blank");
  element.setAttribute("rel", "noopener noreferrer");
}

function sanitizeGenericAttributes(element: HTMLElement): void {
  const attributes = [...element.attributes];
  for (const attribute of attributes) {
    const key = attribute.name.toLowerCase();
    if (key.startsWith("on") || key === "style" || key === "class") {
      element.removeAttribute(attribute.name);
      continue;
    }
    element.removeAttribute(attribute.name);
  }
}

function sanitizeRichTextNode(node: Node): void {
  if (node.nodeType === Node.ELEMENT_NODE) {
    const element = node as HTMLElement;
    if (!ALLOWED_RICH_TEXT_TAGS.has(element.tagName)) {
      unwrapElement(element);
      return;
    }
    if (element.tagName === "A") {
      sanitizeAnchorAttributes(element);
    } else {
      sanitizeGenericAttributes(element);
    }
  }

  const children = [...node.childNodes];
  for (const child of children) {
    sanitizeRichTextNode(child);
  }
}

function sanitizeRichTextHtml(input: string): string {
  if (!input.trim()) {
    return "";
  }

  const template = document.createElement("template");
  template.innerHTML = input;

  sanitizeRichTextNode(template.content);
  return template.innerHTML.trim();
}

function paiseToRupeesInput(amountPaise: number): string {
  return (amountPaise / 100).toFixed(2).replace(/\.00$/, "");
}

function splitNonEmptyLines(input: string): string[] {
  return input
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean);
}

function buildOrderedRows(input: string): Array<{ label: string; order: number }> | null {
  const lines = splitNonEmptyLines(input);
  if (!lines.length) {
    return null;
  }
  return lines.map((label, index) => ({ label, order: index + 1 }));
}

function renderTemplate(template: string | null | undefined, values: Record<string, string>): string {
  if (!template?.trim()) {
    return "";
  }
  return template.replace(/\{([a-z_]+)\}/g, (_, token: string) => values[token] ?? "");
}

function canViewSubscriptions(claims: Record<string, unknown>): boolean {
  const role = typeof claims.role === "string" ? claims.role.toLowerCase() : "";
  const roles = Array.isArray(claims.roles)
    ? claims.roles.filter((item): item is string => typeof item === "string").map((item) => item.toLowerCase())
    : [];
  return role === "admin" || role === "super_admin" || roles.includes("admin") || roles.includes("super_admin");
}

async function fetchDashboardState(token: string, canSeeSubscriptionData: boolean): Promise<DashboardState> {
  const products = await listProducts(token);
  const subscriptions = canSeeSubscriptionData ? await listSubscriptions(token) : [];
  return { products, subscriptions };
}

export default function ProductsPage() { // NOSONAR: page orchestrator intentionally composes dashboard + modal state
  const { token, user } = useAuth();
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [subscriptions, setSubscriptions] = useState<AdminSubscription[]>([]);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [expandedProductId, setExpandedProductId] = useState<string | null>(null);

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingProductId, setEditingProductId] = useState<string | null>(null);

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [baseMaxUsers, setBaseMaxUsers] = useState("25");
  const [selectedModules, setSelectedModules] = useState<Set<string>>(new Set(["execution", "dpr", "store"]));
  const [monthlyAmountRupees, setMonthlyAmountRupees] = useState("1200");
  const [yearlyAmountRupees, setYearlyAmountRupees] = useState("12000");
  const [homeUsersText, setHomeUsersText] = useState("");
  const [homeDescriptionText, setHomeDescriptionText] = useState("");
  const [homeModulesText, setHomeModulesText] = useState("");
  const [checkoutPlanTemplate, setCheckoutPlanTemplate] = useState("{plan_name} - {users_text}");
  const [checkoutPriceTemplate, setCheckoutPriceTemplate] = useState("{price}{period}");
  const [checkoutCommitmentText, setCheckoutCommitmentText] = useState("");
  const [checkoutTrustRowsText, setCheckoutTrustRowsText] = useState("");
  const [isMostPopular, setIsMostPopular] = useState(false);
  const [isLive, setIsLive] = useState(true);
  const [seriesOrder, setSeriesOrder] = useState("100");
  const [metadataSavingId, setMetadataSavingId] = useState<string | null>(null);
  const [seriesDraftByProductId, setSeriesDraftByProductId] = useState<Record<string, string>>({});

  const toLiveState = (product: ProductItem): boolean => product.is_live === true;

  const authToken = token || "";
  const claims = useMemo(() => decodeTokenClaims(token), [token]);
  const canAccessProducts = useMemo(() => hasProductModuleAccess(claims), [claims]);
  const canSeeSubscriptionData = useMemo(() => canViewSubscriptions(claims), [claims]);

  const usageByProduct = useMemo(() => {
    const map = new Map<string, ProductUsage>();
    const allTenantSets = new Map<string, Set<string>>();
    const activeTenantSets = new Map<string, Set<string>>();

    for (const item of subscriptions) {
      const current = map.get(item.product_id) || {
        totalSubscriptions: 0,
        activeSubscriptions: 0,
        totalTenants: 0,
        activeTenants: 0,
      };
      current.totalSubscriptions += 1;
      if (item.status === "active") {
        current.activeSubscriptions += 1;
      }
      map.set(item.product_id, current);

      const allTenants = allTenantSets.get(item.product_id) || new Set<string>();
      allTenants.add(item.tenant_id);
      allTenantSets.set(item.product_id, allTenants);

      if (item.status === "active") {
        const activeTenants = activeTenantSets.get(item.product_id) || new Set<string>();
        activeTenants.add(item.tenant_id);
        activeTenantSets.set(item.product_id, activeTenants);
      }
    }

    for (const [productId, current] of map.entries()) {
      current.totalTenants = allTenantSets.get(productId)?.size || 0;
      current.activeTenants = activeTenantSets.get(productId)?.size || 0;
      map.set(productId, current);
    }

    return map;
  }, [subscriptions]);

  const dashboardStats = useMemo(() => {
    const activeTenantIds = new Set<string>();
    let productsWithActiveTenants = 0;

    for (const item of products) {
      const usage = usageByProduct.get(item.id);
      if (!usage) {
        continue;
      }
      if (usage.activeTenants > 0) {
        productsWithActiveTenants += 1;
      }
      const productSubs = subscriptions.filter((subscription) => subscription.product_id === item.id && subscription.status === "active");
      for (const subscription of productSubs) {
        activeTenantIds.add(subscription.tenant_id);
      }
    }

    const totalBaseUsers = products.reduce((sum, item) => sum + item.base_max_users, 0);

    return {
      totalProducts: products.length,
      productsWithActiveTenants,
      activeTenants: activeTenantIds.size,
      avgBaseUsers: products.length ? Math.round(totalBaseUsers / products.length) : 0,
    };
  }, [products, subscriptions, usageByProduct]);

  const filteredProducts = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return products;
    }

    return products.filter((item) => {
      const usage = usageByProduct.get(item.id);
      const haystack = [
        item.name,
        item.code,
        item.modules.join(" "),
        String(usage?.activeTenants || 0),
        String(usage?.totalSubscriptions || 0),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [products, search, usageByProduct]);

  const effectiveExpandedProductId = useMemo(() => {
    if (!expandedProductId) {
      return null;
    }
    return filteredProducts.some((item) => item.id === expandedProductId) ? expandedProductId : null;
  }, [expandedProductId, filteredProducts]);

  const resetForm = () => {
    setCode("");
    setName("");
    setBaseMaxUsers("25");
    setSelectedModules(new Set(["execution", "dpr", "store"]));
    setMonthlyAmountRupees("1200");
    setYearlyAmountRupees("12000");
    setHomeUsersText("");
    setHomeDescriptionText("");
    setHomeModulesText("");
    setCheckoutPlanTemplate("{plan_name} - {users_text}");
    setCheckoutPriceTemplate("{price}{period}");
    setCheckoutCommitmentText("");
    setCheckoutTrustRowsText("");
    setIsMostPopular(false);
    setIsLive(true);
    setSeriesOrder("100");
    setEditingProductId(null);
  };

  const openCreateForm = () => {
    resetForm();
    setIsFormOpen(true);
  };

  const openEditForm = (product: ProductItem) => {
    const billingCycles = resolveBillingCycles(product);

    setEditingProductId(product.id);
    setCode(product.code);
    setName(product.name);
    setBaseMaxUsers(String(product.base_max_users));
    setSelectedModules(new Set(product.modules.map((item) => item.toLowerCase())));
    setMonthlyAmountRupees(billingCycles ? paiseToRupeesInput(billingCycles.monthly_amount_paise) : "");
    setYearlyAmountRupees(billingCycles ? paiseToRupeesInput(billingCycles.yearly_amount_paise) : "");
    setHomeUsersText(product.home_view?.users_text?.trim() || "");
    setHomeDescriptionText(product.home_view?.description_text?.trim() || "");
    setHomeModulesText((product.home_view?.modules || []).sort((a, b) => a.order - b.order).map((item) => item.label).join("\n"));
    setCheckoutPlanTemplate(product.checkout_view?.summary_plan_name_template?.trim() || "{plan_name} - {users_text}");
    setCheckoutPriceTemplate(product.checkout_view?.summary_price_line_template?.trim() || "{price}{period}");
    setCheckoutCommitmentText(product.checkout_view?.commitment_note_text?.trim() || "");
    setCheckoutTrustRowsText((product.checkout_view?.trust_rows || []).join("\n"));
    setIsMostPopular(Boolean(product.is_most_popular));
    setIsLive(toLiveState(product));
    setSeriesOrder(String(product.series_order || 100));
    setIsFormOpen(true);
  };

  const toggleModuleGroup = (values: string[]) => {
    setSelectedModules((prev) => {
      const next = new Set(prev);
      const allSelected = values.every((value) => next.has(value));
      if (allSelected) {
        values.forEach((value) => next.delete(value));
      } else {
        values.forEach((value) => next.add(value));
      }
      return next;
    });
  };

  const loadDashboard = async () => {
    if (!authToken) {
      setProducts([]);
      setSubscriptions([]);
      return;
    }
    if (!canAccessProducts) {
      setError("Products module is disabled for your account.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const nextState = await fetchDashboardState(authToken, canSeeSubscriptionData);
      setProducts(nextState.products);
      setSubscriptions(nextState.subscriptions);
      setSeriesDraftByProductId((prev) => {
        const next: Record<string, string> = {};
        for (const product of nextState.products) {
          next[product.id] = prev[product.id] ?? String(product.series_order || 100);
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load products dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;

    const bootstrap = async () => {
      if (!authToken) {
        if (active) {
          setProducts([]);
          setSubscriptions([]);
        }
        return;
      }

      if (!canAccessProducts) {
        if (active) {
          setProducts([]);
          setSubscriptions([]);
          setError("Products module is disabled for your account.");
        }
        return;
      }

      if (active) {
        setLoading(true);
        setError(null);
      }

      try {
        const nextState = await fetchDashboardState(authToken, canSeeSubscriptionData);
        if (!active) {
          return;
        }
        setProducts(nextState.products);
        setSubscriptions(nextState.subscriptions);
        setSeriesDraftByProductId((prev) => {
          const next: Record<string, string> = {};
          for (const product of nextState.products) {
            next[product.id] = prev[product.id] ?? String(product.series_order || 100);
          }
          return next;
        });
      } catch (err) {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : "Unable to load products dashboard");
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
  }, [authToken, canAccessProducts, canSeeSubscriptionData]);

  if (authToken && !canAccessProducts) {
    return (
      <PageShell
        eyebrow="Products"
        title="Products"
        description="Access denied for this module based on backend permissions."
        compactHeader
      >
        <p className="subtle status-error">Products module is disabled for your account.</p>
      </PageShell>
    );
  }

  const buildPayload = (): ProductCreateInput | null => {
    const baseUsers = Number(baseMaxUsers);
    if (!Number.isInteger(baseUsers) || baseUsers <= 0) {
      setError("Base max users must be a positive whole number.");
      return null;
    }

    const monthlyAmountPaise = Math.round(Number(monthlyAmountRupees) * 100);
    const yearlyAmountPaise = Math.round(Number(yearlyAmountRupees) * 100);
    if (!Number.isFinite(monthlyAmountPaise) || monthlyAmountPaise <= 0) {
      setError("Monthly amount must be a valid positive value.");
      return null;
    }
    if (!Number.isFinite(yearlyAmountPaise) || yearlyAmountPaise <= 0) {
      setError("Yearly amount must be a valid positive value.");
      return null;
    }
    if (yearlyAmountPaise >= monthlyAmountPaise * 12) {
      setError("Yearly amount must include a discount compared to 12 monthly payments.");
      return null;
    }

    const selected = Array.from(selectedModules);
    if (!selected.length) {
      setError("Select at least one module.");
      return null;
    }

    const parsedSeriesOrder = Number(seriesOrder);
    if (!Number.isInteger(parsedSeriesOrder) || parsedSeriesOrder <= 0) {
      setError("Series order must be a positive whole number.");
      return null;
    }

    const homeModules = buildOrderedRows(homeModulesText);
    const checkoutTrustRows = splitNonEmptyLines(checkoutTrustRowsText);

    return {
      code: code.trim(),
      name: name.trim(),
      description: null,
      features: null,
      modules: selected,
      base_max_users: baseUsers,
      pricing: [
        { tenure_months: 1, amount_paise: monthlyAmountPaise },
        { tenure_months: 12, amount_paise: yearlyAmountPaise },
      ],
      billing_cycles: {
        monthly_amount_paise: monthlyAmountPaise,
        yearly_amount_paise: yearlyAmountPaise,
      },
      home_view:
        homeUsersText.trim() || homeDescriptionText.trim() || homeModules
          ? {
              users_text: homeUsersText.trim() || null,
              description_text: homeDescriptionText.trim() || null,
              modules: homeModules,
            }
          : null,
      checkout_view:
        checkoutPlanTemplate.trim() || checkoutPriceTemplate.trim() || checkoutCommitmentText.trim() || checkoutTrustRows.length
          ? {
              summary_plan_name_template: checkoutPlanTemplate.trim() || null,
              summary_price_line_template: checkoutPriceTemplate.trim() || null,
              commitment_note_text: checkoutCommitmentText.trim() || null,
              trust_rows: checkoutTrustRows.length ? checkoutTrustRows : null,
            }
          : null,
      is_most_popular: isMostPopular,
      is_live: isLive,
      series_order: parsedSeriesOrder,
    };
  };

  const updateProductMetadata = async (product: ProductItem, payload: ProductUpdateInput) => {
    if (!authToken) {
      setError("Sign in from Auth before updating products.");
      return;
    }
    setError(null);
    setMessage(null);
    setMetadataSavingId(product.id);
    try {
      await updateProduct(product.id, payload, authToken);
      await loadDashboard();
      setMessage("Product settings updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update product settings");
    } finally {
      setMetadataSavingId(null);
    }
  };

  const saveProduct = async () => {
    if (!authToken) {
      setError("Sign in from Auth before creating or updating products.");
      return;
    }

    setError(null);
    setMessage(null);

    const payload = buildPayload();
    if (!payload) {
      return;
    }

    setSaving(true);
    try {
      if (editingProductId) {
        await updateProduct(editingProductId, payload, authToken);
        setMessage("Product updated successfully.");
      } else {
        await createProduct(payload, authToken);
        setMessage("Product created successfully.");
      }
      await loadDashboard();
      setIsFormOpen(false);
      resetForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save product");
    } finally {
      setSaving(false);
    }
  };

  const removeProduct = async (productId: string, productName: string) => {
    if (!authToken) {
      setError("Sign in from Auth before deleting products.");
      return;
    }

    const confirmed = globalThis.confirm(`Delete ${productName}? This action cannot be undone.`);
    if (!confirmed) {
      return;
    }

    setError(null);
    setMessage(null);
    setDeletingId(productId);
    try {
      await deleteProduct(productId, authToken);
      setMessage("Product deleted successfully.");
      await loadDashboard();
      if (editingProductId === productId) {
        setIsFormOpen(false);
        resetForm();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete product");
    } finally {
      setDeletingId(null);
    }
  };

  const saveButtonText = (() => {
    if (saving && editingProductId) {
      return "Updating...";
    }
    if (saving) {
      return "Creating...";
    }
    return editingProductId ? "Update product" : "Create product";
  })();

  const previewPlanName = name.trim() || "Core Plan";
  const previewUsersText = homeUsersText.trim() || (Number(baseMaxUsers) >= 100000 ? "Unlimited users" : `Up to ${baseMaxUsers || "0"} users`);
  const monthlyAmountValue = Number(monthlyAmountRupees);
  const yearlyAmountValue = Number(yearlyAmountRupees);
  const previewPriceText = Number.isFinite(yearlyAmountValue) && yearlyAmountValue > 0
    ? `INR ${yearlyAmountValue.toLocaleString("en-IN")}`
    : "Custom";
  const previewMonthlyText = Number.isFinite(monthlyAmountValue) && monthlyAmountValue > 0
    ? `${monthlyAmountValue.toLocaleString("en-IN")}/m`
    : "Custom/m";
  const previewPeriodText = " / 12m";
  const yearlyDiscountPercent =
    Number.isFinite(monthlyAmountValue) && monthlyAmountValue > 0 && Number.isFinite(yearlyAmountValue) && yearlyAmountValue > 0
      ? Math.max(0, ((monthlyAmountValue * 12 - yearlyAmountValue) / (monthlyAmountValue * 12)) * 100)
      : 0;
  const previewTemplateValues = {
    plan_name: previewPlanName,
    users_text: previewUsersText,
    price: previewPriceText,
    period: previewPeriodText,
  };
  const previewSummaryTitle =
    renderTemplate(checkoutPlanTemplate, previewTemplateValues) || `${previewPlanName} - ${previewUsersText}`;
  const previewSummaryPrice =
    renderTemplate(checkoutPriceTemplate, previewTemplateValues) || `${previewPriceText}${previewPeriodText}`;
  const previewHomeModules = buildOrderedRows(homeModulesText)?.map((item) => item.label) || [];
  const previewTrustRows = splitNonEmptyLines(checkoutTrustRowsText);

  let productRowsContent: ReactNode;
  if (loading) {
    productRowsContent = (
      <tr>
        <td colSpan={4} className="empty-state table-loading-state">
          <span className="loading-ring" aria-hidden="true" />
          <span>Loading products...</span>
        </td>
      </tr>
    );
  } else if (filteredProducts.length === 0) {
    productRowsContent = (
      <tr>
        <td colSpan={4} className="empty-state">No matching products found.</td>
      </tr>
    );
  } else {
    productRowsContent = filteredProducts.map((item) => { // NOSONAR: row renderer intentionally composes summary/detail UI actions
      const isLiveProduct = toLiveState(item);
      const billingCycles = resolveBillingCycles(item);
      const usage = usageByProduct.get(item.id) || {
        totalSubscriptions: 0,
        activeSubscriptions: 0,
        totalTenants: 0,
        activeTenants: 0,
      };
      const isExpanded = effectiveExpandedProductId === item.id;
      const detailRegionId = `product-details-${item.id}`;

      return (
        <Fragment key={item.id}>
          <tr className={`product-summary-row ${isExpanded ? "product-summary-row-open" : ""}`.trim()}>
            <td className="product-cell-product">
              <div className="product-name-cell">
                <button
                  className="product-name-toggle"
                  type="button"
                  onClick={() => setExpandedProductId((prev) => (prev === item.id ? null : item.id))}
                  aria-expanded={isExpanded}
                  aria-controls={detailRegionId}
                >
                  <span>{item.name}</span>
                </button>
                <div className="product-inline-meta">
                  <span className={`chip ${isLiveProduct ? "product-state-chip-live" : "product-state-chip-stage"}`}>
                    {isLiveProduct ? "Live" : "Stage"}
                  </span>
                  <span className="chip">Series {item.series_order || 100}</span>
                  {item.is_most_popular ? <span className="chip product-state-chip-popular">Most popular</span> : null}
                </div>
              </div>
            </td>
            <td className="product-cell-code">
              <span className="product-code-value">{item.code}</span>
            </td>
            <td className="product-cell-capacity">
              <div className="product-metric-stack">
                <span className="product-metric-value">{item.base_max_users}</span>
              </div>
            </td>
            <td className="product-cell-pricing">
              <div className="product-pricing-cell">
                <span className="product-pricing-value">{formatMonthlyPricing(item.pricing)}</span>
                <button
                  className="product-price-toggle"
                  type="button"
                  onClick={() => setExpandedProductId((prev) => (prev === item.id ? null : item.id))}
                  aria-expanded={isExpanded}
                  aria-controls={detailRegionId}
                  aria-label={isExpanded ? `Collapse ${item.name}` : `Expand ${item.name}`}
                  title={isExpanded ? `Collapse ${item.name}` : `Expand ${item.name}`}
                >
                  <span className="product-price-chevron" aria-hidden="true">▾</span>
                </button>
              </div>
            </td>
          </tr>
          {isExpanded ? (
            <tr className="product-detail-row" id={detailRegionId}>
              <td colSpan={4}>
                <section className="product-detail-panel" aria-label={`Details for ${item.name}`}>
                  <section className="product-detail-group product-detail-overview">
                    <div className="product-detail-head">
                      <div className="product-detail-head-copy">
                        <p className="product-detail-kicker">Overview</p>
                        <p className="product-detail-copy">{item.description || "No description provided."}</p>
                        {item.features ? (
                          <div className="product-rich-content" dangerouslySetInnerHTML={{ __html: sanitizeRichTextHtml(item.features) }} />
                        ) : null}
                      </div>
                      <div className="product-detail-actions">
                        <button className="icon-button" type="button" onClick={() => openEditForm(item)} aria-label="Edit product" title="Edit product">
                          <EditIcon />
                        </button>
                        <button
                          className="icon-button icon-button-danger"
                          type="button"
                          onClick={() => removeProduct(item.id, item.name)}
                          disabled={deletingId === item.id}
                          aria-label={deletingId === item.id ? "Deleting product" : "Delete product"}
                          title={deletingId === item.id ? "Deleting..." : "Delete product"}
                        >
                          <DeleteIcon />
                        </button>
                      </div>
                    </div>
                    <div className="product-overview-meta">
                      <article className="product-overview-stat">
                        <span className="product-overview-label">Code</span>
                        <strong>{item.code}</strong>
                      </article>
                      <article className="product-overview-stat">
                        <span className="product-overview-label">Users</span>
                        <strong>{item.base_max_users}</strong>
                      </article>
                      <article className="product-overview-stat">
                        <span className="product-overview-label">Pricing</span>
                        <strong>{formatMonthlyPricing(item.pricing)}</strong>
                      </article>
                    </div>
                  </section>
                  <section className="product-detail-group product-detail-modules">
                    <p className="product-detail-kicker">Modules</p>
                    <div className="chips product-module-chips product-module-chips-detail">
                      {item.modules.map((moduleName) => (
                        <span key={`${item.id}-detail-${moduleName}`} className="chip">
                          {moduleName}
                        </span>
                      ))}
                    </div>
                  </section>
                  <section className="product-detail-group product-detail-pricing">
                    <p className="product-detail-kicker">Billing cycles</p>
                    <div className="product-pricing-list">
                      {billingCycles ? (
                        <>
                          <span className="product-pricing-line">
                            Monthly · {formatInr(billingCycles.monthly_amount_paise)}
                          </span>
                          <span className="product-pricing-line">
                            Yearly · {formatInr(billingCycles.yearly_amount_paise)} ({billingCycles.yearly_discount_percent}% off)
                          </span>
                        </>
                      ) : (
                        <span className="product-pricing-line">Monthly/yearly billing cycles are not configured yet.</span>
                      )}
                    </div>
                    <div className="product-pricing-list">
                      {formatPricingLines(item.pricing).map((line) => (
                        <span key={`${item.id}-detail-${line}`} className="product-pricing-line">
                          {line}
                        </span>
                      ))}
                    </div>
                    <p className="subtle">Summary: {formatPricingSummary(item.pricing)}</p>
                  </section>
                  <section className="product-detail-group product-detail-pricing">
                    <p className="product-detail-kicker">Visibility controls</p>
                    <div className="product-detail-actions product-detail-actions-left">
                      <button
                        className="button secondary"
                        type="button"
                        disabled={metadataSavingId === item.id}
                        onClick={() => updateProductMetadata(item, { is_live: !isLiveProduct })}
                      >
                        {isLiveProduct ? "Set stage" : "Set live"}
                      </button>
                      <button
                        className="button secondary"
                        type="button"
                        disabled={metadataSavingId === item.id}
                        onClick={() => updateProductMetadata(item, { is_most_popular: !item.is_most_popular })}
                      >
                        {item.is_most_popular ? "Remove most popular" : "Mark most popular"}
                      </button>
                    </div>
                    <div className="product-series-edit-row">
                      <label className="field product-series-input-wrap">
                        <span>Series order on live website</span>
                        <input
                          inputMode="numeric"
                          value={seriesDraftByProductId[item.id] ?? String(item.series_order || 100)}
                          onChange={(event) =>
                            setSeriesDraftByProductId((prev) => ({
                              ...prev,
                              [item.id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                      <button
                        className="button secondary"
                        type="button"
                        disabled={metadataSavingId === item.id}
                        onClick={() => {
                          const nextSeriesOrder = Number(seriesDraftByProductId[item.id] ?? item.series_order ?? 100);
                          if (!Number.isInteger(nextSeriesOrder) || nextSeriesOrder <= 0) {
                            setError("Series order must be a positive whole number.");
                            return;
                          }
                          void updateProductMetadata(item, { series_order: nextSeriesOrder });
                        }}
                      >
                        Save order
                      </button>
                    </div>
                  </section>
                  <section className="product-detail-group product-detail-usage">
                    <p className="product-detail-kicker">Usage</p>
                    <div className="product-usage-summary-grid">
                      <article className="product-usage-summary-card">
                        <span className="product-usage-summary-title">Tenants</span>
                        <div className="product-usage-pairs">
                          <div className="product-usage-pair">
                            <strong>{usage.activeTenants}</strong>
                            <span className="subtle">Active</span>
                          </div>
                          <div className="product-usage-pair">
                            <strong>{usage.totalTenants}</strong>
                            <span className="subtle">Total</span>
                          </div>
                        </div>
                      </article>
                      <article className="product-usage-summary-card">
                        <span className="product-usage-summary-title">Subscriptions</span>
                        <div className="product-usage-pairs">
                          <div className="product-usage-pair">
                            <strong>{usage.activeSubscriptions}</strong>
                            <span className="subtle">Active</span>
                          </div>
                          <div className="product-usage-pair">
                            <strong>{usage.totalSubscriptions}</strong>
                            <span className="subtle">Total</span>
                          </div>
                        </div>
                      </article>
                    </div>
                  </section>
                </section>
              </td>
            </tr>
          ) : null}
        </Fragment>
      );
    });
  }

  return (
    <PageShell
      eyebrow="Catalog"
      title="Products"
      description="Manage product catalog."
      compactHeader
      headerActions={
        <div className="product-hero-actions">
          <button className="button secondary product-hero-button" type="button" onClick={loadDashboard} disabled={loading || !authToken} aria-label={loading ? "Refreshing products" : "Refresh products"} title={loading ? "Refreshing products" : "Refresh products"}>
            <RefreshIcon />
          </button>
          <button className="button product-hero-button" type="button" onClick={openCreateForm} disabled={!authToken}>
            <AddIcon />
            <span>Add</span>
          </button>
        </div>
      }
    >
      {!user || !authToken ? (
        <p className="subtle muted-block">
          Sign in from <Link href="/">home</Link> to manage products.
        </p>
      ) : null}
      {error ? <p className="subtle status-error">{error}</p> : null}
      {message ? <p className="subtle status-success">{message}</p> : null}

      <section className="product-kpi-grid">
        <article className="product-kpi-card">
          <p className="product-kpi-label">Total products</p>
          <p className="product-kpi-value">{dashboardStats.totalProducts}</p>
        </article>
        <article className="product-kpi-card">
          <p className="product-kpi-label">Adopted products</p>
          <p className="product-kpi-value">{dashboardStats.productsWithActiveTenants}</p>
        </article>
        <article className="product-kpi-card">
          <p className="product-kpi-label">Active tenants</p>
          <p className="product-kpi-value">{dashboardStats.activeTenants}</p>
        </article>
        <article className="product-kpi-card">
          <p className="product-kpi-label">Avg default seats</p>
          <p className="product-kpi-value">{dashboardStats.avgBaseUsers}</p>
        </article>
      </section>

      <section className="table-card product-live-table">
        <h2 className="section-title">Products</h2>
        <div className="table-toolbar">
          <input
            className="input table-search"
            type="search"
            placeholder="Search by product, code, module, or usage"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="table-shell product-table-shell">
          <table className="table product-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Code</th>
                <th>Users</th>
                <th>Pricing</th>
              </tr>
            </thead>
            <tbody>
              {productRowsContent}
            </tbody>
          </table>
        </div>
      </section>

      {isFormOpen ? (
        <dialog open className="product-editor-overlay" aria-label="Product editor">
          <button
            type="button"
            aria-label="Close product editor"
            className="product-editor-backdrop"
            onClick={() => {
              setIsFormOpen(false);
              resetForm();
            }}
          />
          <aside className="product-editor-panel">
            <div className="product-editor-header">
              <div>
                <h2 className="section-title">{editingProductId ? "Edit product" : "New product"}</h2>
              </div>
              <button
                className="button secondary"
                type="button"
                onClick={() => {
                  setIsFormOpen(false);
                  resetForm();
                }}
              >
                Close
              </button>
            </div>

            <div className="form-grid product-editor-form">
              <label className="field">
                <span>Product code</span>
                <input placeholder="CORE-GROWTH" value={code} onChange={(event) => setCode(event.target.value)} />
              </label>
              <label className="field">
                <span>Product name</span>
                <input placeholder="Core Growth" value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label className="field">
                <span>Base max users</span>
                <input inputMode="numeric" placeholder="25" value={baseMaxUsers} onChange={(event) => setBaseMaxUsers(event.target.value)} />
              </label>
              <div className="field">
                <span>Modules included</span>
                <div className="checklist">
                  {moduleOptions.map((option) => {
                    const active = option.values.every((value) => selectedModules.has(value));
                    return (
                      <label key={option.label} className="check-item">
                        <input type="checkbox" checked={active} onChange={() => toggleModuleGroup(option.values)} />
                        <span className="subtle">{option.label}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="field">
                <span>Billing cycles</span>
                <div className="pricing-grid">
                  <label className="field">
                    <span>Monthly amount (INR)</span>
                    <input
                      inputMode="decimal"
                      placeholder="1200"
                      value={monthlyAmountRupees}
                      onChange={(event) => setMonthlyAmountRupees(event.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>Yearly amount (INR)</span>
                    <input
                      inputMode="decimal"
                      placeholder="12000"
                      value={yearlyAmountRupees}
                      onChange={(event) => setYearlyAmountRupees(event.target.value)}
                    />
                  </label>
                </div>
                <p className="subtle">Yearly discount: {yearlyDiscountPercent.toFixed(2)}%</p>
              </div>
              <section className="field product-view-config product-visibility-config">
                <div className="product-visibility-head">
                  <h3 className="section-title">Catalog visibility</h3>
                  <p className="subtle">Decide if this plan is live, highlighted, and where it appears in sales ordering.</p>
                </div>
                <div className="product-visibility-grid">
                  <label className="product-visibility-card">
                    <div className="product-visibility-copy">
                      <span className="product-visibility-title">Most popular badge</span>
                      <span className="product-visibility-desc">Show the Most popular tag on the live pricing card.</span>
                    </div>
                    <span className={`product-toggle ${isMostPopular ? "is-on" : ""}`}>
                      <input
                        type="checkbox"
                        className="product-toggle-input"
                        checked={isMostPopular}
                        onChange={(event) => setIsMostPopular(event.target.checked)}
                        aria-label="Toggle most popular tag"
                      />
                      <span className="product-toggle-track" aria-hidden="true">
                        <span className="product-toggle-thumb" />
                      </span>
                    </span>
                  </label>
                  <label className="product-visibility-card">
                    <div className="product-visibility-copy">
                      <span className="product-visibility-title">Live website visibility</span>
                      <span className="product-visibility-desc">Publish or hide this product from the live sales website.</span>
                    </div>
                    <span className={`product-toggle ${isLive ? "is-on" : ""}`}>
                      <input
                        type="checkbox"
                        className="product-toggle-input"
                        checked={isLive}
                        onChange={(event) => setIsLive(event.target.checked)}
                        aria-label="Toggle live website visibility"
                      />
                      <span className="product-toggle-track" aria-hidden="true">
                        <span className="product-toggle-thumb" />
                      </span>
                    </span>
                  </label>
                </div>
                <label className="field product-series-field">
                  <span>Series order (live listing position)</span>
                  <span className="product-input-help">Lower number appears earlier in the live pricing section.</span>
                  <input
                    inputMode="numeric"
                    placeholder="100"
                    value={seriesOrder}
                    onChange={(event) => setSeriesOrder(event.target.value)}
                  />
                </label>
              </section>

              <section className="field product-view-config">
                <h3 className="section-title">1. Home View Content</h3>
                <p className="subtle">Single source of truth for sales-card copy to avoid duplicate inputs.</p>
                <label className="field">
                  <span>1.1 Users text</span>
                  <span className="product-input-help">Shown below price. Example: Up to 25 users or Unlimited users.</span>
                  <input
                    placeholder="Unlimited users"
                    value={homeUsersText}
                    onChange={(event) => setHomeUsersText(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>1.2 Description text</span>
                  <span className="product-input-help">Main plan description line in the card body.</span>
                  <textarea
                    placeholder="Tailored setup for large teams and integrations"
                    value={homeDescriptionText}
                    onChange={(event) => setHomeDescriptionText(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>1.3 Feature rows (one per line)</span>
                  <span className="product-input-help">Checklist rows shown with a check icon. Write one row per line.</span>
                  <textarea
                    placeholder={"Execution workflows\nHR and attendance\nAccounts visibility"}
                    value={homeModulesText}
                    onChange={(event) => setHomeModulesText(event.target.value)}
                  />
                </label>

                <article className="product-preview-card">
                  <p className="product-preview-kicker">Home card preview</p>
                  <p className="product-preview-title">{previewPlanName}</p>
                  <p className="product-preview-price">{previewPriceText} <span className="subtle">({previewMonthlyText})</span></p>
                  <p className="product-preview-users">{previewUsersText}</p>
                  <p className="product-preview-copy">{homeDescriptionText.trim() || "No custom description provided."}</p>
                  <div className="product-preview-list">
                    {(previewHomeModules.length ? previewHomeModules : ["No module rows configured"]).map((line) => (
                      <div key={line} className="product-preview-row">
                        <span>✓</span>
                        <span>{line}</span>
                      </div>
                    ))}
                  </div>
                </article>
              </section>

              <section className="field product-view-config">
                <h3 className="section-title">2. Checkout View Content</h3>
                <p className="subtle">Used on the checkout summary panel. Keep templates simple and readable.</p>
                <p className="subtle">Tokens you can use in templates: {"{plan_name}"}, {"{users_text}"}, {"{price}"}, {"{period}"}</p>
                <label className="field">
                  <span>2.1 Summary title template</span>
                  <span className="product-input-help">Top line in checkout summary card.</span>
                  <input
                    placeholder="{plan_name} - {users_text}"
                    value={checkoutPlanTemplate}
                    onChange={(event) => setCheckoutPlanTemplate(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>2.2 Summary price template</span>
                  <span className="product-input-help">Price line directly below title.</span>
                  <input
                    placeholder="{price}{period}"
                    value={checkoutPriceTemplate}
                    onChange={(event) => setCheckoutPriceTemplate(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>2.3 Commitment note</span>
                  <span className="product-input-help">Single paragraph explaining what this purchase activates.</span>
                  <textarea
                    placeholder="This checkout activates your organization workspace and first Super Admin account."
                    value={checkoutCommitmentText}
                    onChange={(event) => setCheckoutCommitmentText(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>2.4 Trust checklist rows (one per line)</span>
                  <span className="product-input-help">Proof points shown below summary card. Write one row per line.</span>
                  <textarea
                    placeholder={"Execution module: BOQ progress and billing\nHR module: attendance and payroll"}
                    value={checkoutTrustRowsText}
                    onChange={(event) => setCheckoutTrustRowsText(event.target.value)}
                  />
                </label>

                <article className="product-preview-card">
                  <p className="product-preview-kicker">Checkout panel preview</p>
                  <p className="product-preview-title">{previewSummaryTitle}</p>
                  <p className="product-preview-price">{previewSummaryPrice}</p>
                  <p className="product-preview-copy">
                    {checkoutCommitmentText.trim() || "No custom commitment note provided."}
                  </p>
                  <div className="product-preview-list">
                    {(previewTrustRows.length ? previewTrustRows : ["No trust rows configured"]).map((line) => (
                      <div key={line} className="product-preview-row">
                        <span>✓</span>
                        <span>{line}</span>
                      </div>
                    ))}
                  </div>
                </article>
              </section>

              <div className="product-editor-actions">
                <button className="button" type="button" onClick={saveProduct} disabled={saving || !authToken}>
                {saveButtonText}
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => {
                    setIsFormOpen(false);
                    resetForm();
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </aside>
        </dialog>
      ) : null}
    </PageShell>
  );
}
