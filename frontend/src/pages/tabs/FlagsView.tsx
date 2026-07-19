import { useState } from "react";
import { fmtMs } from "../../api/client";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import { ConfidenceChip, ReviewBadge } from "../../components/shared";
import type { DashboardContext } from "../CaseDashboard";

const SEVERITY_ORDER = ["weapon_visible", "person_down", "struggle", "physical_contact"];

export default function FlagsView({ ctx }: { ctx: DashboardContext }) {
  const [selected, setSelected] = useState<string | null>(null);
  const flags = ctx.events
    .filter((e) => e.is_suspicious)
    .sort((a, b) => {
      const sa = SEVERITY_ORDER.indexOf(a.label);
      const sb = SEVERITY_ORDER.indexOf(b.label);
      return (sa === -1 ? 99 : sa) - (sb === -1 ? 99 : sb) || a.start_ms - b.start_ms;
    });

  if (flags.length === 0)
    return <p className="text-sm text-slate-500">No suspicious activity was flagged in this footage.</p>;

  return (
    <div className="space-y-3">
      {flags.map((e) => (
        <div key={e.id}
             className={`rounded border-l-4 bg-slate-900 p-4 shadow-sm ${SEVERITY_ORDER.indexOf(e.label) <= 1 && SEVERITY_ORDER.includes(e.label) ? "border-red-600" : "border-amber-500"} ${e.review_status === "rejected" ? "opacity-40" : ""}`}>
          <div className="mb-1 flex items-center gap-2">
            <span className="font-semibold">{e.label.replace(/_/g, " ")}</span>
            <ConfidenceChip confidence={e.confidence} startMs={e.start_ms} onSeek={ctx.onSeek} />
            {e.requires_human_review && <ReviewBadge />}
            {e.review_status !== "unreviewed" && (
              <span className="text-xs text-slate-500">({e.review_status})</span>
            )}
          </div>
          <p className="mb-2 text-sm">{e.description}
            {e.person_label && <span className="text-slate-500"> — Person {e.person_label}
              {e.target_person_label && ` → Person ${e.target_person_label}`}</span>}
          </p>
          <div className="flex items-center gap-2">
            {e.evidence_frame_urls.slice(0, 3).map((u, i) => (
              <img key={i} src={u} alt="evidence" className="h-16 rounded border" />
            ))}
            <span className="text-xs text-slate-500">{fmtMs(e.start_ms)}–{fmtMs(e.end_ms)}</span>
            <button onClick={() => setSelected(e.id)} className="text-xs text-sky-400 underline">Review</button>
          </div>
        </div>
      ))}
      {selected && <EventDetailDrawer ctx={ctx} eventId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
