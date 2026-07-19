import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmtMs } from "../api/client";
import type { DashboardContext } from "../pages/CaseDashboard";
import { ConfidenceChip, ReviewBadge } from "./shared";

export default function EventDetailDrawer({ ctx, eventId, onClose }: {
  ctx: DashboardContext;
  eventId: string;
  onClose: () => void;
}) {
  const event = ctx.eventsById.get(eventId);
  const [note, setNote] = useState("");
  const review = useMutation({
    mutationFn: (action: "approve" | "reject" | "edit") =>
      api(`/cases/${ctx.caseData.id}/events/${eventId}/review`, {
        method: "POST",
        body: { action, human_note: note || null },
      }),
    onSuccess: () => {
      ctx.refetchAll();
      onClose();
    },
  });

  if (!event) return null;
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-[28rem] overflow-y-auto border-l bg-white p-5 shadow-2xl">
      <div className="mb-3 flex items-start justify-between">
        <h3 className="font-semibold">
          {event.event_type.replace("_", " ")}: {event.label}
          {event.requires_human_review && <ReviewBadge />}
        </h3>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-800">✕</button>
      </div>
      <p className="mb-2 text-sm">{event.description}</p>
      <p className="mb-2 text-sm">
        <ConfidenceChip confidence={event.confidence} startMs={event.start_ms} onSeek={ctx.onSeek} />
        <span className="ml-2 text-slate-500">{fmtMs(event.start_ms)}–{fmtMs(event.end_ms)}</span>
      </p>
      {event.person_label && (
        <p className="mb-2 text-sm text-slate-600">
          Person {event.person_label}
          {event.target_person_label && <> → Person {event.target_person_label}
            {!event.actor_direction && <span className="text-amber-700"> (initiation unclear)</span>}</>}
        </p>
      )}
      {event.confidence < 0.4 && (
        <p className="mb-2 rounded bg-red-50 p-2 text-xs text-red-800">
          Below evidentiary threshold — not used in analysis.
        </p>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2">
        {event.evidence_frame_urls.map((u, i) => (
          <img key={i} src={u} alt={`evidence frame ${i + 1}`} className="rounded border" />
        ))}
      </div>
      <p className="mb-2 text-xs text-slate-500">Review status: <strong>{event.review_status}</strong>
        {event.human_note && <> — note: {event.human_note}</>}</p>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                placeholder="Optional note (required for Edit)"
                className="mb-2 w-full rounded border p-2 text-sm" />
      <div className="flex gap-2">
        <button onClick={() => review.mutate("approve")}
                className="rounded bg-green-700 px-3 py-1.5 text-sm text-white">Approve</button>
        <button onClick={() => review.mutate("reject")}
                className="rounded bg-red-700 px-3 py-1.5 text-sm text-white">Reject</button>
        <button onClick={() => review.mutate("edit")} disabled={!note}
                className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white disabled:opacity-40">Edit</button>
      </div>
    </div>
  );
}
