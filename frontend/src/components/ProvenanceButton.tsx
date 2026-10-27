import { FileSearch, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import type { S } from "@/api/client";
import { Badge } from "@/components/ui";

type Meta = S["FieldMeta"];

const SOURCE_LABEL: Record<string, string> = {
  parser: "Read by parser",
  "parser+llm": "Parser, confirmed by AI",
  llm_fallback: "Re-read by AI",
  default: "Convention default",
};

/** A value that opens a popover showing where it came from in the PDF. */
export function ProvenanceButton({ meta, children, pdfUrl }: { meta?: Meta | null; children: ReactNode; pdfUrl?: string }) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const open = pos !== null;
  const ref = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  // fixed position (so table scroll containers don't clip it), kept next to the button on scroll/resize
  const place = () => {
    const r = btn.current?.getBoundingClientRect();
    if (r) setPos({ top: Math.min(r.bottom + 8, window.innerHeight - 300), left: Math.max(8, Math.min(r.left, window.innerWidth - 336)) });
  };
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setPos(null);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  if (!meta) return <>{children}</>;
  const low = meta.confidence < 0.75;
  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        ref={btn}
        onClick={() => (open ? setPos(null) : place())}
        className={`rounded text-left underline decoration-dotted underline-offset-4 hover:text-brand-700 ${low ? "decoration-amber-500" : "decoration-slate-300"}`}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {children}
      </button>
      {open && (
        <div role="dialog" aria-label="Source of this value" style={pos ?? undefined} className="fixed z-40 w-80 rounded-xl border border-slate-200 bg-white p-4 text-left text-sm shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 font-medium text-slate-800">
              <FileSearch className="h-4 w-4 text-brand-600" /> Source {meta.page ? `· page ${meta.page}` : ""}
            </span>
            <button aria-label="Close" onClick={() => setPos(null)} className="rounded p-1 text-slate-400 hover:bg-slate-100">
              <X className="h-4 w-4" />
            </button>
          </div>
          <blockquote className="max-h-40 overflow-auto rounded-lg bg-slate-50 p-2 font-mono text-xs leading-relaxed text-slate-700">
            {meta.raw_text ?? "No source text recorded."}
          </blockquote>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge tone={meta.source === "llm_fallback" ? "violet" : "gray"}>{SOURCE_LABEL[meta.source ?? "parser"]}</Badge>
            <Badge tone={low ? "amber" : "green"}>{Math.round(meta.confidence * 100)}% confidence</Badge>
            {(meta.reasons ?? []).map((r) => (
              <Badge key={r}>{r.replace(/_/g, " ")}</Badge>
            ))}
          </div>
          {pdfUrl && meta.page && (
            <a className="mt-3 inline-block text-xs font-medium text-brand-600 hover:underline" href={`${pdfUrl}#page=${meta.page}`} target="_blank" rel="noreferrer">
              Open PDF at page {meta.page} →
            </a>
          )}
        </div>
      )}
    </div>
  );
}
