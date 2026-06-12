import { describe, expect, it } from "vitest";

import { isAdvanceCoupon } from "./coupon-mode";

describe("isAdvanceCoupon", () => {
  it("returns false for normal coupons with undefined override fields", () => {
    expect(
      isAdvanceCoupon({
        exclusive_for_tenant_id: null,
        override_tenure_months: undefined,
        override_max_users: undefined,
        override_modules: undefined,
      }),
    ).toBe(false);
  });

  it("returns true when tenant restriction is present", () => {
    expect(
      isAdvanceCoupon({
        exclusive_for_tenant_id: "tenant_123",
      }),
    ).toBe(true);
  });

  it("returns true when any override is present", () => {
    expect(isAdvanceCoupon({ override_tenure_months: 1 })).toBe(true);
    expect(isAdvanceCoupon({ override_max_users: 10 })).toBe(true);
    expect(isAdvanceCoupon({ override_modules: ["execution"] })).toBe(true);
  });
});
