import { AlertTriangle, ArrowLeft, CheckSquare, ExternalLink, RefreshCw, Sparkles, Square } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, type BenefitsDocument, type CostShare, type DocumentDetail, type S } from "@/api/client";
import { ProvenanceButton } from "@/components/ProvenanceButton";
import { ConfidenceBadge, StatusBadge } from "@/components/StatusBadge";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton, Spinner } from "@/components/ui";
import { useDocument, useGenerateSummaries } from "@/hooks/api";
import { MAX_PLANS, useSelection } from "@/hooks/selection";
import { deductibleNote, describeCost, money } from "@/lib/format";
import { SECTIONS, SERVICE_LABELS, type SectionDef } from "@/lib/sections";

type Amounts = S["Amounts"] | null | undefined;

function CostCell({ c, path, doc, pdf }: { c: CostShare | null | undefined; path: string; doc: BenefitsDocument; pdf: string }) {
  const note = deductibleNote(c);
  return (
    <div>
      <ProvenanceButton meta={doc.provenance?.[`${path}.copay`]} pdfUrl={pdf}>
        <span className={c && !c.covered ? "text-slate-400" : "font-medium text-slate-900"}>{describeCost(c)}</span>
      </ProvenanceButton>
      {note && <div className="text-xs text-slate-500">{note}</div>}
      {c?.note && <div className="mt-0.5 text-xs text-slate-500">{c.note}</div>}
    </div>
  );
}

function amountText(a: Amounts): string {
  if (!a) return "Not stated";
  return `${money(a.individual)} individual${a.family !== null && a.family !== undefined ? ` · ${money(a.family)} family` : ""}`;
}

function Summary({ doc, section, status }: { doc: BenefitsDocument; section: string; status: string }) {
  const s = doc.summaries?.find((x) => x.section === section);
  if (s)
    return (
      <div className="rounded-lg bg-brand-50/60 p-3 text-sm text-slate-700">
        <p>{s.summary}</p>
        {s.highlights && s.highlights.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {s.highlights.map((h) => (
              <li key={h}>
                <Badge tone="blue">{h}</Badge>
              </li>
            ))}
          </ul>
        )}
        {s.source === "template" && <p className="mt-1 text-xs text-slate-500">Generated from the extracted values (AI summary unavailable).</p>}
      </div>
    );
  if (status === "running" || status === "pending") return <Skeleton className="h-12" />;
  return null;
}

function SectionCard({ def, detail }: { def: SectionDef; detail: DocumentDetail }) {
  const doc = detail.benefits!;
  const b = doc.benefits;
  const pdf = api.pdfUrl(detail.id);
  return (
    <Card className="p-5" >
      <h2 id={`sec-${def.id}`} className="mb-3 text-base font-semibold text-slate-900">
        {def.title}
      </h2>
      <div className="space-y-4">
        <Summary doc={doc} section={def.id} status={detail.summaries_status} />
        {def.services.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="pb-2 pr-4 font-medium">Service</th>
                  <th className="pb-2 pr-4 font-medium">In network</th>
                  <th className="pb-2 pr-4 font-medium">Out of network</th>
                  <th className="pb-2 font-medium">Limits &amp; notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 align-top">
                {def.services.map((k) => {
                  const svc = (b.services as Record<string, S["ServiceCost"]>)[k];
                  return (
                    <tr key={k}>
                      <td className="py-2 pr-4 text-slate-700">{SERVICE_LABELS[k]}</td>
                      <td className="py-2 pr-4"><CostCell c={svc.in_network} path={`services.${k}.in_network`} doc={doc} pdf={pdf} /></td>
                      <td className="py-2 pr-4"><CostCell c={svc.out_of_network} path={`services.${k}.out_of_network`} doc={doc} pdf={pdf} /></td>
                      <td className="max-w-xs py-2 text-xs text-slate-500">{doc.extras.limitations?.[k] ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {def.id === "deductible_oop" && (
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            {(
              [
                ["Deductible (in network)", b.deductible.in_network, "deductible.in_network.individual"],
                ["Deductible (out of network)", b.deductible.out_of_network, "deductible.out_of_network.individual"],
                ["Out-of-pocket limit (in network)", b.out_of_pocket_limit.in_network, "out_of_pocket_limit.in_network.individual"],
                ["Out-of-pocket limit (out of network)", b.out_of_pocket_limit.out_of_network, "out_of_pocket_limit.out_of_network.individual"],
              ] as [string, Amounts, string][]
            ).map(([label, a, path]) => (
              <div key={label}>
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="font-medium">
                  <ProvenanceButton meta={doc.provenance?.[path]} pdfUrl={pdf}>{amountText(a)}</ProvenanceButton>
                </dd>
              </div>
            ))}
            <div className="sm:col-span-2">
              <dt className="text-xs text-slate-500">Covered before you meet the deductible</dt>
              <dd>{b.services_before_deductible.length ? b.services_before_deductible.join("; ") : "Nothing listed"}</dd>
            </div>
          </dl>
        )}
        {def.id === "drugs" &&
          (b.drug_tiers.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="pb-2 pr-4 font-medium">Tier</th>
                  <th className="pb-2 pr-4 font-medium">Retail, in network</th>
                  <th className="pb-2 font-medium">Out of network</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 align-top">
                {b.drug_tiers.map((t, i) => (
                  <tr key={i}>
                    <td className="py-2 pr-4">
                      {t.name} <Badge>{t.category.replace(/_/g, " ")}</Badge>
                    </td>
                    <td className="py-2 pr-4"><CostCell c={t.retail.in_network} path={`drug_tiers[${i}].retail.in_network`} doc={doc} pdf={pdf} /></td>
                    <td className="py-2"><CostCell c={t.retail.out_of_network} path={`drug_tiers[${i}].retail.out_of_network`} doc={doc} pdf={pdf} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-slate-500">No drug tiers were found.</p>
          ))}
        {def.id === "exclusions" &&
          (b.excluded_services.length ? (
            <ul className="grid gap-x-6 gap-y-1 text-sm text-slate-700 sm:grid-cols-2">
              {b.excluded_services.map((x) => (
                <li key={x} className="before:mr-2 before:text-slate-400 before:content-['•']">{x}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">No exclusions listed.</p>
          ))}
        {def.id === "overview" && (
          <dl className="grid gap-4 text-sm sm:grid-cols-4">
            <div><dt className="text-xs text-slate-500">Plan type</dt><dd className="font-medium">{b.plan_type ?? "—"}</dd></div>
            <div><dt className="text-xs text-slate-500">Coverage period</dt><dd className="font-medium">{b.coverage_period ?? "—"}</dd></div>
            <div>
              <dt className="text-xs text-slate-500">Referral for specialists</dt>
              <dd className="font-medium">{b.referral_required_for_specialist === null ? "Not stated" : b.referral_required_for_specialist ? "Required" : "Not required"}</dd>
            </div>
            <div><dt className="text-xs text-slate-500">Family deductible</dt><dd className="font-medium capitalize">{doc.extras.deductible_type}</dd></div>
          </dl>
        )}
      </div>
    </Card>
  );
}

export function PlanDetailPage() {
  const { id } = useParams();
  const { data, isLoading, isError, error, refetch } = useDocument(id);
  const sel = useSelection();
  const summaries = useGenerateSummaries();

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-40" /><Skeleton className="h-40" /></div>;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return null;
  if (data.status !== "ready" || !data.benefits)
    return (
      <EmptyState title={data.status === "failed" ? "We couldn't read this document" : "Reading the PDF…"}>
        {data.status === "failed" ? data.error_message : <Spinner label="This usually takes a few seconds." />}
      </EmptyState>
    );

  const doc = data.benefits;
  const b = doc.benefits;
  const on = sel.has(data.id);
  return (
    <div className="space-y-6">
      <Link to={data.source === "catalog" ? "/catalog" : "/"} className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>
      <PageHeader
        title={b.plan_name ?? data.filename}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {b.issuer && <span>{b.issuer}</span>}
            {b.plan_type && <Badge>{b.plan_type}</Badge>}
            <Badge tone={data.source === "catalog" ? "violet" : "gray"}>{data.source === "catalog" ? "Marketplace catalog" : "Uploaded"}</Badge>
            <StatusBadge doc={data} />
            <ConfidenceBadge value={data.doc_confidence} />
          </span>
        }
        actions={
          <>
            <a className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline" href={api.pdfUrl(data.id)} target="_blank" rel="noreferrer">
              Original PDF <ExternalLink className="h-3.5 w-3.5" />
            </a>
            {data.summaries_status !== "ready" && data.summaries_status !== "running" && (
              <Button variant="secondary" loading={summaries.isPending} onClick={() => summaries.mutate(data.id)}>
                <Sparkles className="h-4 w-4" /> Summarize sections
              </Button>
            )}
            {data.summaries_status === "ready" && (
              <Button variant="ghost" size="sm" loading={summaries.isPending} onClick={() => summaries.mutate(data.id)} title="Regenerate summaries">
                <RefreshCw className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant={on ? "secondary" : "primary"}
              onClick={() => {
                if (!sel.toggle({ documentId: data.id, label: b.plan_name ?? data.filename, source: data.source as "upload" | "catalog", catalogPlanId: data.catalog_plan_id, issuer: b.issuer }))
                  toast.error(`You can compare up to ${MAX_PLANS} plans.`);
              }}
            >
              {on ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />} {on ? "Selected" : "Add to comparison"}
            </Button>
          </>
        }
      />
      {data.summaries_status === "running" && <Spinner label="Writing plain-language summaries…" />}
      {doc.warnings.length > 0 && (
        <Card className="border-amber-200 bg-amber-50 p-4">
          <p className="flex items-center gap-2 text-sm font-medium text-amber-900">
            <AlertTriangle className="h-4 w-4" /> Worth double-checking
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-6 text-sm text-amber-900">
            {doc.warnings.map((w, i) => (
              <li key={i}>{w.message}</li>
            ))}
          </ul>
        </Card>
      )}
      <p className="text-xs text-slate-500">Tip: click any underlined value to see the text and page it came from in the PDF.</p>
      <div className="space-y-4">
        {SECTIONS.map((s) => (
          <SectionCard key={s.id} def={s} detail={data} />
        ))}
      </div>
    </div>
  );
}
