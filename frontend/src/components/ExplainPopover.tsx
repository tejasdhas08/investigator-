import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EventExplanation } from "../api/types";

/** Phase 3 explainability drill-down: clicking a confidence score shows the signals
 * that produced it. Read-only — derived from stored detection data, no new claims. */
export default function ExplainPopover({ caseId, eventId, onClose }: {
  caseId: string;
  eventId: string;
  onClose: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["explain", caseId, eventId],
    queryFn: () => api<EventExplanation>(`/cases/${caseId}/events/${eventId}/explain`),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="surface w-[30rem] max-w-[92vw] p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-semibold text-sky-300">Why this confidence?</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200">✕</button>
        </div>
        {isLoading || !data ? (
          <p className="text-sm text-slate-500">Loading signals…</p>
        ) : (
          <>
            <p className="mb-3 text-xs text-slate-400">
              These are the stored detection signals behind this event's score. They explain the
              number — they are not additional findings, and none of this is a statement of fact.
            </p>
            <ul className="space-y-2">
              {data.signals.map((s, i) => (
                <li key={i} className="rounded-md border border-slate-800 bg-slate-950/40 p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-slate-300">{s.label}</span>
                    <span className="font-mono text-sm text-slate-100">
                      {typeof s.value === "boolean" ? (s.value ? "yes" : "no") : String(s.value)}
                    </span>
                  </div>
                  {s.detail && <p className="mt-0.5 text-xs text-slate-500">{s.detail}</p>}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
