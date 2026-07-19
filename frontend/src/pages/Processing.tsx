import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseStatus } from "../api/types";
import { DisclaimerBanner } from "../components/shared";

const STAGES: { key: string; label: string; detail: string }[] = [
  { key: "uploading", label: "Uploading", detail: "Transferring media to secure storage." },
  { key: "queued", label: "Queued", detail: "Waiting for a processing slot." },
  { key: "ingesting", label: "Ingesting", detail: "Extracting frames and audio, checking integrity, detecting scene cuts." },
  { key: "detecting", label: "Detecting", detail: "Real inference: faces, person tracking, objects, and attributes across every frame." },
  { key: "narrating", label: "Narrating", detail: "Synthesizing the cited narrative and hypothesis check from the evidence timeline." },
  { key: "complete", label: "Complete", detail: "Done." },
];

export default function Processing() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["status", caseId],
    queryFn: () => api<CaseStatus>(`/cases/${caseId}/status`),
    refetchInterval: 2000,
  });

  useEffect(() => {
    if (data?.status === "complete") navigate(`/cases/${caseId}`);
  }, [data?.status, caseId, navigate]);

  const activeIdx = data ? STAGES.findIndex((s) => s.key === data.status) : 0;
  const pct = data?.stage_progress_pct;

  return (
    <div className="mx-auto max-w-2xl p-10">
      <Link to="/cases" className="text-sm text-slate-500 underline">← Cases</Link>
      <h1 className="mb-1 mt-2 text-2xl font-bold">Analyzing footage…</h1>
      <p className="mb-6 text-sm text-slate-500">
        Real detection runs frame by frame on CPU — larger videos take longer. Live progress below.
      </p>
      <DisclaimerBanner />
      <ol className="space-y-3">
        {STAGES.map((s, i) => {
          const done = i < activeIdx;
          const active = i === activeIdx;
          return (
            <li key={s.key} className="surface flex items-start gap-3 p-3">
              <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold
                ${done ? "bg-emerald-600 text-white" : active ? "bg-sky-500 text-white" : "bg-slate-800 text-slate-500"}`}>
                {done ? "✓" : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={`font-medium ${active ? "text-sky-300" : done ? "text-slate-300" : "text-slate-500"}`}>
                    {s.label}
                  </span>
                  {active && pct != null && <span className="text-xs text-slate-400">{pct}%</span>}
                </div>
                {active && (
                  <>
                    <p className="mt-0.5 text-xs text-slate-500">{s.detail}</p>
                    {pct != null && (
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded bg-slate-800">
                        <div className="h-full rounded bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
                      </div>
                    )}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {data?.status === "failed" && (
        <div className="mt-8 rounded-md border border-red-900 bg-red-950/60 p-4">
          <p className="mb-2 font-medium text-red-300">Processing failed</p>
          <p className="mb-3 text-sm text-red-400">{data.failure_reason}</p>
          <button onClick={() => api(`/cases/${caseId}/narrative/regenerate`, { method: "POST" }).catch(() => {})}
                  className="rounded bg-red-700 px-3 py-1.5 text-sm text-white hover:bg-red-600">Retry narrative</button>
        </div>
      )}
    </div>
  );
}
