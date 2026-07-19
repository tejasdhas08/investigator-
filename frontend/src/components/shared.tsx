import { fmtMs } from "../api/client";

/** Section 7.1: every claim carries its confidence chip; 0.40-0.69 amber + review tooltip;
 * <0.40 only shown with the below-threshold watermark. */
export function ConfidenceChip({ confidence, startMs, onSeek }: {
  confidence: number;
  startMs?: number;
  onSeek?: (ms: number) => void;
}) {
  const pct = Math.round(confidence * 100);
  const cls =
    confidence >= 0.7
      ? "bg-slate-200 text-slate-700"
      : confidence >= 0.4
        ? "bg-amber-200 text-amber-900"
        : "bg-red-100 text-red-800 line-through";
  const title =
    confidence >= 0.7
      ? `Confidence ${pct}%`
      : confidence >= 0.4
        ? `Confidence ${pct}% — requires human review`
        : `Confidence ${pct}% — below evidentiary threshold, not used in analysis`;
  return (
    <button
      type="button"
      title={title}
      onClick={() => startMs !== undefined && onSeek?.(startMs)}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${cls} ${onSeek ? "cursor-pointer hover:ring-1 ring-slate-400" : "cursor-default"}`}
    >
      {startMs !== undefined && <span>{fmtMs(startMs)}</span>}
      <span>· {pct}%</span>
    </button>
  );
}

export function ReviewBadge() {
  return (
    <span className="ml-1 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
      Requires human review
    </span>
  );
}

/** Condensed disclaimer banner pinned atop every case tab (Section 7.5). */
export function DisclaimerBanner() {
  return (
    <div className="mb-3 rounded border border-red-300 bg-red-50 px-3 py-1.5 text-xs text-red-900">
      AI-assisted analysis — verify against footage before use. Not evidence.
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    complete: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    archived: "bg-slate-200 text-slate-600",
    created: "bg-slate-100 text-slate-700",
  };
  const cls = colors[status] ?? "bg-blue-100 text-blue-800 animate-pulse";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

export function Spinner() {
  return <div className="p-6 text-center text-sm text-slate-500">Loading…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{message}</div>;
}
