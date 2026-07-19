import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import type { ExportReport } from "../../api/types";
import EventDetailDrawer from "../../components/EventDetailDrawer";
import { ConfidenceChip, ReviewBadge } from "../../components/shared";
import { fmtMs } from "../../api/client";
import type { DashboardContext } from "../CaseDashboard";

export default function ReviewView({ ctx }: { ctx: DashboardContext }) {
  const qc = useQueryClient();
  const caseId = ctx.caseData.id;
  const [includeChat, setIncludeChat] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const tallies = { unreviewed: 0, approved: 0, rejected: 0, edited: 0 };
  for (const e of ctx.events) tallies[e.review_status]++;
  const needsReview = ctx.events
    .filter((e) => e.requires_human_review && e.review_status === "unreviewed")
    .sort((a, b) => a.start_ms - b.start_ms);

  const exportsQ = useQuery({
    queryKey: ["exports", caseId],
    queryFn: () => api<ExportReport[]>(`/cases/${caseId}/exports`),
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "pending") ? 4000 : false),
  });

  const createExport = useMutation({
    mutationFn: () => api(`/cases/${caseId}/exports`, { method: "POST", body: { includes_chat: includeChat } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exports", caseId] }),
  });

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        {Object.entries(tallies).map(([k, v]) => (
          <div key={k} className="surface p-3 text-center">
            <div className="text-2xl font-bold">{v}</div>
            <div className="text-xs uppercase text-slate-500">{k}</div>
          </div>
        ))}
      </div>

      <div className="surface p-4">
        <h3 className="mb-2 font-semibold">Items requiring human review ({needsReview.length})</h3>
        {needsReview.length === 0 && <p className="text-sm text-slate-500">Nothing pending review.</p>}
        <ul className="divide-y">
          {needsReview.map((e) => (
            <li key={e.id} className="flex items-center gap-2 py-2 text-sm">
              <ConfidenceChip confidence={e.confidence} startMs={e.start_ms} onSeek={ctx.onSeek} />
              <span className="flex-1">
                {e.event_type}: {e.description ?? e.label}
                {e.person_label && ` — Person ${e.person_label}`}
              </span>
              <ReviewBadge />
              <button onClick={() => setSelected(e.id)} className="text-sky-400 underline">Review</button>
            </li>
          ))}
        </ul>
      </div>

      <div className="surface p-4">
        <h3 className="mb-2 font-semibold">Export report (PDF)</h3>
        <p className="mb-2 text-xs text-slate-500">
          Exports are immutable snapshots. Unconfirmed AI content is marked; every page carries the disclaimer.
        </p>
        <label className="mb-3 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={includeChat} onChange={(e) => setIncludeChat(e.target.checked)} />
          Include Q&A transcript
        </label>
        <button onClick={() => createExport.mutate()} disabled={createExport.isPending}
                className="rounded bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500 disabled:opacity-50">
          Generate PDF
        </button>
        <ul className="mt-4 divide-y">
          {exportsQ.data?.map((e) => (
            <li key={e.id} className="flex items-center justify-between py-2 text-sm">
              <span>
                {new Date(e.created_at).toLocaleString()} — {e.status}
                {e.sha256 && <span className="ml-2 font-mono text-[10px] text-slate-400">sha256 {e.sha256.slice(0, 16)}…</span>}
              </span>
              {e.status === "complete" && (
                <a href={`/api/v1/cases/${caseId}/exports/${e.id}/download`} target="_blank" rel="noreferrer"
                   className="text-sky-400 underline">Download</a>
              )}
            </li>
          ))}
        </ul>
      </div>
      {selected && <EventDetailDrawer ctx={ctx} eventId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
