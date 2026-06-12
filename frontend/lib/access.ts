export type Claims = Record<string, unknown>;

function lower(value: unknown): string {
  return typeof value === "string" ? value.toLowerCase() : "";
}

export function decodeTokenClaims(token: string | null): Claims {
  if (!token) return {};
  try {
    const payload = token.split(".")[1];
    if (!payload) return {};
    const normalized = payload.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as Claims;
  } catch {
    return {};
  }
}

function roleSet(claims: Claims): Set<string> {
  const roles = new Set<string>();
  const role = lower(claims.role);
  if (role) roles.add(role);
  if (Array.isArray(claims.roles)) {
    for (const item of claims.roles) {
      const value = lower(item);
      if (value) roles.add(value);
    }
  }
  return roles;
}

function permissionSet(claims: Claims): Set<string> {
  const permissions = new Set<string>();
  if (Array.isArray(claims.portal_permissions)) {
    for (const item of claims.portal_permissions) {
      const value = lower(item);
      if (value) permissions.add(value);
    }
  }

  const roles = roleSet(claims);
  if (roles.has("super_admin")) {
    permissions.add("products");
    permissions.add("coupons");
    permissions.add("advance_coupons");
    permissions.add("users");
  }

  return permissions;
}

export function hasProductModuleAccess(claims: Claims): boolean {
  return permissionSet(claims).has("products");
}

export function hasCouponModuleAccess(claims: Claims): boolean {
  return permissionSet(claims).has("coupons");
}

export function hasAdvanceCouponModuleAccess(claims: Claims): boolean {
  const permissions = permissionSet(claims);
  return permissions.has("advance_coupons") && permissions.has("coupons");
}

export function hasUsersAccess(claims: Claims): boolean {
  return permissionSet(claims).has("users");
}

export function isRouteAllowedByClaims(pathname: string, claims: Claims): boolean {
  if (pathname.startsWith("/products")) {
    return hasProductModuleAccess(claims);
  }
  if (pathname.startsWith("/coupons/advance")) {
    return hasAdvanceCouponModuleAccess(claims);
  }
  if (pathname.startsWith("/coupons")) {
    return hasCouponModuleAccess(claims);
  }
  if (pathname.startsWith("/users")) {
    return hasUsersAccess(claims);
  }
  return true;
}

export function getFirstAccessibleRoute(claims: Claims): string {
  if (hasProductModuleAccess(claims)) return "/products";
  if (hasCouponModuleAccess(claims)) return "/coupons";
  if (hasAdvanceCouponModuleAccess(claims)) return "/coupons/advance";
  if (hasUsersAccess(claims)) return "/users";
  return "/";
}