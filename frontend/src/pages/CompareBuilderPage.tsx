import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Scale, Trash2 } from "lucide-react";
import { useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { Badge, Button, Card, EmptyState, Field, PageHeader, inputClass } from "@/components/ui";
import { useCreateComparison, useScenarios } from "@/hooks/api";
import { useSelection } from "@/hooks/selection";
import { schema, toRequest, type FormValues } from "@/lib/compareForm";

export function CompareBuilderPage() {
  const { items, remove } = useSelection();
  const scenarios = useScenarios();
  const create = useCreateComparison();
  const nav = useNavigate();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      base: items[0]?.documentId ?? "",
      plans: items.map((i) => ({ documentId: i.documentId, premium: "", hsa: "" })),
      coverage_tier: "individual",
      network: "in_network",
      scenario_ids: ["low", "moderate", "high"],
      custom: [],
    },
  });
  const { register, handleSubmit, formState, setValue, watch, getValues } = form;
  const custom = useFieldArray({ control: form.control, name: "custom" });

  // keep the form in sync with the selection tray
  useEffect(() => {
    const prev = getValues("plans");
    setValue("plans", items.map((i) => prev.find((p) => p.documentId === i.documentId) ?? { documentId: i.documentId, premium: "", hsa: "" }));
    if (!items.some((i) => i.documentId === getValues("base"))) setValue("base", items[0]?.documentId ?? "");
  }, [items, getValues, setValue]);

  // prefill catalog premiums (age 40, first rating area) when the Rate PUF is loaded
  useEffect(() => {
    items.forEach((it, idx) => {
      if (!it.catalogPlanId) return;
      api.premiums(it.catalogPlanId, "40").then((q) => {
        const first = q.items[0];
        if (first && getValues(`plans.${idx}.premium`) === "") setValue(`plans.${idx}.premium`, first.monthly_premium.toFixed(2));
      }).catch(() => undefined);
    });
  }, [items, getValues, setValue]);

  if (items.length < 2)
    return (
      <div className="space-y-6">
        <PageHeader title="Compare plans" />
        <EmptyState icon={<Scale className="h-8 w-8" />} title={items.length ? "Pick one more plan" : "Pick at least two plans"}>
          Select plans from <Link className="text-brand-600 underline" to="/">My plans</Link> or the{" "}
          <Link className="text-brand-600 underline" to="/catalog">marketplace catalog</Link>. You can compare up to 5.
        </EmptyState>
      </div>
    );

  const onSubmit = handleSubmit((v) =>
    create.mutate(toRequest(v), { onSuccess: (c) => nav(`/comparisons/${c.id}`) }),
  );
  const chosen = watch("scenario_ids");
  const eventTypes = Object.entries(scenarios.data?.event_types ?? {});

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <PageHeader
        title="Compare plans"
        subtitle="Add premiums so totals reflect what you'd really pay, choose how much care to plan for, then compare."
        actions={<Button type="submit" loading={create.isPending}><Scale className="h-4 w-4" /> Compare {items.length} plans</Button>}
      />
      <Card className="p-5">
        <h2 className="mb-1 font-semibold">Plans and premiums</h2>
        <p className="mb-4 text-sm text-slate-500">Premiums aren't in the SBC. Enter the monthly amount you'd pay (after any subsidy or employer share). Leave blank to compare benefits only.</p>
        <div className="divide-y divide-slate-100">
          {items.map((it, idx) => (
            <div key={it.documentId} className="grid items-start gap-4 py-4 md:grid-cols-[1fr_10rem_12rem_auto]">
              <div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" value={it.documentId} {...register("base")} className="h-4 w-4 text-brand-600" />
                  <span className="font-medium text-slate-900">{it.label}</span>
                </label>
                <div className="ml-6 mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                  {it.issuer && <span>{it.issuer}</span>}
                  <Badge tone={it.source === "catalog" ? "violet" : "gray"}>{it.source === "catalog" ? "Catalog" : "Uploaded"}</Badge>
                  {watch("base") === it.documentId && <Badge tone="blue">Base plan</Badge>}
                </div>
              </div>
              <Field label="Monthly premium" error={formState.errors.plans?.[idx]?.premium?.message}>
                <input inputMode="decimal" placeholder="e.g. 450" className={inputClass} aria-label={`Monthly premium for ${it.label}`} {...register(`plans.${idx}.premium`)} />
              </Field>
              <Field label="Employer HSA/HRA per year" error={formState.errors.plans?.[idx]?.hsa?.message}>
                <input inputMode="decimal" placeholder="0" className={inputClass} aria-label={`Employer contribution for ${it.label}`} {...register(`plans.${idx}.hsa`)} />
              </Field>
              <Button type="button" variant="danger" size="sm" className="mt-6" aria-label={`Remove ${it.label}`} onClick={() => remove(it.documentId)}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-500">The base plan is the one others are compared against (usually your current plan).</p>
      </Card>

      <Card className="grid gap-4 p-5 sm:grid-cols-2">
        <Field label="Coverage">
          <select className={inputClass} {...register("coverage_tier")}>
            <option value="individual">Just me (individual)</option>
            <option value="family">Family</option>
          </select>
        </Field>
        <Field label="Network" hint="Out-of-network estimates exclude balance billing.">
          <select className={inputClass} {...register("network")}>
            <option value="in_network">In-network care</option>
            <option value="out_of_network">Out-of-network care</option>
          </select>
        </Field>
      </Card>

      <Card className="p-5">
        <h2 className="mb-1 font-semibold">How much care to plan for</h2>
        <p className="mb-4 text-sm text-slate-500">Each scenario is a year of care priced with reference costs. Pick any, and add your own.</p>
        <div className="grid gap-3 md:grid-cols-2">
          {scenarios.data?.presets.map((p) => (
            <label key={p.id} className={`flex cursor-pointer gap-3 rounded-lg border p-3 text-sm ${chosen.includes(p.id) ? "border-brand-500 bg-brand-50/50" : "border-slate-200"}`}>
              <input type="checkbox" value={p.id} {...register("scenario_ids")} className="mt-0.5 h-4 w-4" />
              <span>
                <span className="font-medium text-slate-900">{p.label}</span>
                <span className="block text-slate-500">{p.description}</span>
              </span>
            </label>
          ))}
        </div>
        {formState.errors.scenario_ids && <p className="mt-2 text-sm text-red-600">{formState.errors.scenario_ids.message}</p>}

        <div className="mt-6">
          <h3 className="text-sm font-medium text-slate-800">Your own usage (optional)</h3>
          <div className="mt-2 space-y-2">
            {custom.fields.map((f, i) => (
              <div key={f.id} className="flex flex-wrap items-start gap-2">
                <select aria-label="Event" className={`${inputClass} max-w-xs`} {...register(`custom.${i}.event`)}>
                  <option value="">Choose an event…</option>
                  {eventTypes.map(([k, v]) => (
                    <option key={k} value={k}>{String(v.label ?? k)}</option>
                  ))}
                </select>
                <input aria-label="Times per year" type="number" min={1} max={365} className={`${inputClass} w-28`} {...register(`custom.${i}.count`)} />
                <span className="py-2 text-sm text-slate-500">times a year</span>
                <Button type="button" variant="danger" size="sm" aria-label="Remove event" onClick={() => custom.remove(i)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
                {(formState.errors.custom?.[i]?.event || formState.errors.custom?.[i]?.count) && (
                  <span className="w-full text-xs text-red-600">{formState.errors.custom?.[i]?.event?.message ?? formState.errors.custom?.[i]?.count?.message}</span>
                )}
              </div>
            ))}
          </div>
          <Button type="button" variant="secondary" size="sm" className="mt-2" onClick={() => custom.append({ event: "", count: 1 })}>
            <Plus className="h-4 w-4" /> Add event
          </Button>
        </div>
      </Card>

      <div className="flex justify-end">
        <Button type="submit" loading={create.isPending}><Scale className="h-4 w-4" /> Compare {items.length} plans</Button>
      </div>
    </form>
  );
}
