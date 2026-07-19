import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, sha256Hex, uploadToPresigned } from "../api/client";
import type { Case } from "../api/types";

interface FileState {
  file: File;
  progress: "pending" | "hashing" | "uploading" | "done" | "error";
  videoId?: string;
  error?: string;
}

export default function NewCase() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [caseNumber, setCaseNumber] = useState("");
  const [title, setTitle] = useState("");
  const [context, setContext] = useState("");
  const [caseId, setCaseId] = useState<string | null>(null);
  const [files, setFiles] = useState<FileState[]>([]);
  const [suspectFile, setSuspectFile] = useState<File | null>(null);
  const [suspectName, setSuspectName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function createCase(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const c = await api<Case>("/cases", {
        method: "POST",
        body: { case_number: caseNumber, title, context_description: context },
      });
      setCaseId(c.id);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create case");
    } finally {
      setBusy(false);
    }
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    setFiles((prev) => [...prev, ...Array.from(list).map((file) => ({ file, progress: "pending" as const }))]);
  }

  async function uploadOne(fs: FileState, index: number): Promise<string> {
    const update = (patch: Partial<FileState>) =>
      setFiles((prev) => prev.map((f, i) => (i === index ? { ...f, ...patch } : f)));
    update({ progress: "hashing" });
    const sha = await sha256Hex(fs.file);
    const isVideo = /\.(mp4|mov|avi|mkv|webm)$/i.test(fs.file.name);
    const res = await api<{ video_id: string; upload_url: string }>(`/cases/${caseId}/media`, {
      method: "POST",
      body: {
        filename: fs.file.name,
        media_type: isVideo ? "video" : "photo",
        content_type: fs.file.type || "application/octet-stream",
        size_bytes: fs.file.size,
        sha256: sha,
      },
    });
    update({ progress: "uploading", videoId: res.video_id });
    await uploadToPresigned(res.upload_url, fs.file, fs.file.type || "application/octet-stream");
    update({ progress: "done" });
    return res.video_id;
  }

  async function uploadAllAndContinue() {
    setBusy(true);
    setError("");
    try {
      const ids: string[] = [];
      for (let i = 0; i < files.length; i++) {
        if (files[i].progress === "done" && files[i].videoId) {
          ids.push(files[i].videoId!);
          continue;
        }
        ids.push(await uploadOne(files[i], i));
      }
      // complete all but the last without starting; last one may start processing in step 3
      for (let i = 0; i < ids.length - 1; i++) {
        await api(`/cases/${caseId}/media/${ids[i]}/complete`, { method: "POST", body: {} });
      }
      sessionStorage.setItem(`csai_lastvideo_${caseId}`, ids[ids.length - 1]);
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function startAnalysis() {
    setBusy(true);
    setError("");
    try {
      if (suspectFile) {
        const sha = await sha256Hex(suspectFile);
        const ref = await api<{ suspect_reference_id: string; upload_url: string }>(
          `/cases/${caseId}/suspects`,
          {
            method: "POST",
            body: {
              display_name: suspectName || suspectFile.name,
              filename: suspectFile.name,
              content_type: suspectFile.type || "image/jpeg",
              size_bytes: suspectFile.size,
              sha256: sha,
            },
          },
        );
        await uploadToPresigned(ref.upload_url, suspectFile, suspectFile.type || "image/jpeg");
        await api(`/cases/${caseId}/suspects/${ref.suspect_reference_id}/complete`, { method: "POST", body: {} });
      }
      const lastVideo = sessionStorage.getItem(`csai_lastvideo_${caseId}`);
      await api(`/cases/${caseId}/media/${lastVideo}/complete`, {
        method: "POST",
        body: { start_processing: true },
      });
      navigate(`/cases/${caseId}/processing`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="mb-2 text-2xl font-bold">New Case</h1>
      <div className="mb-6 text-sm text-slate-500">Step {step} of 3</div>
      {error && <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-800">{error}</div>}

      {step === 1 && (
        <form onSubmit={createCase} className="rounded bg-white p-6 shadow-sm">
          <label className="mb-1 block text-sm font-medium">Case number</label>
          <input className="mb-3 w-full rounded border p-2" value={caseNumber}
                 onChange={(e) => setCaseNumber(e.target.value)} required placeholder="CASE-2026-014" />
          <label className="mb-1 block text-sm font-medium">Title</label>
          <input className="mb-3 w-full rounded border p-2" value={title}
                 onChange={(e) => setTitle(e.target.value)} required />
          <label className="mb-1 block text-sm font-medium">
            What do you believe happened? <span className="font-normal text-slate-500">(treated as a hypothesis, not evidence)</span>
          </label>
          <textarea className="mb-4 w-full rounded border p-2" rows={4} value={context}
                    onChange={(e) => setContext(e.target.value)} required />
          <button disabled={busy} className="rounded bg-slate-800 px-4 py-2 text-white disabled:opacity-50">
            Continue
          </button>
        </form>
      )}

      {step === 2 && (
        <div className="rounded bg-white p-6 shadow-sm">
          <label className="mb-2 block text-sm font-medium">Video / photo files</label>
          <input type="file" multiple accept="video/*,image/*" onChange={(e) => addFiles(e.target.files)}
                 className="mb-4 block text-sm" />
          <ul className="mb-4 space-y-1">
            {files.map((f, i) => (
              <li key={i} className="flex justify-between rounded bg-slate-50 px-3 py-1.5 text-sm">
                <span>{f.file.name}</span>
                <span className="text-slate-500">{f.progress}{f.error ? ` — ${f.error}` : ""}</span>
              </li>
            ))}
          </ul>
          <button disabled={busy || files.length === 0} onClick={uploadAllAndContinue}
                  className="rounded bg-slate-800 px-4 py-2 text-white disabled:opacity-50">
            {busy ? "Uploading…" : "Upload & continue"}
          </button>
        </div>
      )}

      {step === 3 && (
        <div className="rounded bg-white p-6 shadow-sm">
          <h2 className="mb-2 font-medium">Optional: suspect reference photo</h2>
          <p className="mb-3 text-xs text-slate-500">
            The tool reports algorithmic facial similarity only — never identity confirmation.
          </p>
          <input className="mb-3 w-full rounded border p-2 text-sm" placeholder="Reference label, e.g. 'Suspect from robbery #4411'"
                 value={suspectName} onChange={(e) => setSuspectName(e.target.value)} />
          <input type="file" accept="image/*" onChange={(e) => setSuspectFile(e.target.files?.[0] ?? null)}
                 className="mb-4 block text-sm" />
          <button disabled={busy} onClick={startAnalysis}
                  className="rounded bg-green-700 px-4 py-2 font-medium text-white disabled:opacity-50">
            {busy ? "Starting…" : "Start Analysis"}
          </button>
        </div>
      )}
    </div>
  );
}
