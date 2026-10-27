import { CheckSquare, ChevronLeft, ChevronRight, Library, Search, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import type { CatalogPlan } from "@/api/client";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton, inputClass } from "@/components/ui";
import { useCatalog, useFacets } from "@/hooks/api";
import { MAX_PLANS, useSelection } from "@/hooks/selection";
import { money } from "@/lib/format";

const PAGE = 20;
const METAL_TONE: Record<string, "amber" | "gray" | "blue" | "violet" | "green"> = {
  Bronze: "amber",
  "Expanded Bronze": "amber",
  Silver: "gray",
  Gold: "amber",
  Platinum: "violet",
  Catastrophic: "green",
};

function useDebounced<T>(v: T, ms = 300): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

function SelectPlan({ plan }: { plan: CatalogPlan }) {
  const sel = useSelection();
  if (!plan.document_id) return null;
  const on = sel.has(plan.document_id);
  return (
    <Button
      size="sm"
      variant={on ? "secondary" : "ghost"}
      aria-pressed={on}
      onClick={() => {
        if (!sel.toggle({ documentId: plan.document_id!, label: plan.plan_name, source: "catalog", catalogPlanId: plan.plan_id, issuer: plan.issuer }))
          toast.error(`You can compare up to ${MAX_PLANS} plans.`);
      }}
    >
      {on ? <CheckSquare className="h-4 w-4 text-brand-600" /> : <Square className="h-4 w-4" />}
      {on ? "Selected" : "Compare"}
    </Button>
  );
}

export function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const [q, setQ] = useState(get("q"));
  const dq = useDebounced(q);
  const offset = Number(get("offset") || 0);
  const filters = { state: get("state"), metal: get("metal"), plan_type: get("plan_type"), issuer: get("issuer"), sort: get("sort") || "plan_name" };

  useEffect(() => {
    if (dq !== get("q")) update({ q: dq });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq]);

  function update(patch: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("offset" in patch)) next.delete("offset");
    setParams(next, { replace: true });
  }

  const facets = useFacets();
  const { data, isLoading, isError, error, refetch, isFetching } = useCatalog({ ...filters, q: dq || undefined, offset, limit: PAGE });
  const empty = facets.data && facets.data.state.length === 0;

  const select = (key: keyof typeof filters, label: string, opts: { value: string; count: number }[] | undefined) => (
    <label className="text-sm">
      <span className="sr-only">{label}</span>
      <select aria-label={label} className={inputClass} value={filters[key]} onChange={(e) => update({ [key]: e.target.value })}>
        <option value="">{label}: all</option>
        {opts?.map((o) => (
          <option key={o.value} value={o.value}>
            {o.value} ({o.count})
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Marketplace catalog"
        subtitle="2026 HealthCare.gov plans, read from their SBCs. Add any of them to a comparison with your own plan."
      />
      {empty ? (
        <EmptyState icon={<Library className="h-8 w-8" />} title="The catalog is empty">
          Load it once with <code className="rounded bg-slate-100 px-1">make ingest-catalog</code> (and optionally{" "}
          <code className="rounded bg-slate-100 px-1">make load-premiums</code>), then refresh.
        </EmptyState>
      ) : (
        <>
          <Card className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-6">
            <label className="relative lg:col-span-2">
              <span className="sr-only">Search</span>
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input className={`${inputClass} pl-9`} placeholder="Search plan, issuer or plan ID" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            {select("state", "State", facets.data?.state)}
            {select("metal", "Metal", facets.data?.metal)}
            {select("plan_type", "Type", facets.data?.plan_type)}
            <select aria-label="Sort" className={inputClass} value={filters.sort} onChange={(e) => update({ sort: e.target.value })}>
              <option value="plan_name">Sort: name</option>
              <option value="deductible">Sort: lowest deductible</option>
              <option value="oop">Sort: lowest out-of-pocket limit</option>
            </select>
          </Card>
          {isError && <ErrorState error={error} onRetry={() => refetch()} />}
          {isLoading && <Skeleton className="h-64" />}
          {data && data.items.length === 0 && <EmptyState title="No plans match these filters">Try removing a filter or changing the search.</EmptyState>}
          {data && data.items.length > 0 && (
            <Card className={isFetching ? "opacity-70" : ""}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">Plan</th>
                      <th className="px-4 py-3 font-medium">State</th>
                      <th className="px-4 py-3 font-medium">Metal / type</th>
                      <th className="px-4 py-3 text-right font-medium">Deductible</th>
                      <th className="px-4 py-3 text-right font-medium">Out-of-pocket limit</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.items.map((p) => (
                      <tr key={p.plan_id} className="hover:bg-slate-50">
                        <td className="px-4 py-3">
                          {p.document_id ? (
                            <Link to={`/plans/${p.document_id}`} className="font-medium text-slate-900 hover:text-brand-700">{p.plan_name}</Link>
                          ) : (
                            p.plan_name
                          )}
                          <div className="text-xs text-slate-500">{p.issuer} · {p.plan_id}</div>
                        </td>
                        <td className="px-4 py-3">{p.state}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {p.metal && <Badge tone={METAL_TONE[p.metal] ?? "gray"}>{p.metal}</Badge>}
                            {p.plan_type && <Badge>{p.plan_type}</Badge>}
                          </div>
                        </td>
                        <td className="tabular px-4 py-3 text-right">{money(p.deductible_individual)}</td>
                        <td className="tabular px-4 py-3 text-right">{money(p.oop_individual)}</td>
                        <td className="px-4 py-3 text-right"><SelectPlan plan={p} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm text-slate-600">
                <span>
                  {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total.toLocaleString()} plans
                </span>
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => update({ offset: String(Math.max(0, offset - PAGE)) })}>
                    <ChevronLeft className="h-4 w-4" /> Previous
                  </Button>
                  <Button variant="secondary" size="sm" disabled={offset + PAGE >= data.total} onClick={() => update({ offset: String(offset + PAGE) })}>
                    Next <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
