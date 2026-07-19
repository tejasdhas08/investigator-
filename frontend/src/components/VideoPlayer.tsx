import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { fmtMs } from "../api/client";
import type { TimelineEvent } from "../api/types";

export interface VideoPlayerHandle {
  seekMs: (ms: number) => void;
}

/** Custom player (Phase 2): dark chrome, scrubber with timeline markers showing
 * exactly where flagged events occur. Marker colors follow the global system:
 * red = suspicious, amber = requires human review, slate = other events. */
const VideoPlayer = forwardRef<VideoPlayerHandle, {
  src: string;
  events: TimelineEvent[];
}>(function VideoPlayer({ src, events }, ref) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [timeMs, setTimeMs] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [hover, setHover] = useState<{ x: number; label: string } | null>(null);

  useImperativeHandle(ref, () => ({
    seekMs: (ms: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.currentTime = ms / 1000;
      v.play().catch(() => {});
      v.scrollIntoView({ behavior: "smooth", block: "nearest" });
    },
  }));

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setTimeMs(v.currentTime * 1000);
    const onMeta = () => setDurationMs(v.duration * 1000);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
    };
  }, [src]);

  function barSeek(e: React.MouseEvent) {
    const bar = barRef.current;
    const v = videoRef.current;
    if (!bar || !v || !durationMs) return;
    const rect = bar.getBoundingClientRect();
    const frac = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    v.currentTime = (frac * durationMs) / 1000;
  }

  const markers = durationMs
    ? events
        .filter((e) => e.event_type !== "scene_change")
        .map((e) => ({
          id: e.id,
          left: (e.start_ms / durationMs) * 100,
          width: Math.max(((e.end_ms - e.start_ms) / durationMs) * 100, 0.5),
          cls: e.is_suspicious
            ? "bg-red-500"
            : e.requires_human_review
              ? "bg-amber-400"
              : "bg-slate-800/600",
          label: `${fmtMs(e.start_ms)} ${e.label.replace(/_/g, " ")}${e.person_label ? ` — ${e.person_label}` : ""}`,
          startMs: e.start_ms,
        }))
    : [];

  return (
    <div className="surface mb-4 overflow-hidden">
      <video ref={videoRef} src={src} className="max-h-[26rem] w-full bg-black"
             onClick={() => (playing ? videoRef.current?.pause() : videoRef.current?.play())} />
      <div className="px-3 pb-2 pt-1">
        <div
          ref={barRef}
          className="group relative mb-1.5 h-4 cursor-pointer"
          onClick={barSeek}
          onMouseLeave={() => setHover(null)}
        >
          <div className="absolute inset-x-0 top-1.5 h-1.5 rounded bg-slate-800" />
          <div className="absolute left-0 top-1.5 h-1.5 rounded bg-sky-500/70"
               style={{ width: `${durationMs ? (timeMs / durationMs) * 100 : 0}%` }} />
          {markers.map((m) => (
            <button
              key={m.id}
              type="button"
              title={m.label}
              onClick={(e) => {
                e.stopPropagation();
                const v = videoRef.current;
                if (v) v.currentTime = m.startMs / 1000;
              }}
              onMouseEnter={(e) => {
                const rect = barRef.current!.getBoundingClientRect();
                setHover({ x: e.clientX - rect.left, label: m.label });
              }}
              className={`absolute top-0 h-3 rounded-sm opacity-90 hover:h-4 hover:opacity-100 ${m.cls}`}
              style={{ left: `${m.left}%`, width: `${m.width}%`, minWidth: 3 }}
            />
          ))}
          {hover && (
            <div className="pointer-events-none absolute -top-7 z-10 -translate-x-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-0.5 text-[11px] text-slate-200 shadow"
                 style={{ left: hover.x }}>
              {hover.label}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={() => (playing ? videoRef.current?.pause() : videoRef.current?.play())}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-800 text-slate-200 hover:bg-slate-700"
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <span className="font-mono text-xs text-slate-400">
            {fmtMs(timeMs)} / {fmtMs(durationMs)}
          </span>
          <span className="ml-auto flex items-center gap-3 text-[11px] text-slate-500">
            <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-red-500" />suspicious</span>
            <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-amber-400" />needs review</span>
            <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-slate-800/600" />event</span>
          </span>
          <button
            onClick={() => videoRef.current?.requestFullscreen()}
            className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
          >
            ⛶ Fullscreen
          </button>
        </div>
      </div>
    </div>
  );
});

export default VideoPlayer;
