type CouponModeSource = {
  exclusive_for_tenant_id: string | null;
  override_tenure_months: number | null;
  override_max_users: number | null;
  override_modules: string[] | null;
};

export function isAdvanceCoupon(item: Partial<CouponModeSource>): boolean {
  return Boolean(
    item.exclusive_for_tenant_id
      || item.override_tenure_months != null
      || item.override_max_users != null
      || (item.override_modules && item.override_modules.length > 0),
  );
}
