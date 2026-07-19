import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fmtMs } from "../../api/client";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import type { DashboardContext } from "../CaseDashboard";

const TYPE_COLORS: Record<string, string> = {
  action: "bg-blue-200",
  interaction: "bg-purple-300",
  object_detection: "bg-teal-200",
  suspicious_flag: "bg-red-300",
  person_appearance: "bg-green-200",
  person_exit: "bg-slate-300",
  scene_change: "bg-yellow-200",
};

export default function TimelineView({ ctx }: { ctx: DashboardContext }) {
  const { persons, events } = ctx;
  const [params] = useSearchParams();
  const [personFilter, setPersonFilter] = useState(params.get("person") ?? "");
  const [typeFilter, setTypeFilter] = useState("");
  const [suspiciousOnly, setSuspiciousOnly] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const maxMs = Math.max(...events.map((e) => e.end_ms), 1000);
  const filtered = events.filter(
    (e) =>
      (!personFilter || e.person_label === personFilter || e.target_person_label === personFilter) &&
      (!typeFilter || e.event_type === typeFilter) &&
      (!suspiciousOnly || e.is_suspicious),
  );

  const lanes: { name: string; events: typeof events }[] = [
    ...persons.map((p) => ({
      name: `Person ${p.label}`,
      events: filtered.filter((e) => e.person_label === p.label && e.event_type !== "object_detection" && e.event_type !== "suspicious_flag"),
    })),
    { name: "Objects", events: filtered.filter((e) => e.event_type === "object_detection") },
    { name: "Flags", events: filtered.filter((e) => e.event_type === "suspicious_flag") },
  ];

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2 text-sm">
        <select value={personFilter} onChange={(e) => setPersonFilter(e.target.value)} className="rounded border p-1.5">
          <option value="">All persons</option>
          {persons.map((p) => <option key={p.id} value={p.label}>Person {p.label}</option>)}
        </select>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="rounded border p-1.5">
          <option value="">All types</option>
          {Object.keys(TYPE_COLORS).map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={suspiciousOnly} onChange={(e) => setSuspiciousOnly(e.target.checked)} />
          Suspicious only
        </label>
      </div>

      <div className="space-y-2 overflow-x-auto surface p-4">
        {lanes.map((lane) => (
          <div key={lane.name} className="flex items-center gap-2">
            <div className="w-28 shrink-0 text-xs font-medium text-slate-400">{lane.name}</div>
            <div className="relative h-7 flex-1 rounded bg-slate-800">
              {lane.events.map((e) => (
                <button
                  key={e.id}
                  title={`${fmtMs(e.start_ms)} ${e.label} (${Math.round(e.confidence * 100)}%)`}
                  onClick={() => setSelected(e.id)}
                  className={`absolute top-0.5 h-6 min-w-[6px] rounded ${TYPE_COLORS[e.event_type] ?? "bg-slate-300"}
                    ${e.is_suspicious ? "ring-2 ring-red-500" : ""}
                    ${e.requires_human_review ? "border-2 border-amber-500" : ""}
                    ${e.review_status === "rejected" ? "opacity-30" : ""}`}
                  style={{
                    left: `${(e.start_ms / maxMs) * 100}%`,
                    width: `${Math.max(((e.end_ms - e.start_ms) / maxMs) * 100, 0.6)}%`,
                  }}
                />
              ))}
            </div>
          </div>
        ))}
        <div className="ml-30 flex justify-between pl-28 text-[10px] text-slate-400">
          <span>00:00</span><span>{fmtMs(maxMs)}</span>
        </div>
      </div>

      <div className="mt-2 flex gap-3 text-[11px] text-slate-500">
        <span><span className="mr-1 inline-block h-3 w-3 rounded ring-2 ring-red-500" /> suspicious</span>
        <span><span className="mr-1 inline-block h-3 w-3 rounded border-2 border-amber-500" /> requires human review</span>
      </div>

      {selected && (
        <EventDetailDrawer ctx={ctx} eventId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
