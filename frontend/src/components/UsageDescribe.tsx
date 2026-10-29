import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError, type InterpretUsageResponse } from "@/api/client";
import { Button, inputClass } from "@/components/ui";

const MAX = 1000;
const ACK = "plan-compare:intake-notice";

function acknowledged(): boolean {
  try {
    return sessionStorage.getItem(ACK) === "1";
  } catch {
    return false;
  }
}

/** "Describe your year": plain words in, editable event rows out. Nothing is computed until the user presses
 * Compare, and the text itself is never saved (v2.1 M4). */
export function UsageDescribe({
  coverageTier,
  members,
  onEvents,
}: {
  coverageTier: "individual" | "family";
  members: string[];
  onEvents: (events: InterpretUsageResponse["events"]) => void;
}) {
  const [text, setText] = useState("");
  const [ack, setAck] = useState(acknowledged);
  const [unmodeled, setUnmodeled] = useState<InterpretUsageResponse["unmodeled"]>([]);
  const run = useMutation({
    mutationFn: () => api.interpretUsage({ text, coverage_tier: coverageTier, members: coverageTier === "family" ? members : [] }),
    onSuccess: (r) => {
      onEvents(r.events);
      setUnmodeled(r.unmodeled);
      toast.success(r.events.length ? `Added ${r.events.length} event${r.events.length > 1 ? "s" : ""}. Check them below.` : "No events found in that description.");
    },
    onError: (e) => toast.error(`${e instanceof ApiError ? e.message : "That didn't work."} You can add events manually.`),
  });

  const accept = (v: boolean) => {
    setAck(v);
    try {
      if (v) sessionStorage.setItem(ACK, "1");
      else sessionStorage.removeItem(ACK);
    } catch {
      /* private mode: ask again next time */
    }
  };

  return (
    <div className="mt-6 rounded-lg border border-violet-200 bg-violet-50/40 p-4">
      <h3 className="flex items-center gap-2 text-sm font-medium text-slate-800">
        <Sparkles className="h-4 w-4 text-violet-600" aria-hidden /> Describe your year (optional)
      </h3>
      <p className="mt-1 text-xs text-slate-600">
        For example: "I see a therapist every other week, take a generic pill daily, and we're having a baby in May." We turn it into the events below; you can change or remove any of them.
      </p>
      <textarea
        aria-label="Describe your expected care"
        className={`${inputClass} mt-2 min-h-[5rem]`}
        maxLength={MAX}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-0.5 h-4 w-4" checked={ack} onChange={(e) => accept(e.target.checked)} />
          <span>I understand this text is sent to an AI service to read it. It isn't saved, and the service is asked not to keep it.</span>
        </label>
        <span>{text.length}/{MAX}</span>
      </div>
      <Button type="button" variant="secondary" size="sm" className="mt-2" disabled={!ack || !text.trim()} loading={run.isPending} onClick={() => run.mutate()}>
        Interpret
      </Button>
      {unmodeled.length > 0 && (
        <div className="mt-3 text-xs text-slate-600">
          <p className="font-medium text-slate-700">Not included in the estimate:</p>
          <ul className="mt-1 list-disc pl-5">
            {unmodeled.map((u, i) => (
              <li key={i}>
                "{u.quote}": {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
