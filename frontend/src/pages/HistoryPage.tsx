import { History, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { useComparisons, useDeleteComparison } from "@/hooks/api";
import { relTime } from "@/lib/format";

/** Saved comparisons: they hold premiums, ages and usage, so each can be deleted (v2.1 M3). */
export function HistoryPage() {
  const { data, isLoading, isError, error, refetch } = useComparisons();
  const del = useDeleteComparison();
  const [confirmAll, setConfirmAll] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Saved comparisons"
        subtitle="Each comparison keeps the premiums, ages and usage you entered so you can reopen or change it. Delete any you no longer need."
        actions={
          data && data.length > 0 && !confirmAll ? (
            <Button variant="secondary" onClick={() => setConfirmAll(true)}>
              <Trash2 className="h-4 w-4" /> Delete all
            </Button>
          ) : undefined
        }
      />
      {confirmAll && (
        <Card className="flex flex-wrap items-center gap-3 border-red-200 bg-red-50 p-4 text-sm text-red-800" >
          <span role="alert">Delete all {data?.length} saved comparisons? This can't be undone.</span>
          <Button
            variant="primary"
            className="bg-red-600 hover:bg-red-700"
            loading={del.isPending}
            onClick={() => del.mutate("all", { onSettled: () => setConfirmAll(false) })}
          >
            Delete all
          </Button>
          <Button variant="ghost" onClick={() => setConfirmAll(false)}>Cancel</Button>
        </Card>
      )}
      {isLoading && <Skeleton className="h-40" />}
      {isError && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <EmptyState icon={<History className="h-8 w-8" />} title="No saved comparisons">
          Comparisons you run appear here. <Link className="text-brand-600 underline" to="/compare">Compare plans</Link>
        </EmptyState>
      )}
      {data && data.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100" aria-label="Saved comparisons">
            {data.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <Link to={`/comparisons/${c.id}`} className="font-medium text-slate-900 hover:text-brand-700">
                    {c.plan_names.join(" vs ")}
                  </Link>
                  <p className="text-xs text-slate-500">
                    {relTime(c.created_at)}
                    {c.scenario_labels && c.scenario_labels.length > 0 && ` · ${c.scenario_labels.join(", ")}`}
                  </p>
                </div>
                <Button variant="danger" size="sm" aria-label={`Delete comparison of ${c.plan_names.join(" and ")}`} onClick={() => del.mutate(c.id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
