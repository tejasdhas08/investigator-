import { fmtMs } from "../api/client";

/** Section 7.1 + Phase 2 design system: every claim carries its confidence chip.
 * >=70% steel; 40-69% amber + review tooltip; <40% red, below-threshold watermark. */
export function ConfidenceChip({ confidence, startMs, onSeek }: {
  confidence: number;
  startMs?: number;
  onSeek?: (ms: number) => void;
}) {
  const pct = Math.round(confidence * 100);
  const cls =
    confidence >= 0.7
      ? "bg-slate-700 text-slate-300"
      : confidence >= 0.4
        ? "bg-amber-900/70 text-amber-300 ring-1 ring-amber-700"
        : "bg-red-950 text-red-400 line-through";
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
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-xs font-medium ${cls} ${onSeek ? "cursor-pointer hover:ring-1 hover:ring-sky-500" : "cursor-default"}`}
    >
      {startMs !== undefined && <span>{fmtMs(startMs)}</span>}
      <span>· {pct}%</span>
    </button>
  );
}

export function ReviewBadge() {
  return (
    <span className="ml-1 rounded bg-amber-500/90 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-950">
      Requires human review
    </span>
  );
}

/** Condensed disclaimer banner pinned atop every case tab (Section 7.5) —
 * restyled for the dark theme, wording unchanged and non-negotiable. */
export function DisclaimerBanner() {
  return (
    <div className="mb-3 flex items-center gap-2 rounded-md border border-red-900 bg-red-950/60 px-3 py-1.5 text-xs text-red-300">
      <span aria-hidden>⚠</span>
      AI-assisted analysis — verify against footage before use. Not evidence.
    </div>
  );
}

export function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    complete: "bg-emerald-950 text-emerald-400 ring-1 ring-emerald-800",
    failed: "bg-red-950 text-red-400 ring-1 ring-red-800",
    archived: "bg-slate-800 text-slate-500",
    created: "bg-slate-800 text-slate-300",
  };
  const cls = colors[status] ?? "bg-sky-950 text-sky-300 ring-1 ring-sky-800 animate-pulse";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

export function Spinner() {
  return <div className="p-6 text-center text-sm text-slate-500">Loading…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-md border border-red-900 bg-red-950/60 p-3 text-sm text-red-300">{message}</div>;
}
