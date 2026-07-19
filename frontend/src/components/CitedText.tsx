import { fmtMs } from "../api/client";
import type { TimelineEvent } from "../api/types";

const CITATION_RE = /\[e:([0-9a-fA-F-]+),\s*conf\s*([0-9.]+)\]/g;

/** Renders narrative/chat text, converting [e:id, conf 0.xx] tokens into clickable
 * chips that seek the player to the cited event. */
export default function CitedText({ text, eventsById, onSeek }: {
  text: string;
  eventsById: Map<string, TimelineEvent>;
  onSeek?: (ms: number) => void;
}) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(CITATION_RE);
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    parts.push(<span key={key++}>{text.slice(last, m.index)}</span>);
    const id = m[1];
    const conf = parseFloat(m[2]);
    const event = eventsById.get(id) ?? [...eventsById.values()].find((e) => e.id.startsWith(id));
    const pct = Math.round(conf * 100);
    const cls = conf >= 0.7 ? "bg-slate-200 text-slate-700" : "bg-amber-200 text-amber-900";
    parts.push(
      <button
        key={key++}
        type="button"
        className={`mx-0.5 inline-flex rounded px-1 py-0 text-[11px] font-medium align-baseline ${cls} ${event && onSeek ? "hover:ring-1 ring-slate-400" : ""}`}
        title={conf < 0.7 ? `Confidence ${pct}% — requires human review` : `Confidence ${pct}%`}
        onClick={() => event && onSeek?.(event.start_ms)}
      >
        [{event ? fmtMs(event.start_ms) : "?"} · {pct}%]
      </button>,
    );
    last = m.index + m[0].length;
  }
  parts.push(<span key={key++}>{text.slice(last)}</span>);
  return <span className="leading-relaxed">{parts}</span>;
}
