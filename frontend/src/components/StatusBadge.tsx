import { Badge, Spinner } from "@/components/ui";
import type { DocumentSummary } from "@/api/client";

export function StatusBadge({ doc }: { doc: Pick<DocumentSummary, "status" | "error_message"> }) {
  switch (doc.status) {
    case "queued":
      return <Badge tone="gray">Queued</Badge>;
    case "extracting":
      return (
        <Badge tone="blue">
          <Spinner /> Reading PDF
        </Badge>
      );
    case "ready":
      return <Badge tone="green">Ready</Badge>;
    case "failed":
      return (
        <Badge tone="red" title={doc.error_message ?? undefined}>
          Failed
        </Badge>
      );
  }
}

export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone = value >= 0.9 ? "green" : value >= 0.75 ? "amber" : "red";
  return (
    <Badge tone={tone} title="Average confidence of the extracted values">
      {pct}% confidence
    </Badge>
  );
}
