type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  token?: string;
  body?: unknown;
};

export type ProductHomeModuleRow = {
  label: string;
  order: number;
};

export type ProductHomeView = {
  users_text?: string | null;
  description_text?: string | null;
  modules?: ProductHomeModuleRow[] | null;
};

export type ProductCheckoutView = {
  summary_plan_name_template?: string | null;
  summary_price_line_template?: string | null;
  commitment_note_text?: string | null;
  trust_rows?: string[] | null;
};

export type ProductBillingCycles = {
  monthly_amount_paise: number;
  yearly_amount_paise: number;
  yearly_discount_percent: number;
};

export type ProductBillingCyclesInput = {
  monthly_amount_paise: number;
  yearly_amount_paise: number;
};

export type ProductItem = {
  id: string;
  code: string;
  description: string | null;
  features: string | null;
  name: string;
  base_max_users: number;
  modules: string[];
  pricing: Array<{
    tenure_months: number;
    amount_paise: number;
  }>;
  billing_cycles?: ProductBillingCycles | null;
  home_view?: ProductHomeView | null;
  checkout_view?: ProductCheckoutView | null;
  is_most_popular?: boolean;
  is_live?: boolean;
  series_order?: number;
  created_at: string;
};

export type ProductCreateInput = {
  code: string;
  name: string;
  description?: string | null;
  features?: string | null;
  modules: string[];
  base_max_users: number;
  pricing: Array<{
    tenure_months: number;
    amount_paise: number;
  }>;
  billing_cycles?: ProductBillingCyclesInput;
  home_view?: ProductHomeView | null;
  checkout_view?: ProductCheckoutView | null;
  is_most_popular?: boolean;
  is_live?: boolean;
  series_order?: number;
};

export type ProductUpdateInput = {
  code?: string;
  name?: string;
  description?: string | null;
  features?: string | null;
  modules?: string[];
  base_max_users?: number;
  pricing?: Array<{
    tenure_months: number;
    amount_paise: number;
  }>;
  home_view?: ProductHomeView | null;
  checkout_view?: ProductCheckoutView | null;
  is_most_popular?: boolean;
  is_live?: boolean;
  series_order?: number;
};

export type SubscriptionProductSnapshot = {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  features?: string | null;
  modules: string[];
  base_max_users: number;
  pricing: Array<{
    tenure_months: number;
    amount_paise: number;
  }>;
  billing_cycles?: ProductBillingCycles | null;
  home_view?: ProductHomeView | null;
  checkout_view?: ProductCheckoutView | null;
};

export type SubscriptionCouponSnapshot = {
  id: string;
  code: string;
  product_id?: string | null;
  discount_percent?: number | null;
  discount_amount_paise?: number | null;
  override_modules?: string[] | null;
  override_max_users?: number | null;
  override_tenure_months?: number | null;
  exclusive_for_tenant_id?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  max_redemptions?: number | null;
};

export type AdminSubscription = {
  id: string;
  tenant_id: string;
  product_id: string;
  status: string;
  version?: number;
  root_subscription_id?: string | null;
  previous_subscription_id?: string | null;
  is_current?: boolean;
  change_reason?: string | null;
  superseded_at?: string | null;
  start_at?: string | null;
  end_at?: string | null;
  modules?: string[];
  max_users?: number;
  amount_paise: number;
  tenure_months: number;
  currency: string;
  coupon_code?: string | null;
  gateway_status?: string | null;
  reconciled_at?: string | null;
  product_snapshot?: SubscriptionProductSnapshot | null;
  coupon_snapshot?: SubscriptionCouponSnapshot | null;
};

export type CouponItem = {
  id: string;
  code: string;
  product_id: string | null;
  discount_percent: number | null;
  discount_amount_paise: number | null;
  override_tenure_months: number | null;
  override_max_users: number | null;
  override_modules: string[] | null;
  exclusive_for_tenant_id: string | null;
  valid_from: string | null;
  valid_until: string | null;
  max_redemptions: number | null;
  redemption_count: number;
  status: string;
  paused_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string | null;
};

export type CouponCreateInput = {
  code: string;
  product_id?: string | null;
  discount_percent?: number | null;
  discount_amount_paise?: number | null;
  override_tenure_months?: number | null;
  override_max_users?: number | null;
  override_modules?: string[] | null;
  exclusive_for_tenant_id?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  max_redemptions?: number | null;
};

export type TenantItem = {
  id: string;
  name: string;
  company_email: string;
  contact_name: string;
  phone: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type TenantCreateInput = {
  name: string;
  company_email: string;
  contact_name: string;
  phone?: string | null;
};

export type TenantUpdateInput = {
  status?: string;
  phone?: string | null;
  name?: string;
  contact_name?: string;
  company_email?: string;
};

export type SuperAdminAssignment = {
  uid: string;
  email: string;
  display_name?: string | null;
  assigned_at: string;
  assigned_by_uid?: string | null;
  assigned_by_email?: string | null;
  updated_at: string;
};

export type SuperAdminInvitation = {
  id: string;
  invitee_email: string;
  status: string;
  invited_at: string;
  expires_at: string;
  invited_by_uid: string;
  invited_by_email: string;
  responded_at?: string | null;
  response_actor_uid?: string | null;
  response_actor_email?: string | null;
  response_note?: string | null;
  resend_count?: number;
  resend_audit?: Array<{
    sent_at: string;
    sent_by_uid: string;
    sent_by_email: string;
    delivery_status: string;
  }>;
};

export type SuperAdminState = {
  current_super_admin: SuperAdminAssignment | null;
  pending_invitation: SuperAdminInvitation | null;
  recent_invitations: SuperAdminInvitation[];
};

export type PortalOperator = {
  uid: string;
  agent_number: string;
  email: string;
  full_name?: string | null;
  display_name?: string | null;
  designation?: string | null;
  role: string;
  permissions: string[];
  disabled: boolean;
  created_at?: string | null;
  last_sign_in_at?: string | null;
};

export type PortalAccessInvitation = {
  id: string;
  invitee_email: string;
  invitee_name?: string | null;
  invitee_designation?: string | null;
  invitee_agent_number?: string | null;
  invitee_phone?: string | null;
  role: string;
  access_scope?: "product" | "coupon" | "advance_coupon" | "both" | "all" | null;
  normal_coupon_max_discount_percent?: number | null;
  permissions: string[];
  status: string;
  invited_at: string;
  expires_at: string;
  invited_by_uid: string;
  invited_by_email: string;
  responded_at?: string | null;
  response_actor_uid?: string | null;
  response_actor_email?: string | null;
  response_note?: string | null;
  resend_count?: number;
  resend_audit?: Array<{
    sent_at: string;
    sent_by_uid: string;
    sent_by_email: string;
    delivery_status: string;
  }>;
};

export type PortalAccessState = {
  operators: PortalOperator[];
  invitations: PortalAccessInvitation[];
};

export type PortalAccessInviteWithScopeInput = {
  invitee_email: string;
  invitee_name: string;
  invitee_designation: string;
  invitee_agent_number: string;
  invitee_phone: string;
  role: string;
  access_scope: "product" | "coupon" | "advance_coupon" | "both" | "all" | null;
  normal_coupon_max_discount_percent: number | null;
};

export type CheckoutIntentInput = {
  tenant_id: string;
  product_id: string;
  tenure_months: number;
  requested_users?: number | null;
  coupon_code?: string | null;
  customer_name: string;
  customer_email: string;
  idempotency_key: string;
};

export type CheckoutIntentResult = {
  subscription_id: string;
  razorpay_order_id: string;
  currency: string;
  amount_paise: number;
  applied_coupon_code: string | null;
  entitlement_modules: string[];
  entitlement_max_users: number;
  entitlement_tenure_months: number;
};

export type CheckoutConfirmInput = {
  subscription_id: string;
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
};

export type CheckoutSubscription = {
  id: string;
  tenant_id: string;
  product_id: string;
  status: string;
  start_at: string | null;
  end_at: string | null;
  modules: string[];
  max_users: number;
  tenure_months: number;
  currency: string;
  amount_paise: number;
  coupon_code: string | null;
  created_at: string;
  updated_at: string;
};

const configuredApiBase = (process.env.NEXT_PUBLIC_COREADMIN_API_BASE || "http://localhost:8000/api/v1").replace(/\/$/, "");

function resolveApiBase(): string {
  if (globalThis.window === undefined) {
    return configuredApiBase;
  }

  const host = globalThis.window.location.hostname;
  const isLocalhost = host === "localhost" || host === "127.0.0.1";
  if (!isLocalhost) {
    return configuredApiBase;
  }

  const configuredHost = (() => {
    try {
      return new URL(configuredApiBase).hostname;
    } catch {
      return "";
    }
  })();

  // For local frontend development, proxy remote API calls through Next.js to avoid CORS issues.
  if (configuredHost && configuredHost !== host && configuredHost !== "127.0.0.1") {
    return "/__coreadmin_api";
  }

  return configuredApiBase;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const apiBase = resolveApiBase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new Error("Cannot reach CoreAdmin API. Check API URL, backend status, and CORS settings.");
  }

  if (!response.ok) {
    let backendDetail = "";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) {
        backendDetail = payload.detail.trim();
      }
    } catch {
      backendDetail = "";
    }

    if (response.status === 401 || response.status === 403) {
      throw new Error(backendDetail || "You are not authorized to perform this action.");
    }
    if (response.status >= 500) {
      throw new Error("Service is temporarily unavailable. Please try again.");
    }
    throw new Error(backendDetail || "Request could not be completed.");
  }

  return (await response.json()) as T;
}

export function listProducts(token: string) {
  return request<ProductItem[]>("/products", { token });
}

export function createProduct(payload: ProductCreateInput, token: string) {
  return request<ProductItem>("/products", { method: "POST", token, body: payload });
}

export function updateProduct(productId: string, payload: ProductUpdateInput, token: string) {
  return request<ProductItem>(`/products/${productId}`, { method: "PATCH", token, body: payload });
}

export function deleteProduct(productId: string, token: string) {
  return request<{ id: string; deleted: boolean }>(`/products/${productId}`, { method: "DELETE", token });
}

export function listSubscriptions(token: string) {
  return request<AdminSubscription[]>("/admin/subscriptions", { token });
}

export function reconcileSubscription(subscriptionId: string, token: string) {
  return request<AdminSubscription>(`/admin/subscriptions/${subscriptionId}/reconcile`, {
    method: "POST",
    token,
  });
}

export function listCoupons(token: string) {
  return request<CouponItem[]>("/coupons", { token });
}

export function createCoupon(payload: CouponCreateInput, token: string) {
  return request<CouponItem>("/coupons", { method: "POST", token, body: payload });
}

export function pauseCoupon(couponId: string, token: string) {
  return request<CouponItem>(`/coupons/${couponId}/pause`, { method: "POST", token });
}

export function deleteCoupon(couponId: string, token: string) {
  return request<{ id: string; deleted: boolean }>(`/coupons/${couponId}`, { method: "DELETE", token });
}

export function listTenants(token: string) {
  return request<TenantItem[]>("/admin/tenants", { token });
}

export function createTenant(payload: TenantCreateInput, token: string) {
  return request<TenantItem>("/admin/tenants", { method: "POST", token, body: payload });
}

export function updateTenant(tenantId: string, payload: TenantUpdateInput, token: string) {
  return request<TenantItem>(`/admin/tenants/${tenantId}`, { method: "PATCH", token, body: payload });
}

export function getSuperAdminState(token: string) {
  return request<SuperAdminState>("/admin/super-admin", { token });
}

export function inviteSuperAdmin(invitee_email: string, token: string) {
  return request<{ invitation: SuperAdminInvitation; delivery_status: string }>("/admin/super-admin/invitations", {
    method: "POST",
    token,
    body: { invitee_email },
  });
}

export function getMySuperAdminInvitation(token: string) {
  return request<SuperAdminInvitation | null>("/admin/super-admin/invitations/me", { token });
}

export function acceptSuperAdminInvitation(invitationId: string, token: string) {
  return request<{ invitation: SuperAdminInvitation; current_super_admin: SuperAdminAssignment | null }>(
    `/admin/super-admin/invitations/${invitationId}/accept`,
    {
      method: "POST",
      token,
    },
  );
}

export function rejectSuperAdminInvitation(invitationId: string, token: string) {
  return request<{ invitation: SuperAdminInvitation; current_super_admin: SuperAdminAssignment | null }>(
    `/admin/super-admin/invitations/${invitationId}/reject`,
    {
      method: "POST",
      token,
    },
  );
}

export function cancelSuperAdminInvitation(invitationId: string, token: string) {
  return request<{ invitation: SuperAdminInvitation; current_super_admin: SuperAdminAssignment | null }>(
    `/admin/super-admin/invitations/${invitationId}/cancel`,
    {
      method: "POST",
      token,
    },
  );
}

export function resendSuperAdminInvitation(invitationId: string, token: string) {
  return request<{ invitation: SuperAdminInvitation; delivery_status: string }>(
    `/admin/super-admin/invitations/${invitationId}/resend`,
    {
      method: "POST",
      token,
    },
  );
}

export function getPortalAccessState(token: string) {
  return request<PortalAccessState>("/admin/access", { token });
}

export function invitePortalAccess(invitee_email: string, role: string, token: string) {
  return request<{ invitation: PortalAccessInvitation; delivery_status: string }>("/admin/access/invitations", {
    method: "POST",
    token,
    body: { invitee_email, role },
  });
}

export function invitePortalAccessWithScope(payload: PortalAccessInviteWithScopeInput, token: string) {
  return request<{ invitation: PortalAccessInvitation; delivery_status: string }>("/admin/access/invitations", {
    method: "POST",
    token,
    body: payload,
  });
}

export function getMyPortalAccessInvitation(token: string) {
  return request<PortalAccessInvitation | null>("/admin/access/invitations/me", { token });
}

export function acceptPortalAccessInvitation(invitationId: string, token: string) {
  return request<{ invitation: PortalAccessInvitation }>(`/admin/access/invitations/${invitationId}/accept`, {
    method: "POST",
    token,
  });
}

export function acceptPortalAccessInvitationByToken(portalToken: string, token: string) {
  return request<{ invitation: PortalAccessInvitation }>(`/admin/access/invitations/token/accept`, {
    method: "POST",
    token,
    body: { portal_token: portalToken },
  });
}

export function rejectPortalAccessInvitation(invitationId: string, token: string) {
  return request<{ invitation: PortalAccessInvitation }>(`/admin/access/invitations/${invitationId}/reject`, {
    method: "POST",
    token,
  });
}

export function rejectPortalAccessInvitationByToken(portalToken: string, token: string) {
  return request<{ invitation: PortalAccessInvitation }>(`/admin/access/invitations/token/reject`, {
    method: "POST",
    token,
    body: { portal_token: portalToken },
  });
}

export function cancelPortalAccessInvitation(invitationId: string, token: string) {
  return request<{ invitation: PortalAccessInvitation }>(`/admin/access/invitations/${invitationId}/cancel`, {
    method: "POST",
    token,
  });
}

export function resendPortalAccessInvitation(invitationId: string, token: string) {
  return request<{ invitation: PortalAccessInvitation; delivery_status: string }>(
    `/admin/access/invitations/${invitationId}/resend`,
    {
      method: "POST",
      token,
    },
  );
}

export function updatePortalOperatorAccess(
  uid: string,
  action: "set_admin" | "set_manager" | "remove_access",
  token: string,
  access_scope?: "product" | "coupon" | "advance_coupon" | "both" | "all" | null,
) {
  return request<{ uid: string; agent_number: string; role: string }>(`/admin/access/operators/${uid}`, {
    method: "PATCH",
    token,
    body: { action, access_scope: access_scope ?? null },
  });
}

export function createCheckoutIntent(payload: CheckoutIntentInput, token?: string) {
  return request<CheckoutIntentResult>("/checkout/intent", { method: "POST", token, body: payload });
}

export function confirmCheckout(payload: CheckoutConfirmInput, token?: string) {
  return request<CheckoutSubscription>("/checkout/confirm", { method: "POST", token, body: payload });
}