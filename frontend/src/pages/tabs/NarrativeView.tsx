import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, fmtMs } from "../../api/client";
import CitedText from "../../components/CitedText";
import HypothesisCheck from "../../components/HypothesisCheck";
import { ErrorBox, ReviewBadge } from "../../components/shared";
import type { DashboardContext } from "../CaseDashboard";

export default function NarrativeView({ ctx }: { ctx: DashboardContext }) {
  const { caseData, eventsById, onSeek } = ctx;
  const navigate = useNavigate();
  const narrative = caseData.narrative_json;
  const hasReviews = ctx.events.some((e) => e.review_status !== "unreviewed");

  const regenerate = useMutation({
    mutationFn: () => api(`/cases/${caseData.id}/narrative/regenerate`, { method: "POST" }),
    onSuccess: () => navigate(`/cases/${caseData.id}/processing`),
  });

  if (!narrative) return <ErrorBox message="Narrative not generated yet." />;

  return (
    <div className="space-y-5">
      <div className="surface p-4">
        <p className="italic text-slate-300">{narrative.overall_summary}</p>
      </div>

      {narrative.hypothesis_check && (
        <HypothesisCheck check={narrative.hypothesis_check} eventsById={eventsById} onSeek={onSeek} />
      )}

      {narrative.narrative_sections.map((s) => (
        <section key={s.section_index} className="surface p-4">
          <h3 className="mb-1 font-semibold">
            {s.heading}{" "}
            <span className="text-xs font-normal text-slate-400">
              {fmtMs(s.time_range_ms[0])}–{fmtMs(s.time_range_ms[1])} · AI
            </span>
          </h3>
          <p className="text-sm"><CitedText text={s.text} eventsById={eventsById} onSeek={onSeek} /></p>
        </section>
      ))}

      {narrative.uncertainties.length > 0 && (
        <section className="rounded border border-amber-300 bg-amber-50 p-4">
          <h3 className="mb-2 font-semibold text-amber-900">Uncertainties <ReviewBadge /></h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-amber-900">
            {narrative.uncertainties.map((u, i) => <li key={i}>{u.text}</li>)}
          </ul>
        </section>
      )}

      {narrative.evidence_gaps.length > 0 && (
        <section className="surface p-4">
          <h3 className="mb-2 font-semibold">Evidence gaps</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {narrative.evidence_gaps.map((g, i) => <li key={i}>{g}</li>)}
          </ul>
        </section>
      )}

      {(narrative.human_edits?.length ?? 0) > 0 && (
        <section className="surface p-4">
          <h3 className="mb-2 font-semibold">Human edits (AI✎)</h3>
          {narrative.human_edits!.map((e, i) => (
            <p key={i} className="mb-1 text-sm">
              <span className="text-slate-400 line-through">{e.original_text}</span>{" "}
              → <span>{e.edited_text}</span>
            </p>
          ))}
        </section>
      )}

      <button onClick={() => regenerate.mutate()} disabled={!hasReviews || regenerate.isPending}
              title={hasReviews ? "" : "Enabled after review actions"}
              className="rounded border px-4 py-2 text-sm disabled:opacity-40">
        Regenerate narrative (honors review decisions)
      </button>

      <p className="border-t pt-3 text-[11px] leading-snug text-slate-500">{narrative.disclaimer}</p>
    </div>
  );
}
