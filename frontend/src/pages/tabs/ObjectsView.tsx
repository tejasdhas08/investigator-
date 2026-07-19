import { useState } from "react";
import { fmtMs } from "../../api/client";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import { ConfidenceChip, ReviewBadge } from "../../components/shared";
import type { DashboardContext } from "../CaseDashboard";

const WEAPONS = new Set(["knife", "pistol", "rifle", "baseball bat", "scissors"]);

export default function ObjectsView({ ctx }: { ctx: DashboardContext }) {
  const [selected, setSelected] = useState<string | null>(null);
  const objects = ctx.events.filter((e) => e.event_type === "object_detection");
  const groups = new Map<string, typeof objects>();
  for (const e of objects) {
    const k = e.object_class ?? "unknown";
    groups.set(k, [...(groups.get(k) ?? []), e]);
  }
  const sorted = [...groups.entries()].sort(
    ([a], [b]) => Number(WEAPONS.has(b)) - Number(WEAPONS.has(a)) || a.localeCompare(b),
  );

  if (objects.length === 0)
    return <p className="text-sm text-slate-500">No notable objects were detected.</p>;

  return (
    <div className="space-y-4">
      {sorted.map(([cls, items]) => (
        <div key={cls} className="rounded bg-white p-4 shadow-sm">
          {WEAPONS.has(cls) && (
            <div className="mb-2 rounded bg-red-600 px-2 py-1 text-xs font-bold uppercase text-white">
              Possible weapon
            </div>
          )}
          <h3 className="mb-2 font-semibold capitalize">{cls} <span className="text-sm font-normal text-slate-500">({items.length})</span></h3>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {items.map((e) => (
              <button key={e.id} onClick={() => setSelected(e.id)} className="rounded border p-2 text-left hover:bg-slate-50">
                {e.evidence_frame_urls[0] && (
                  <img src={e.evidence_frame_urls[0]} alt={cls} className="mb-1 h-20 w-full rounded object-cover" />
                )}
                <div className="text-xs">
                  <ConfidenceChip confidence={e.confidence} startMs={e.start_ms} onSeek={ctx.onSeek} />
                  {e.requires_human_review && <ReviewBadge />}
                </div>
                <div className="text-[11px] text-slate-500">
                  {fmtMs(e.start_ms)}{e.person_label && ` · near Person ${e.person_label}`}
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
      {selected && <EventDetailDrawer ctx={ctx} eventId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
