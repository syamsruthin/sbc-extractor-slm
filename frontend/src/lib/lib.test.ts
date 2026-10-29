import { describe, expect, it } from "vitest";

import type { ComparisonResponse } from "@/api/client";
import fixtureF1 from "@/test/fixtures/comparison_f1.json";

import { fromComparison, householdAges, nextPremiums, planState, schema, toRequest } from "./compareForm";
import { describeCost, money, range, signedRange } from "./format";
import { rejectionMessage } from "./upload";

describe("format", () => {
  it("formats money and ranges", () => {
    expect(money(1500)).toBe("$1,500");
    expect(money(12.5)).toBe("$12.50");
    expect(money(null)).toBe("—");
    expect(range({ low: 6848, high: 7840 })).toBe("$6,848 – $7,840");
    expect(range({ low: 7310, high: 7310 })).toBe("$7,310");
    expect(signedRange({ low: -530, high: 462 })).toBe("−$530 to +$462");
  });
  it("describes cost sharing like the backend", () => {
    expect(describeCost({ covered: true, copay: 0, coinsurance_pct: 0, deductible_applies: null, note: null })).toBe("No charge");
    expect(describeCost({ covered: true, copay: 250, coinsurance_pct: 20, deductible_applies: null, note: null })).toBe("$250 copay then 20% coinsurance");
    expect(describeCost({ covered: false, copay: null, coinsurance_pct: null, deductible_applies: null, note: null })).toBe("Not covered");
  });
});

describe("compare form", () => {
  const base = {
    base: "a",
    plans: [
      { documentId: "a", premium: "500", hsa: "", premiumSource: "user" as const },
      { documentId: "b", premium: "", hsa: "500", premiumSource: "cms" as const },
    ],
    coverage_tier: "individual" as const,
    network: "in_network" as const,
    scenario_ids: ["low"],
    custom: [] as { event: string; count: number | string; member: number | string }[],
    ages: [{ age: "40" }],
    ratingAreas: {} as Record<string, string>,
    overrides: {} as Record<string, string>,
  };
  it("accepts valid input and builds the API request", () => {
    const v = schema.parse(base);
    const req = toRequest(v);
    expect(req.document_ids).toEqual(["a", "b"]);
    expect(req.inputs?.a).toEqual({ monthly_premium: 500, employer_hsa_hra_annual: 0 });
    expect(req.inputs?.b).toEqual({ monthly_premium: null, employer_hsa_hra_annual: 500 });
    expect(req.custom_scenario).toBeNull();
    expect(req.reference_price_overrides).toEqual({});
    expect(req.profile).toBeNull();
  });
  it("rejects bad amounts, empty scenarios and bad counts", () => {
    expect(schema.safeParse({ ...base, plans: [{ documentId: "a", premium: "abc", hsa: "", premiumSource: "user" }] }).success).toBe(false);
    expect(schema.safeParse({ ...base, ages: [{ age: "130" }] }).success).toBe(false);
    expect(schema.safeParse({ ...base, overrides: { imaging: "-1" } }).success).toBe(false);
    expect(schema.safeParse({ ...base, scenario_ids: [] }).success).toBe(false);
    expect(schema.safeParse({ ...base, custom: [{ event: "mri", count: 0, member: 0 }] }).success).toBe(false);
    const ok = schema.parse({ ...base, scenario_ids: [], custom: [{ event: "mri", count: "2", member: "1" }] });
    // individual coverage: every event is the one member's
    expect(toRequest(ok).custom_scenario?.events[0]).toEqual({ event: "mri", count: 2, member: 0 });
  });

  it("sends members, household details and changed prices", () => {
    const v = schema.parse({
      ...base,
      coverage_tier: "family",
      custom: [{ event: "mri", count: "1", member: "1" }],
      ages: [{ age: "40" }, { age: "8" }],
      ratingAreas: { TX: "Rating Area 3" },
      overrides: { imaging: "1800", specialist_visit: "" },
    });
    const req = toRequest(v);
    expect(req.custom_scenario?.events[0]).toEqual({ event: "mri", count: 1, member: 1 });
    expect(req.profile).toEqual({ ages: [40, 8], rating_areas: { TX: "Rating Area 3" } });
    expect(req.reference_price_overrides).toEqual({ imaging: 1800 });
  });

  it("uses one age for individual coverage", () => {
    expect(householdAges({ ages: [{ age: "40" }, { age: "8" }], coverage_tier: "individual" })).toEqual([40]);
    expect(householdAges({ ages: [{ age: "40" }, { age: "" }], coverage_tier: "family" })).toEqual([40]);
  });

  it("reads the state from a HIOS plan id", () => {
    expect(planState("17933TX0010006-00")).toBe("TX");
    expect(planState(null)).toBeNull();
  });

  it("fills CMS premiums but keeps typed ones", () => {
    const plans = [
      { documentId: "a", premium: "", hsa: "", premiumSource: "cms" as const },
      { documentId: "b", premium: "300", hsa: "", premiumSource: "user" as const },
      { documentId: "c", premium: "450.00", hsa: "", premiumSource: "cms" as const },
      { documentId: "d", premium: "", hsa: "", premiumSource: "cms" as const },
    ];
    const next = nextPremiums(plans, [{ monthly_total: 553.37 }, { monthly_total: 1 }, { monthly_total: null }, undefined]);
    expect(next.map((p) => p.premium)).toEqual(["553.37", "300", "", ""]);
  });

  it("restores a stored comparison so the same request is sent again", () => {
    const c = fixtureF1 as unknown as ComparisonResponse;
    const { items, values } = fromComparison(c);
    expect(items.map((i) => i.source)).toEqual(["catalog", "catalog"]);
    expect(items[0].catalogPlanId).toBe("17933TX0010006-00");
    const req = toRequest(schema.parse(values));
    expect(req.document_ids).toEqual(c.request.document_ids);
    expect(req.inputs).toEqual(c.request.inputs);
    expect(req.scenario_ids).toEqual(c.request.scenario_ids);
    expect(req.coverage_tier).toBe(c.request.coverage_tier);
    expect(req.reference_price_overrides).toEqual(c.request.reference_price_overrides);
  });
});

describe("upload validation", () => {
  it("explains rejected files", () => {
    const file = new File(["x"], "plan.docx");
    expect(rejectionMessage({ file, errors: [{ code: "file-invalid-type", message: "" }] })).toBe("plan.docx isn't a PDF.");
    expect(rejectionMessage({ file, errors: [{ code: "file-too-large", message: "" }] })).toMatch(/larger than 10 MB/);
  });
});
