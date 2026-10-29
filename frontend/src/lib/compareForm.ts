import { z } from "zod";

import type { ComparisonRequest, ComparisonResponse } from "@/api/client";
import type { SelectedPlan } from "@/hooks/selection";

const money = z
  .string()
  .trim()
  .refine((v) => v === "" || (/^\d+(\.\d{1,2})?$/.test(v) && Number(v) <= 20000), "Enter an amount like 450 or 450.50");

const price = z
  .string()
  .trim()
  .refine((v) => v === "" || (/^\d+(\.\d{1,2})?$/.test(v) && Number(v) <= 1_000_000), "Enter a price from 0 to 1,000,000");

const age = z
  .string()
  .trim()
  .refine((v) => /^\d{1,3}$/.test(v) && Number(v) <= 120, "Enter an age from 0 to 120");

/** "cms": filled from the CMS rate table (refilled when details change); "user": typed by the user (kept). */
export type PremiumSource = "cms" | "user";

export const schema = z
  .object({
    base: z.string().min(1),
    plans: z.array(z.object({ documentId: z.string(), premium: money, hsa: money, premiumSource: z.enum(["cms", "user"]) })),
    coverage_tier: z.enum(["individual", "family"]),
    network: z.enum(["in_network", "out_of_network"]),
    scenario_ids: z.array(z.string()),
    custom: z.array(
      z.object({
        event: z.string().min(1, "Pick an event"),
        count: z.coerce.number().int().min(1, "At least 1").max(365, "At most 365"),
        member: z.coerce.number().int().min(0).max(9),
        fromText: z.string().optional(), // the words this row was interpreted from (natural-language intake)
      }),
    ),
    ages: z.array(z.object({ age })).min(1).max(10),
    ratingAreas: z.record(z.string(), z.string()),
    overrides: z.record(z.string(), price),
  })
  .refine((v) => v.scenario_ids.length > 0 || v.custom.length > 0, { message: "Pick at least one scenario or add your own events", path: ["scenario_ids"] });

export type FormValues = z.infer<typeof schema>; // after validation (counts are numbers)
export type FormInput = z.input<typeof schema>; // what the form fields hold

export const DEFAULT_AGE = "40";

export function defaultValues(items: SelectedPlan[]): FormInput {
  return {
    base: items[0]?.documentId ?? "",
    plans: items.map((i) => ({ documentId: i.documentId, premium: "", hsa: "", premiumSource: "cms" })),
    coverage_tier: "individual",
    network: "in_network",
    scenario_ids: ["low", "moderate", "high"],
    custom: [],
    ages: [{ age: DEFAULT_AGE }],
    ratingAreas: {},
    overrides: {},
  };
}

/** HIOS plan ids carry the state in characters 6-7 ("17933TX0010006-00" -> "TX"). */
export function planState(catalogPlanId: string | null | undefined): string | null {
  const m = catalogPlanId?.match(/^\d{5}([A-Z]{2})/);
  return m ? m[1] : null;
}

/** Ages that count for the selected coverage: one person for individual coverage. */
export function householdAges(v: Pick<FormInput, "ages" | "coverage_tier">): number[] {
  const all = v.ages
    .filter((a) => /^\d{1,3}$/.test(a.age.trim()))
    .map((a) => Number(a.age))
    .filter((a) => a <= 120);
  return v.coverage_tier === "family" ? all : all.slice(0, 1);
}

export type Quote = { monthly_total: number | null } | undefined;

/** New premium fields after CMS quotes arrive: user-typed premiums are kept; CMS ones follow the quotes. */
export function nextPremiums<P extends { premium: string; premiumSource: PremiumSource }>(plans: P[], quotes: Quote[]): P[] {
  return plans.map((p, i) => {
    if (p.premiumSource === "user") return p;
    const q = quotes[i];
    if (q === undefined) return p; // uploaded plan, or quote still loading
    return { ...p, premium: q.monthly_total === null ? "" : q.monthly_total.toFixed(2), premiumSource: "cms" };
  });
}

export function toRequest(v: FormValues): ComparisonRequest {
  const inputs: ComparisonRequest["inputs"] = {};
  for (const p of v.plans)
    inputs[p.documentId] = {
      monthly_premium: p.premium === "" ? null : Number(p.premium),
      employer_hsa_hra_annual: p.hsa === "" ? 0 : Number(p.hsa),
    };
  const family = v.coverage_tier === "family";
  const overrides = Object.fromEntries(Object.entries(v.overrides).filter(([, x]) => x !== "").map(([k, x]) => [k, Number(x)]));
  const hasDetails = Object.keys(v.ratingAreas).length > 0;
  return {
    document_ids: v.plans.map((p) => p.documentId),
    base_document_id: v.base,
    inputs,
    coverage_tier: v.coverage_tier,
    network: v.network,
    scenario_ids: v.scenario_ids,
    custom_scenario: v.custom.length
      ? { id: "custom", label: "Your usage", description: "The events you entered", events: v.custom.map((c) => ({ event: c.event, count: c.count, member: family ? c.member : 0 })) }
      : null,
    reference_price_overrides: overrides,
    explain: true,
    profile: hasDetails ? { ages: householdAges(v), rating_areas: v.ratingAreas } : null,
  };
}

/** The builder's selection and form for a stored comparison (the inverse of toRequest). */
export function fromComparison(c: ComparisonResponse): { items: SelectedPlan[]; values: FormInput } {
  const req = c.request;
  const plans = c.result.plans;
  const items: SelectedPlan[] = req.document_ids.map((id) => {
    const p = plans.find((x) => x.document_id === id);
    return {
      documentId: id,
      label: p?.plan_name ?? "Plan",
      source: p?.catalog_plan_id ? "catalog" : "upload",
      catalogPlanId: p?.catalog_plan_id ?? null,
      issuer: p?.issuer ?? null,
    };
  });
  const str = (n: number | null | undefined) => (n === null || n === undefined ? "" : String(n));
  const ages = req.profile?.ages?.length ? req.profile.ages : [Number(DEFAULT_AGE)];
  return {
    items,
    values: {
      base: req.base_document_id ?? req.document_ids[0],
      plans: req.document_ids.map((id) => {
        const i = req.inputs?.[id];
        // premiums are restored as typed values so a re-run reproduces the stored result exactly
        return { documentId: id, premium: str(i?.monthly_premium), hsa: i?.employer_hsa_hra_annual ? str(i.employer_hsa_hra_annual) : "", premiumSource: "user" };
      }),
      coverage_tier: req.coverage_tier ?? "individual",
      network: req.network ?? "in_network",
      scenario_ids: req.scenario_ids ?? [],
      custom: (req.custom_scenario?.events ?? []).map((e) => ({ event: e.event, count: e.count ?? 1, member: e.member ?? 0 })),
      ages: ages.map((a) => ({ age: String(a) })),
      ratingAreas: req.profile?.rating_areas ?? {},
      overrides: Object.fromEntries(Object.entries(req.reference_price_overrides ?? {}).map(([k, x]) => [k, String(x)])),
    },
  };
}
