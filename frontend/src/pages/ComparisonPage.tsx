import clsx from "clsx";
import { AlertTriangle, ArrowLeft, ChevronDown, ChevronRight, Crown, Info } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { ComparisonResult, S } from "@/api/client";
import { CostChart } from "@/components/CostChart";
import { PLAN_COLORS } from "@/lib/colors";
import { ExplanationPanel } from "@/components/ExplanationPanel";
import { Badge, Card, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { useComparison } from "@/hooks/api";
import { money, range, signedMoney, signedRange } from "@/lib/format";
import { SECTIONS } from "@/lib/sections";

type Verdict = S["Verdict"];
const VERDICT: Record<Verdict, { label: string; cls: string }> = {
  better: { label: "lower cost", cls: "bg-emerald-50 text-emerald-700" },
  worse: { label: "higher cost", cls: "bg-red-50 text-red-700" },
  same: { label: "about the same", cls: "bg-slate-100 text-slate-600" },
  not_comparable: { label: "not comparable", cls: "bg-slate-50 text-slate-400" },
};

function Delta({ v, invert = false }: { v: number | null | undefined; invert?: boolean }) {
  if (v === null || v === undefined || v === 0) return null;
  const good = invert ? v > 0 : v < 0;
  return <span className={clsx("ml-1 text-xs font-medium", good ? "text-emerald-600" : "text-red-600")}>{signedMoney(v)}</span>;
}

function HeadlineCards({ r }: { r: ComparisonResult }) {
  const h = r.headline;
  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(auto-fit, minmax(15rem, 1fr))` }}>
      {r.plans.map((p, i) => (
        <Card key={p.plan_key} className="p-4">
          <div className="mb-3 flex items-start gap-2">
            <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ background: PLAN_COLORS[i] }} />
            <div className="min-w-0">
              <p className="truncate font-semibold text-slate-900" title={p.plan_name ?? ""}>{p.plan_name ?? `Plan ${p.plan_key}`}</p>
              <p className="truncate text-xs text-slate-500">
                {p.issuer} {p.plan_type && `· ${p.plan_type}`} {p.metal && `· ${p.metal}`}
              </p>
              {p.is_base && <Badge tone="blue">Base plan</Badge>}
            </div>
          </div>
          <dl className="space-y-1.5 text-sm">
            {(
              [
                ["Premiums / year", h.annual_premium[p.plan_key], null],
                ["Deductible", h.deductible[p.plan_key]?.individual, null],
                ["Out-of-pocket limit", h.oop_limit[p.plan_key]?.individual, null],
                ["If you use no care", h.best_case[p.plan_key], h.best_case_delta[p.plan_key]],
                ["Worst case (hit the limit)", h.worst_case[p.plan_key], h.worst_case_delta[p.plan_key]],
              ] as [string, number | null | undefined, number | null | undefined][]
            ).map(([label, v, d]) => (
              <div key={label} className="flex justify-between gap-2">
                <dt className="text-slate-500">{label}</dt>
                <dd className="tabular font-medium text-slate-900">
                  {money(v, "—")}
                  <Delta v={d} />
                </dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}
    </div>
  );
}

function ScenarioTable({ r }: { r: ComparisonResult }) {
  const [open, setOpen] = useState<string | null>(null);
  const names = Object.fromEntries(r.plans.map((p) => [p.plan_key, p.plan_name ?? `Plan ${p.plan_key}`]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2 pr-4 font-medium">Scenario</th>
            {r.plans.map((p) => (
              <th key={p.plan_key} className="py-2 pr-4 text-right font-medium">{names[p.plan_key]}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {r.scenarios.map((s) => (
            <Fragment key={s.scenario.id}>
              <tr className="align-top">
                <td className="py-3 pr-4">
                  <button className="flex items-center gap-1 text-left font-medium text-slate-900" onClick={() => setOpen(open === s.scenario.id ? null : s.scenario.id)} aria-expanded={open === s.scenario.id}>
                    {open === s.scenario.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    {s.scenario.label}
                  </button>
                  <p className="ml-5 text-xs text-slate-500">{s.scenario.description}</p>
                  {s.ranges_overlap && <p className="ml-5 mt-1 text-xs text-amber-700">Ranges overlap: it depends on details the SBCs don't state.</p>}
                </td>
                {r.plans.map((p) => {
                  const pr = s.per_plan[p.plan_key];
                  const cheapest = s.cheapest.includes(p.plan_key) && !s.ranges_overlap;
                  return (
                    <td key={p.plan_key} className="tabular py-3 pr-4 text-right">
                      <span className={clsx("font-semibold", cheapest ? "text-emerald-700" : "text-slate-900")}>
                        {cheapest && <Crown className="mr-1 inline h-3.5 w-3.5" aria-label="lowest" />}
                        {range(pr.total)}
                      </span>
                      <div className="text-xs text-slate-500">out of pocket {range(pr.out_of_pocket)}</div>
                      {!p.is_base && s.delta_vs_base[p.plan_key] && <div className="text-xs text-slate-500">vs base {signedRange(s.delta_vs_base[p.plan_key])}</div>}
                    </td>
                  );
                })}
              </tr>
              {open === s.scenario.id && (
                <tr>
                  <td colSpan={r.plans.length + 1} className="bg-slate-50 px-4 py-3">
                    <p className="mb-2 text-xs font-medium text-slate-600">Show your work: what you pay for each claim</p>
                    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${r.plans.length}, minmax(14rem, 1fr))` }}>
                      {r.plans.map((p) => (
                        <div key={p.plan_key}>
                          <p className="mb-1 text-xs font-semibold text-slate-800">{names[p.plan_key]}</p>
                          <ul className="space-y-0.5 text-xs text-slate-600">
                            {s.per_plan[p.plan_key].trace.map((li, i) => (
                              <li key={i} className="flex justify-between gap-2" title={li.note || undefined}>
                                <span className="truncate">{li.service_key.replace("drug:", "").replace(/_/g, " ")}{li.note && " *"}</span>
                                <span className="tabular">{range(li.member_pays)} <span className="text-slate-400">of {money(li.allowed)}</span></span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-slate-500">* the SBC doesn't say whether the deductible applies, or the service isn't covered. Hover for details.</p>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DiffTable({ r }: { r: ComparisonResult }) {
  const [onlyDiff, setOnlyDiff] = useState(true);
  const base = r.plans.find((p) => p.is_base)!.plan_key;
  const rows = useMemo(() => {
    const isDiff = (d: S["ServiceDiff"]) => d.flags.length > 0 || Object.values(d.verdicts).some((v) => v !== "same");
    return SECTIONS.filter((s) => s.services.length).map((sec) => ({
      sec,
      items: r.services.filter((d) => d.section === sec.id && (!onlyDiff || isDiff(d))),
    }));
  }, [r, onlyDiff]);
  const drugs = r.drug_tiers.filter((d) => !onlyDiff || Object.values(d.verdicts).some((v) => v !== "same"));

  const cell = (c: S["CellView"] | null | undefined, verdict?: Verdict) => (
    <td className="py-2 pr-4 align-top">
      <div className={clsx(c?.covered === false ? "text-slate-400" : "text-slate-900")}>{c?.display ?? "Not listed"}</div>
      {c?.est_cost_per_use !== null && c?.est_cost_per_use !== undefined && <div className="text-xs text-slate-500">≈ {money(c.est_cost_per_use)} per use</div>}
      {verdict && <span className={clsx("mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-medium", VERDICT[verdict].cls)}>{VERDICT[verdict].label}</span>}
    </td>
  );

  return (
    <div>
      <label className="mb-3 inline-flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} className="h-4 w-4" /> Show only differences
      </label>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-2 pr-4 font-medium">Service</th>
              {r.plans.map((p) => (
                <th key={p.plan_key} className="py-2 pr-4 font-medium">{p.plan_name ?? `Plan ${p.plan_key}`}{p.is_base && " (base)"}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ sec, items }) =>
              items.length ? (
                <Fragment key={sec.id}>
                  <tr><td colSpan={r.plans.length + 1} className="pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">{sec.title}</td></tr>
                  {items.map((d) => (
                    <tr key={d.id} className="border-t border-slate-100">
                      <td className="py-2 pr-4 align-top text-slate-700">
                        {d.label}
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          {d.flags.includes("coverage_gap") && <Badge tone="red">coverage gap</Badge>}
                          {d.flags.includes("deductible_difference") && <Badge tone="amber">deductible differs</Badge>}
                        </div>
                      </td>
                      {r.plans.map((p) => (
                        <Fragment key={p.plan_key}>{cell(d.cells[p.plan_key], p.plan_key === base ? undefined : d.verdicts[p.plan_key])}</Fragment>
                      ))}
                    </tr>
                  ))}
                </Fragment>
              ) : null,
            )}
            {drugs.length > 0 && (
              <>
                <tr><td colSpan={r.plans.length + 1} className="pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-slate-400">Prescription drugs (retail, 30-day)</td></tr>
                {drugs.map((d) => (
                  <tr key={d.id} className="border-t border-slate-100">
                    <td className="py-2 pr-4 align-top text-slate-700">{d.label}</td>
                    {r.plans.map((p) => (
                      <Fragment key={p.plan_key}>{cell(d.cells[p.plan_key], p.plan_key === base ? undefined : d.verdicts[p.plan_key])}</Fragment>
                    ))}
                  </tr>
                ))}
              </>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">"Per use" assumes the deductible is already met and uses reference prices; it's for comparing copays with coinsurance.</p>
    </div>
  );
}

function CoverageExamples({ r }: { r: ComparisonResult }) {
  const withEx = r.plans.filter((p) => r.coverage_examples?.[p.plan_key]);
  if (!withEx.length) return null;
  const labels: Record<string, string> = { having_a_baby: "Having a baby", managing_diabetes: "Managing type 2 diabetes", simple_fracture: "Simple fracture" };
  return (
    <Card className="p-5">
      <h2 className="mb-1 font-semibold">The plans' own coverage examples</h2>
      <p className="mb-3 text-sm text-slate-500">What each SBC says you'd pay in the standard federal examples (marketplace plans only, from the CMS data).</p>
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2 pr-4 font-medium">Example</th>
            {withEx.map((p) => <th key={p.plan_key} className="py-2 pr-4 text-right font-medium">{p.plan_name}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {Object.entries(labels).map(([k, label]) => (
            <tr key={k}>
              <td className="py-2 pr-4">{label}</td>
              {withEx.map((p) => {
                const ex = (r.coverage_examples?.[p.plan_key] as Record<string, { total?: number }> | null)?.[k];
                return <td key={p.plan_key} className="tabular py-2 pr-4 text-right">{money(ex?.total)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export function ComparisonPage() {
  const { id } = useParams();
  const { data, isLoading, isError, error, refetch } = useComparison(id);
  if (isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-48" /><Skeleton className="h-80" /></div>;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;
  const r = data.result;
  const gaps = r.services.filter((s) => r.coverage_gaps.includes(s.id));
  return (
    <div className="space-y-6">
      <Link to="/compare" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> Change inputs
      </Link>
      <PageHeader
        title="Plan comparison"
        subtitle={`${r.plans.length} plans · ${r.coverage_tier === "family" ? "family" : "individual"} coverage · ${r.network === "in_network" ? "in-network" : "out-of-network"} care`}
      />
      <ExplanationPanel data={data} />
      <HeadlineCards r={r} />
      <Card className="p-5">
        <h2 className="mb-1 font-semibold">Estimated yearly cost by scenario</h2>
        <p className="mb-4 text-sm text-slate-500">Premiums minus employer contributions plus what you'd pay for care. Lighter bars show the range where the SBC leaves something unstated.</p>
        <CostChart result={r} />
        <div className="mt-6"><ScenarioTable r={r} /></div>
      </Card>
      {gaps.length > 0 && (
        <Card className="border-red-200 p-5">
          <h2 className="mb-2 flex items-center gap-2 font-semibold text-red-800"><AlertTriangle className="h-4 w-4" /> Coverage gaps</h2>
          <ul className="space-y-1 text-sm">
            {gaps.map((g) => (
              <li key={g.id}>
                <span className="font-medium">{g.label}:</span>{" "}
                {r.plans.map((p) => `${p.plan_name ?? p.plan_key}: ${g.cells[p.plan_key]?.display ?? "not listed"}`).join(" · ")}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card className="p-5">
        <h2 className="mb-3 font-semibold">Side by side</h2>
        <DiffTable r={r} />
      </Card>
      <CoverageExamples r={r} />
      <Card className="p-5 text-sm text-slate-600">
        <h2 className="mb-2 flex items-center gap-2 font-semibold text-slate-900"><Info className="h-4 w-4" /> Assumptions and notes</h2>
        <ul className="list-disc space-y-1 pl-5">
          {r.assumptions.map((a, i) => <li key={i}>{a}</li>)}
          {r.warnings.slice(0, 8).map((w, i) => <li key={`w${i}`} className="text-amber-800">{w.message}</li>)}
        </ul>
        <p className="mt-3 text-xs text-slate-400">Engine {r.engine_version} · reference prices {r.reference_prices_version} · result {r.result_hash}</p>
      </Card>
    </div>
  );
}
