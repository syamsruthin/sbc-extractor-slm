import { AlertTriangle, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";

import type { ComparisonResponse } from "@/api/client";
import { Badge, Button, Card, Skeleton } from "@/components/ui";
import { useRegenerateExplanation } from "@/hooks/api";

const SOURCE: Record<string, { label: string; tone: "green" | "blue" | "amber" }> = {
  llm: { label: "AI explanation", tone: "green" },
  llm_retry: { label: "AI explanation (corrected)", tone: "blue" },
  template: { label: "Standard summary", tone: "amber" },
};

export function ExplanationPanel({ data }: { data: ComparisonResponse }) {
  const regen = useRegenerateExplanation(data.id);
  const st = data.explanation_status;
  const e = data.explanation;

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 bg-gradient-to-r from-brand-50 to-white px-5 py-3">
        <h2 className="flex items-center gap-2 font-semibold text-slate-900">
          <Sparkles className="h-4 w-4 text-brand-600" /> What this means for you
        </h2>
        <div className="flex items-center gap-2">
          {e && <Badge tone={SOURCE[e.source].tone}>{SOURCE[e.source].label}</Badge>}
          {e?.grounding.ok && (
            <Badge
              tone="green"
              title={`Checked against the calculation: ${e.grounding.numbers_checked} amounts and percentages, "lowest/highest" claims, and statements about deductibles and coverage. Other wording isn't machine-checked.`}
            >
              <ShieldCheck className="h-3 w-3" /> Numbers checked
            </Badge>
          )}
          {(st === "ready" || st === "failed") && (
            <Button variant="ghost" size="sm" loading={regen.isPending} onClick={() => regen.mutate()} title="Write the explanation again">
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
      <div className="p-5">
        {(st === "pending" || st === "running") && (
          <div className="space-y-3" aria-busy="true" aria-label="Writing the explanation">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
            <p className="text-xs text-slate-500">Writing a plain-language explanation from the computed numbers…</p>
          </div>
        )}
        {st === "failed" && (
          <p role="alert" className="flex items-center gap-2 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4" /> The explanation couldn't be written. The numbers below are still complete. Try again with the refresh button.
          </p>
        )}
        {st === "skipped" && <p className="text-sm text-slate-500">No explanation was requested for this comparison.</p>}
        {st === "ready" && e && (
          <div className="space-y-5 text-sm leading-relaxed text-slate-700">
            <p className="text-lg font-medium text-slate-900">{e.content.headline}</p>
            <ul className="list-disc space-y-1 pl-5">
              {e.content.key_points.map((k, i) => (
                <li key={i}>{k}</li>
              ))}
            </ul>
            <div className="grid gap-3 md:grid-cols-2">
              {e.content.scenarios.map((s) => (
                <div key={s.scenario} className="rounded-lg bg-slate-50 p-3">
                  <p className="mb-1 font-medium text-slate-900">{s.scenario}</p>
                  <p>{s.text}</p>
                </div>
              ))}
            </div>
            {e.content.watch_out && e.content.watch_out.length > 0 && (
              <div>
                <p className="mb-1 flex items-center gap-1.5 font-medium text-amber-800"><AlertTriangle className="h-4 w-4" /> Watch out for</p>
                <ul className="list-disc space-y-1 pl-5">
                  {e.content.watch_out.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">{e.content.disclaimer}</p>
          </div>
        )}
      </div>
    </Card>
  );
}
