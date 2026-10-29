import { zodResolver } from "@hookform/resolvers/zod";
import { useQueries } from "@tanstack/react-query";
import { Plus, Scale, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "@/api/client";
import { PricesPanel } from "@/components/PricesPanel";
import { UsageDescribe } from "@/components/UsageDescribe";
import { Badge, Button, Card, EmptyState, Field, PageHeader, Skeleton, inputClass } from "@/components/ui";
import { useComparison, useCreateComparison, useFacets, useHealth, useScenarios } from "@/hooks/api";
import { useSelection } from "@/hooks/selection";
import {
  defaultValues,
  fromComparison,
  householdAges,
  nextPremiums,
  planState,
  schema,
  toRequest,
  type FormInput,
  type FormValues,
  type Quote,
} from "@/lib/compareForm";

export function CompareBuilderPage() {
  const { items, remove, replace } = useSelection();
  const scenarios = useScenarios();
  const facets = useFacets();
  const health = useHealth();
  const create = useCreateComparison();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const from = params.get("from") ?? undefined;
  const restoring = useComparison(from);
  const restored = useRef<string | null>(null);
  const pendingTray = useRef<string | null>(null); // restored plan ids until the tray has caught up

  // When the comparison is already cached (arriving from its result page) the form starts from it: resetting it in a
  // mount effect is undone by react-hook-form re-applying defaultValues on StrictMode's remount.
  const cached = from && restoring.data ? fromComparison(restoring.data) : null;
  const form = useForm<FormInput, unknown, FormValues>({
    resolver: zodResolver(schema),
    defaultValues: cached?.values ?? defaultValues(items),
  });
  const { register, handleSubmit, formState, setValue, watch, getValues, reset } = form;
  const custom = useFieldArray({ control: form.control, name: "custom" });
  const ages = useFieldArray({ control: form.control, name: "ages" });

  // "Change inputs" on a result: restore its plans and every input once
  useEffect(() => {
    if (!from || !restoring.data || restored.current === from) return;
    restored.current = from;
    const { items: restoredItems, values } = fromComparison(restoring.data);
    pendingTray.current = restoredItems.map((i) => i.documentId).join();
    replace(restoredItems);
    reset(values);
  }, [from, restoring.data, replace, reset]);

  // keep the form in sync with the selection tray (not while it still holds the plans from before a restore)
  useEffect(() => {
    if (pendingTray.current !== null) {
      if (items.map((i) => i.documentId).join() !== pendingTray.current) return;
      pendingTray.current = null;
    }
    const prev = getValues("plans");
    const next = items.map(
      (i) => prev.find((p) => p.documentId === i.documentId) ?? { documentId: i.documentId, premium: "", hsa: "", premiumSource: "cms" as const },
    );
    if (JSON.stringify(next) !== JSON.stringify(prev)) setValue("plans", next);
    if (!items.some((i) => i.documentId === getValues("base"))) setValue("base", items[0]?.documentId ?? "");
  }, [items, getValues, setValue]);

  // CMS premiums: one rating area per state of the selected catalog plans
  const catalogItems = items.filter((i) => i.catalogPlanId);
  const states = [...new Set(catalogItems.map((i) => planState(i.catalogPlanId)).filter((s): s is string => !!s))].sort();
  const showDetails = catalogItems.length > 0 && !!facets.data?.premiums_loaded;
  const areaQueries = useQueries({
    queries: states.map((s) => ({ queryKey: ["rating-areas", s], queryFn: () => api.ratingAreas(s), enabled: showDetails, staleTime: Infinity })),
  });

  // default rating area: the first one where a selected plan in that state is sold (what the builder used before)
  useEffect(() => {
    if (!showDetails) return;
    for (const s of states) {
      if (getValues(`ratingAreas.${s}`)) continue;
      const first = catalogItems.find((i) => planState(i.catalogPlanId) === s);
      if (!first?.catalogPlanId) continue;
      api
        .premiums(first.catalogPlanId, "40")
        .then((q) => {
          if (q.items[0] && !getValues(`ratingAreas.${s}`)) setValue(`ratingAreas.${s}`, q.items[0].rating_area);
        })
        .catch(() => undefined);
    }
  }, [showDetails, states.join(), catalogItems, getValues, setValue]); // eslint-disable-line react-hooks/exhaustive-deps

  const tier = watch("coverage_tier");
  const ageValues = watch("ages");
  const areas = watch("ratingAreas");
  const hhAges = householdAges({ ages: ageValues, coverage_tier: tier });
  const quoteQueries = useQueries({
    queries: items.map((i) => {
      const area = areas[planState(i.catalogPlanId) ?? ""];
      return {
        queryKey: ["premium-quote", i.documentId, i.catalogPlanId, area, hhAges.join(",")],
        queryFn: () => api.premiumQuote(i.catalogPlanId!, area!, hhAges),
        enabled: showDetails && !!i.catalogPlanId && !!area && hhAges.length > 0,
        staleTime: Infinity,
      };
    }),
  });
  const quotes: Quote[] = items.map((i, idx) => (i.catalogPlanId ? quoteQueries[idx]?.data : undefined));
  const quoteKey = quotes.map((q) => (q === undefined ? "-" : String(q.monthly_total))).join("|");
  useEffect(() => {
    const prev = getValues("plans");
    const next = nextPremiums(prev, quotes);
    if (JSON.stringify(next) !== JSON.stringify(prev)) setValue("plans", next);
  }, [quoteKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const memberLabels = useMemo(
    () => ageValues.map((a, i) => (i === 0 ? `You${a.age ? ` (${a.age})` : ""}` : `Member ${i + 1}${a.age ? ` (${a.age})` : ""}`)),
    [ageValues],
  );

  if (from && (restoring.isLoading || restored.current !== from) && !restoring.isError)
    return (
      <div className="space-y-6">
        <PageHeader title="Compare plans" />
        <Skeleton className="h-64" />
      </div>
    );

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

  const onSubmit = handleSubmit((v) => create.mutate(toRequest(v), { onSuccess: (c) => nav(`/comparisons/${c.id}`) }));
  const chosen = watch("scenario_ids");
  const plans = watch("plans");
  const eventTypes = Object.entries(scenarios.data?.event_types ?? {});
  const family = tier === "family";

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      <PageHeader
        title="Compare plans"
        subtitle="Add premiums so totals reflect what you'd really pay, choose how much care to plan for, then compare."
        actions={<Button type="submit" loading={create.isPending}><Scale className="h-4 w-4" /> Compare {items.length} plans</Button>}
      />

      {showDetails && (
        <Card className="space-y-4 p-5">
          <div>
            <h2 className="mb-1 font-semibold">Your details</h2>
            <p className="text-sm text-slate-500">
              Marketplace premiums depend on age and where you live. We use them to fill in premiums for catalog plans; you can still type your own.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              {ages.fields.slice(0, family ? 10 : 1).map((f, i) => (
                <div key={f.id} className="flex items-end gap-2">
                  <Field label={i === 0 ? "Your age" : `Member ${i + 1} age`} error={formState.errors.ages?.[i]?.age?.message}>
                    <input inputMode="numeric" className={`${inputClass} w-28`} aria-label={i === 0 ? "Your age" : `Member ${i + 1} age`} {...register(`ages.${i}.age`)} />
                  </Field>
                  {i > 0 && (
                    <Button type="button" variant="danger" size="sm" aria-label={`Remove member ${i + 1}`} onClick={() => removeMember(i)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
              {family && ages.fields.length < 10 && (
                <Button type="button" variant="secondary" size="sm" onClick={() => ages.append({ age: "" })}>
                  <Plus className="h-4 w-4" /> Add family member
                </Button>
              )}
              {family && <p className="text-xs text-slate-500">Only the 3 oldest children under 21 count toward a family premium.</p>}
            </div>
            <div className="space-y-2">
              {states.map((s, idx) => {
                const opts = areaQueries[idx]?.data?.items ?? [];
                return (
                  <Field key={s} label={`Rating area (${s})`} hint="Premiums vary by rating area; your state's marketplace lists yours.">
                    <select
                      className={inputClass}
                      aria-label={`Rating area for ${s}`}
                      value={areas[s] ?? ""}
                      onChange={(e) => setValue(`ratingAreas.${s}`, e.target.value, { shouldDirty: true })}
                    >
                      <option value="">Choose…</option>
                      {areas[s] && !opts.some((o) => o.rating_area === areas[s]) && <option value={areas[s]}>{areas[s]}</option>}
                      {opts.map((o) => (
                        <option key={o.rating_area} value={o.rating_area}>
                          {o.rating_area} ({o.plans_priced} plans)
                        </option>
                      ))}
                    </select>
                  </Field>
                );
              })}
            </div>
          </div>
        </Card>
      )}

      <Card className="p-5">
        <h2 className="mb-1 font-semibold">Plans and premiums</h2>
        <p className="mb-4 text-sm text-slate-500">Premiums aren't in the SBC. Enter the monthly amount you'd pay (after any subsidy or employer share). Leave blank to compare benefits only.</p>
        <div className="divide-y divide-slate-100">
          {items.map((it, idx) => {
            const p = plans[idx];
            const q = quotes[idx];
            const hint =
              it.catalogPlanId && p?.premiumSource === "cms"
                ? q && q.monthly_total === null
                  ? "Not priced in this rating area. Enter it yourself."
                  : p.premium
                    ? "CMS 2026 rate, before subsidy"
                    : undefined
                : undefined;
            return (
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
                <Field label="Monthly premium" hint={hint} error={formState.errors.plans?.[idx]?.premium?.message}>
                  <input
                    inputMode="decimal"
                    placeholder="e.g. 450"
                    className={inputClass}
                    aria-label={`Monthly premium for ${it.label}`}
                    {...register(`plans.${idx}.premium`, { onChange: () => setValue(`plans.${idx}.premiumSource`, "user") })}
                  />
                </Field>
                <Field label="Employer HSA/HRA per year" error={formState.errors.plans?.[idx]?.hsa?.message}>
                  <input inputMode="decimal" placeholder="0" className={inputClass} aria-label={`Employer contribution for ${it.label}`} {...register(`plans.${idx}.hsa`)} />
                </Field>
                <Button type="button" variant="danger" size="sm" className="mt-6" aria-label={`Remove ${it.label}`} onClick={() => remove(it.documentId)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            );
          })}
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
                {family && (
                  <select aria-label="Who" className={`${inputClass} w-40`} {...register(`custom.${i}.member`)}>
                    {memberLabels.map((label, m) => (
                      <option key={m} value={m}>{label}</option>
                    ))}
                  </select>
                )}
                {f.fromText && <Badge tone="violet" title={`From: "${f.fromText}"`}>from your description</Badge>}
                <Button type="button" variant="danger" size="sm" aria-label="Remove event" onClick={() => custom.remove(i)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
                {(formState.errors.custom?.[i]?.event || formState.errors.custom?.[i]?.count) && (
                  <span className="w-full text-xs text-red-600">{formState.errors.custom?.[i]?.event?.message ?? formState.errors.custom?.[i]?.count?.message}</span>
                )}
              </div>
            ))}
          </div>
          <Button type="button" variant="secondary" size="sm" className="mt-2" onClick={() => custom.append({ event: "", count: 1, member: 0 })}>
            <Plus className="h-4 w-4" /> Add event
          </Button>
        </div>

        {health.data?.intake_available && (
          <UsageDescribe
            coverageTier={tier}
            members={memberLabels}
            onEvents={(evs) => custom.append(evs.map((e) => ({ event: e.event, count: e.count, member: family ? e.member : 0, fromText: e.quote })))}
          />
        )}
      </Card>

      <PricesPanel register={register} setValue={setValue} overrides={watch("overrides")} errors={formState.errors.overrides} />

      <div className="flex flex-wrap items-center justify-end gap-4">
        <p className="flex-1 text-xs text-slate-500">
          The comparison is saved on this computer with the premiums, ages and usage above, so you can reopen it. Delete it any time under{" "}
          <Link className="underline" to="/comparisons">Saved</Link>.
        </p>
        <Button type="submit" loading={create.isPending}><Scale className="h-4 w-4" /> Compare {items.length} plans</Button>
      </div>
    </form>
  );

  function removeMember(i: number) {
    ages.remove(i);
    const rows = getValues("custom");
    rows.forEach((r, j) => {
      const m = Number(r.member);
      if (m === i) setValue(`custom.${j}.member`, 0);
      else if (m > i) setValue(`custom.${j}.member`, m - 1);
    });
  }
}
