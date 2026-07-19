import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fmtMs, sha256Hex, uploadToPresigned } from "../../api/client";
import type { SuspectReference } from "../../api/types";
import { Spinner } from "../../components/shared";
import type { DashboardContext } from "../CaseDashboard";

const VERDICT_STYLES: Record<string, string> = {
  match: "bg-red-100 text-red-800",
  possible_match: "bg-amber-100 text-amber-800",
  no_match: "bg-slate-100 text-slate-600",
};

export default function SuspectView({ ctx }: { ctx: DashboardContext }) {
  const qc = useQueryClient();
  const caseId = ctx.caseData.id;
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const refsQ = useQuery({
    queryKey: ["suspects", caseId],
    queryFn: () => api<SuspectReference[]>(`/cases/${caseId}/suspects`),
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.results.length === 0) ? 5000 : false,
  });

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a photo first");
      const sha = await sha256Hex(file);
      const ref = await api<{ suspect_reference_id: string; upload_url: string }>(
        `/cases/${caseId}/suspects`,
        {
          method: "POST",
          body: {
            display_name: name || file.name, filename: file.name,
            content_type: file.type || "image/jpeg", size_bytes: file.size, sha256: sha,
          },
        },
      );
      await uploadToPresigned(ref.upload_url, file, file.type || "image/jpeg");
      await api(`/cases/${caseId}/suspects/${ref.suspect_reference_id}/complete`, { method: "POST", body: {} });
    },
    onSuccess: () => {
      setFile(null);
      setName("");
      setError("");
      qc.invalidateQueries({ queryKey: ["suspects", caseId] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Upload failed"),
  });

  const reviewMatch = useMutation({
    mutationFn: ({ refId, resultId, action }: { refId: string; resultId: string; action: "confirm" | "reject" }) =>
      api(`/cases/${caseId}/suspects/${refId}/results/${resultId}/review`, { method: "POST", body: { action } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["suspects", caseId] });
      ctx.refetchAll();
    },
  });

  return (
    <div className="space-y-4">
      <div className="rounded bg-white p-4 shadow-sm">
        <h3 className="mb-2 font-semibold">Upload suspect reference photo</h3>
        {error && <div className="mb-2 rounded bg-red-50 p-2 text-sm text-red-800">{error}</div>}
        <input className="mb-2 w-full rounded border p-2 text-sm" placeholder="Reference label"
               value={name} onChange={(e) => setName(e.target.value)} />
        <input type="file" accept="image/*" className="mb-2 block text-sm"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button onClick={() => upload.mutate()} disabled={upload.isPending || !file}
                className="rounded bg-slate-800 px-4 py-2 text-sm text-white disabled:opacity-50">
          {upload.isPending ? "Uploading…" : "Upload & match"}
        </button>
      </div>

      {refsQ.isLoading ? <Spinner /> : refsQ.data?.map((ref) => (
        <div key={ref.id} className="rounded bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-3">
            {ref.photo_url && <img src={ref.photo_url} alt="reference" className="h-16 w-16 rounded object-cover" />}
            <div>
              <div className="font-semibold">{ref.display_name}</div>
              <div className="text-xs text-slate-500">
                Algorithmic similarity — not identity confirmation
              </div>
            </div>
          </div>
          {ref.results.length === 0 && (
            <p className="text-sm text-slate-500">Matching in progress (or no usable face was found in the photo)…</p>
          )}
          <div className="space-y-2">
            {ref.results.map((r) => (
              <div key={r.id} className="flex items-center gap-3 rounded border p-2">
                {ref.photo_url && <img src={ref.photo_url} alt="ref" className="h-12 w-12 rounded object-cover" />}
                <span className="text-slate-400">vs</span>
                {r.comparison_face_url ? (
                  <img src={r.comparison_face_url} alt={`Person ${r.person_label}`} className="h-12 w-12 rounded object-cover" />
                ) : (
                  <div className="flex h-12 w-12 items-center justify-center rounded bg-slate-200 text-[9px] text-slate-500">
                    no usable face
                  </div>
                )}
                <div className="flex-1 text-sm">
                  <div className="font-medium">Person {r.person_label}</div>
                  <div className="text-xs text-slate-500">
                    {r.cosine_similarity < 0
                      ? "no usable face — cannot compare"
                      : `similarity ${r.cosine_similarity.toFixed(2)}`}
                    {r.best_frame_ms != null && (
                      <button className="ml-2 text-blue-700 underline" onClick={() => ctx.onSeek(r.best_frame_ms!)}>
                        {fmtMs(r.best_frame_ms)}
                      </button>
                    )}
                  </div>
                </div>
                <span className={`rounded px-2 py-1 text-xs font-bold uppercase ${VERDICT_STYLES[r.verdict]}`}>
                  {r.verdict.replace("_", " ")} (algorithmic)
                </span>
                {r.verdict !== "no_match" && r.review_status === "unreviewed" && (
                  <div className="flex gap-1">
                    <button onClick={() => reviewMatch.mutate({ refId: ref.id, resultId: r.id, action: "confirm" })}
                            className="rounded bg-green-700 px-2 py-1 text-xs text-white">Confirm</button>
                    <button onClick={() => reviewMatch.mutate({ refId: ref.id, resultId: r.id, action: "reject" })}
                            className="rounded bg-red-700 px-2 py-1 text-xs text-white">Reject</button>
                  </div>
                )}
                {r.review_status !== "unreviewed" && (
                  <span className="text-xs text-slate-500">({r.review_status})</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
