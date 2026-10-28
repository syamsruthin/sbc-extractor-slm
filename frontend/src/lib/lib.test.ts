import { describe, expect, it } from "vitest";

import { schema, toRequest } from "./compareForm";
import { deductibleNote, describeCost, money, range, signedRange } from "./format";
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
    plans: [{ documentId: "a", premium: "500", hsa: "" }, { documentId: "b", premium: "", hsa: "500" }],
    coverage_tier: "individual" as const,
    network: "in_network" as const,
    scenario_ids: ["low"],
    custom: [],
  };
  it("accepts valid input and builds the API request", () => {
    const v = schema.parse(base);
    const req = toRequest(v);
    expect(req.document_ids).toEqual(["a", "b"]);
    expect(req.inputs?.a).toEqual({ monthly_premium: 500, employer_hsa_hra_annual: 0 });
    expect(req.inputs?.b).toEqual({ monthly_premium: null, employer_hsa_hra_annual: 500 });
    expect(req.custom_scenario).toBeNull();
  });
  it("rejects bad amounts, empty scenarios and bad counts", () => {
    expect(schema.safeParse({ ...base, plans: [{ documentId: "a", premium: "abc", hsa: "" }] }).success).toBe(false);
    expect(schema.safeParse({ ...base, scenario_ids: [] }).success).toBe(false);
    expect(schema.safeParse({ ...base, custom: [{ event: "mri", count: 0 }] }).success).toBe(false);
    const ok = schema.parse({ ...base, scenario_ids: [], custom: [{ event: "mri", count: "2" }] });
    expect(toRequest(ok).custom_scenario?.events[0]).toEqual({ event: "mri", count: 2, member: 0 });
  });
});

describe("upload validation", () => {
  it("explains rejected files", () => {
    const file = new File(["x"], "plan.docx");
    expect(rejectionMessage({ file, errors: [{ code: "file-invalid-type", message: "" }] })).toBe("plan.docx isn't a PDF.");
    expect(rejectionMessage({ file, errors: [{ code: "file-too-large", message: "" }] })).toMatch(/larger than 10 MB/);
  });
});

describe("deductible note", () => {
  const c = { covered: true, copay: 0, coinsurance_pct: 0, deductible_applies: null, note: null };
  it("says 'not stated' instead of implying no deductible", () => {
    expect(deductibleNote(c, true)).toBe("deductible not stated");
    expect(deductibleNote(c, false)).toBeNull();
    expect(deductibleNote({ ...c, deductible_applies: true }, true)).toBe("after deductible");
  });
});
