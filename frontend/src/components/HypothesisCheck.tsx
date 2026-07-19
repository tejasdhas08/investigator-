import type { HypothesisCheck as HC, TimelineEvent } from "../api/types";
import CitedText from "./CitedText";
import { fmtMs } from "../api/client";

const VERDICT: Record<string, { label: string; cls: string; icon: string }> = {
  supported: { label: "Supported by footage", cls: "bg-emerald-950/60 text-emerald-300 ring-emerald-800", icon: "✓" },
  partially_supported: { label: "Partially supported", cls: "bg-amber-950/50 text-amber-300 ring-amber-800", icon: "≈" },
  contradicted: { label: "Contradicted by footage", cls: "bg-red-950/60 text-red-300 ring-red-800", icon: "✗" },
  unsupported: { label: "No evidence either way", cls: "bg-slate-800 text-slate-400 ring-slate-700", icon: "—" },
};

/** Phase 3 flagship: the investigator's typed context checked, claim by claim, against
 * what the timeline actually supports. Surfaced as its own prominent section. */
export default function HypothesisCheck({ check, eventsById, onSeek }: {
  check: HC;
  eventsById: Map<string, TimelineEvent>;
  onSeek?: (ms: number) => void;
}) {
  if (!check?.claims?.length) return null;
  return (
    <section className="surface border-l-4 border-l-sky-600 p-4">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="font-semibold text-sky-300">Hypothesis vs. Evidence</h3>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
          your account, checked against the footage
        </span>
      </div>
      <p className="mb-3 text-xs italic text-slate-400">"{check.hypothesis_text}"</p>
      <ul className="space-y-2">
        {check.claims.map((c, i) => {
          const v = VERDICT[c.verdict] ?? VERDICT.unsupported;
          return (
            <li key={i} className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
              <div className="mb-1 flex items-start justify-between gap-2">
                <span className="text-sm text-slate-200">{c.claim}</span>
                <span className={`shrink-0 rounded px-2 py-0.5 text-[11px] font-semibold ring-1 ${v.cls}`}>
                  {v.icon} {v.label}
                </span>
              </div>
              <p className="text-xs text-slate-400">{c.explanation}</p>
              {c.cited_event_ids.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {c.cited_event_ids.map((id) => {
                    const e = eventsById.get(id) ?? eventsById.get(id.slice(0, 8));
                    if (!e) return null;
                    return (
                      <button key={id} onClick={() => onSeek?.(e.start_ms)}
                              className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-sky-300 hover:bg-slate-700">
                        {fmtMs(e.start_ms)} · {Math.round(e.confidence * 100)}%
                      </button>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {check.overall && (
        <p className="mt-3 border-t border-slate-800 pt-2 text-xs text-slate-400">{check.overall}</p>
      )}
    </section>
  );
}
