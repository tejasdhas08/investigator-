import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtMs } from "../../api/client";
import { ConfidenceChip } from "../../components/shared";
import type { DashboardContext } from "../CaseDashboard";

export default function PeopleView({ ctx }: { ctx: DashboardContext }) {
  const { caseData, persons, onSeek, refetchAll } = ctx;
  const [editing, setEditing] = useState<string | null>(null);
  const [alias, setAlias] = useState("");

  const override = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) =>
      api(`/cases/${caseData.id}/persons/${id}/override`, { method: "POST", body }),
    onSuccess: () => {
      setEditing(null);
      refetchAll();
    },
  });

  return (
    <div>
      <div className="mb-4 rounded bg-white p-4 shadow-sm">
        <span className="text-lg font-bold">{caseData.person_count_total ?? persons.length} people detected</span>
        <span className="ml-3 text-sm text-slate-600">
          {caseData.person_count_male ?? 0} male est. · {caseData.person_count_female ?? 0} female est. ·{" "}
          {caseData.person_count_unknown_gender ?? 0} unknown
        </span>
        <p className="mt-1 text-xs text-slate-500">
          Gender values are algorithmic estimates. Labels A, B, C… are anonymous tracking labels, not identifications.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        {persons.map((p) => (
          <div key={p.id} className="rounded bg-white p-4 shadow-sm">
            <div className="mb-2 flex items-start gap-3">
              {p.face_crop_url ? (
                <img src={p.face_crop_url} alt={`Person ${p.label} face`}
                     className="h-20 w-20 rounded object-cover" />
              ) : (
                <div className="flex h-20 w-20 items-center justify-center rounded bg-slate-200 text-center text-[10px] text-slate-500">
                  face not visible in footage
                </div>
              )}
              <div>
                <div className="text-2xl font-bold">{p.label}</div>
                {p.display_alias && <div className="text-xs text-slate-600">{p.display_alias}</div>}
                {p.is_suspect_match && (
                  <span className="mt-1 inline-block rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-bold text-purple-800">
                    CONFIRMED SUSPECT SIMILARITY
                  </span>
                )}
              </div>
            </div>
            <dl className="space-y-1 text-sm">
              <div>
                <dt className="inline text-slate-500">Gender est.: </dt>
                <dd className="inline">
                  {p.gender_estimate}
                  {p.gender_confidence != null && <> <ConfidenceChip confidence={p.gender_confidence} /></>}
                  {p.gender_human_override && (
                    <span className="ml-1 text-xs text-blue-700">(human override: {p.gender_human_override})</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Appearance: </dt>
                <dd className="inline">{p.appearance_description ?? "—"}</dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Present: </dt>
                <dd className="inline">
                  <button className="text-blue-700 underline" onClick={() => onSeek(p.first_seen_ms ?? 0)}>
                    {fmtMs(p.first_seen_ms)}
                  </button>{" "}
                  – {fmtMs(p.last_seen_ms)}
                  {" "}<ConfidenceChip confidence={p.detection_confidence_avg} />
                </dd>
              </div>
            </dl>
            {p.activity_summary && (
              <p className="mt-2 border-t pt-2 text-xs text-slate-700">{p.activity_summary}</p>
            )}
            <div className="mt-2 flex items-center gap-2 text-xs">
              <Link to={`../timeline?person=${p.label}`} className="text-blue-700 underline">Timeline</Link>
              {editing === p.id ? (
                <>
                  <input className="w-28 rounded border p-1" value={alias}
                         onChange={(e) => setAlias(e.target.value)} placeholder="e.g. A (victim)" />
                  <button className="text-green-700 underline"
                          onClick={() => override.mutate({ id: p.id, body: { display_alias: alias } })}>Save</button>
                </>
              ) : (
                <button className="text-slate-500 underline"
                        onClick={() => { setEditing(p.id); setAlias(p.display_alias ?? ""); }}>
                  Set alias
                </button>
              )}
              <select className="rounded border p-1" value={p.gender_human_override ?? ""}
                      onChange={(e) => override.mutate({ id: p.id, body: { gender_estimate: e.target.value } })}>
                <option value="" disabled>Override gender…</option>
                <option value="male">male</option><option value="female">female</option>
                <option value="unknown">unknown</option>
              </select>
            </div>
          </div>
        ))}
        {persons.length === 0 && (
          <p className="text-sm text-slate-500">No persons were detected in the analyzed footage.</p>
        )}
      </div>
    </div>
  );
}
