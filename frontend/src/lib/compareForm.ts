import { z } from "zod";

import type { ComparisonRequest } from "@/api/client";

const money = z
  .string()
  .trim()
  .refine((v) => v === "" || (/^\d+(\.\d{1,2})?$/.test(v) && Number(v) <= 20000), "Enter an amount like 450 or 450.50");

export const schema = z
  .object({
    base: z.string().min(1),
    plans: z.array(z.object({ documentId: z.string(), premium: money, hsa: money })),
    coverage_tier: z.enum(["individual", "family"]),
    network: z.enum(["in_network", "out_of_network"]),
    scenario_ids: z.array(z.string()),
    custom: z.array(z.object({ event: z.string().min(1, "Pick an event"), count: z.coerce.number().int().min(1, "At least 1").max(365, "At most 365") })),
  })
  .refine((v) => v.scenario_ids.length > 0 || v.custom.length > 0, { message: "Pick at least one scenario or add your own events", path: ["scenario_ids"] });

export type FormValues = z.infer<typeof schema>;

export function toRequest(v: FormValues): ComparisonRequest {
  const inputs: ComparisonRequest["inputs"] = {};
  for (const p of v.plans)
    inputs[p.documentId] = {
      monthly_premium: p.premium === "" ? null : Number(p.premium),
      employer_hsa_hra_annual: p.hsa === "" ? 0 : Number(p.hsa),
    };
  return {
    document_ids: v.plans.map((p) => p.documentId),
    base_document_id: v.base,
    inputs,
    coverage_tier: v.coverage_tier,
    network: v.network,
    scenario_ids: v.scenario_ids,
    custom_scenario: v.custom.length ? { id: "custom", label: "Your usage", description: "The events you entered", events: v.custom.map((c) => ({ event: c.event, count: c.count, member: 0 })) } : null,
    reference_price_overrides: {},
    explain: true,
  };
}

