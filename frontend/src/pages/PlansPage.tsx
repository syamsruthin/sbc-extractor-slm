import { AlertTriangle, CheckSquare, FileText, Square, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import type { DocumentSummary } from "@/api/client";
import { ConfidenceBadge, StatusBadge } from "@/components/StatusBadge";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { useDeleteDocument, useDocuments } from "@/hooks/api";
import { MAX_PLANS, useSelection } from "@/hooks/selection";
import { relTime } from "@/lib/format";

function SelectButton({ doc }: { doc: DocumentSummary }) {
  const sel = useSelection();
  const on = sel.has(doc.id);
  return (
    <Button
      variant={on ? "secondary" : "ghost"}
      size="sm"
      disabled={doc.status !== "ready"}
      aria-pressed={on}
      onClick={() => {
        const ok = sel.toggle({ documentId: doc.id, label: doc.plan_name ?? doc.filename, source: "upload", issuer: doc.issuer });
        if (!ok) toast.error(`You can compare up to ${MAX_PLANS} plans.`);
      }}
    >
      {on ? <CheckSquare className="h-4 w-4 text-brand-600" /> : <Square className="h-4 w-4" />}
      {on ? "Selected" : "Compare"}
    </Button>
  );
}

function PlanRow({ doc }: { doc: DocumentSummary }) {
  const del = useDeleteDocument();
  return (
    <li className="flex flex-wrap items-center gap-4 px-4 py-3">
      <FileText className="h-5 w-5 shrink-0 text-slate-400" aria-hidden />
      <div className="min-w-0 flex-1">
        {doc.status === "ready" ? (
          <Link to={`/plans/${doc.id}`} className="font-medium text-slate-900 hover:text-brand-700">
            {doc.plan_name ?? doc.filename}
          </Link>
        ) : (
          <span className="font-medium text-slate-900">{doc.plan_name ?? doc.filename}</span>
        )}
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {doc.issuer && <span>{doc.issuer}</span>}
          {doc.plan_type && <Badge>{doc.plan_type}</Badge>}
          <span>{doc.filename}</span>
          <span>· {relTime(doc.created_at)}</span>
        </div>
        {doc.status === "failed" && <p className="mt-1 text-sm text-red-700">{doc.error_message}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge doc={doc} />
        {doc.status === "ready" && <ConfidenceBadge value={doc.doc_confidence} />}
        {doc.warning_count > 0 && (
          <Badge tone="amber" title="Values worth double-checking">
            <AlertTriangle className="h-3 w-3" /> {doc.warning_count}
          </Badge>
        )}
        <SelectButton doc={doc} />
        <Button
          variant="danger"
          size="sm"
          aria-label={`Remove ${doc.plan_name ?? doc.filename}`}
          loading={del.isPending && del.variables === doc.id}
          onClick={() => del.mutate(doc.id)}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </li>
  );
}

export function PlansPage() {
  const { data, isLoading, isError, error, refetch } = useDocuments();
  return (
    <div className="space-y-6">
      <PageHeader
        title="My plans"
        subtitle="Upload the SBC for each plan you're considering. We read the benefits, then you can compare them side by side."
      />
      <UploadDropzone />
      {isLoading && (
        <Card className="space-y-3 p-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </Card>
      )}
      {isError && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && data.items.length === 0 && (
        <EmptyState icon={<FileText className="h-8 w-8" />} title="No plans yet">
          Upload an SBC PDF above, or pick plans from the <Link className="text-brand-600 underline" to="/catalog">marketplace catalog</Link>.
        </EmptyState>
      )}
      {data && data.items.length > 0 && (
        <Card>
          <ul className="divide-y divide-slate-100" aria-label="Uploaded plans">
            {data.items.map((d) => (
              <PlanRow key={d.id} doc={d} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
