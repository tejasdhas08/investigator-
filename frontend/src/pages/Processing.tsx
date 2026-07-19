import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseStatus } from "../api/types";

const STAGES = ["uploading", "queued", "ingesting", "detecting", "narrating", "complete"];

export default function Processing() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["status", caseId],
    queryFn: () => api<CaseStatus>(`/cases/${caseId}/status`),
    refetchInterval: 3000,
  });

  useEffect(() => {
    if (data?.status === "complete") navigate(`/cases/${caseId}`);
  }, [data?.status, caseId, navigate]);

  const activeIdx = data ? STAGES.indexOf(data.status) : 0;

  return (
    <div className="mx-auto max-w-xl p-10">
      <Link to="/cases" className="text-sm text-slate-500 underline">← Cases</Link>
      <h1 className="mb-8 mt-2 text-2xl font-bold">Analyzing footage…</h1>
      <ol className="space-y-3">
        {STAGES.map((s, i) => (
          <li key={s} className="flex items-center gap-3">
            <span className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold
              ${i < activeIdx ? "bg-green-600 text-white" : i === activeIdx ? "bg-blue-600 text-white animate-pulse" : "bg-slate-200 text-slate-500"}`}>
              {i < activeIdx ? "✓" : i + 1}
            </span>
            <span className="capitalize">{s}</span>
            {i === activeIdx && data?.stage_progress_pct != null && (
              <span className="text-sm text-slate-500">{data.stage_progress_pct}%</span>
            )}
          </li>
        ))}
      </ol>
      {data?.status === "failed" && (
        <div className="mt-8 rounded border border-red-300 bg-red-50 p-4">
          <p className="mb-2 font-medium text-red-800">Processing failed</p>
          <p className="mb-3 text-sm text-red-700">{data.failure_reason}</p>
          <button onClick={() => api(`/cases/${caseId}/narrative/regenerate`, { method: "POST" }).catch(() => {})}
                  className="rounded bg-red-700 px-3 py-1.5 text-sm text-white">Retry narrative</button>
        </div>
      )}
    </div>
  );
}
