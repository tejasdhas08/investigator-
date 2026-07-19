import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Case, Page, Person, TimelineEvent, Video } from "../api/types";
import ChatPanel from "../components/ChatPanel";
import VideoPlayer, { type VideoPlayerHandle } from "../components/VideoPlayer";
import { DisclaimerBanner, Spinner, StatusPill } from "../components/shared";
import FlagsView from "./tabs/FlagsView";
import NarrativeView from "./tabs/NarrativeView";
import ObjectsView from "./tabs/ObjectsView";
import PeopleView from "./tabs/PeopleView";
import ReviewView from "./tabs/ReviewView";
import SuspectView from "./tabs/SuspectView";
import TimelineView from "./tabs/TimelineView";

export interface DashboardContext {
  caseData: Case;
  persons: Person[];
  events: TimelineEvent[];
  eventsById: Map<string, TimelineEvent>;
  onSeek: (ms: number) => void;
  refetchAll: () => void;
}

const TABS = [
  { path: "", label: "Narrative" },
  { path: "people", label: "People" },
  { path: "timeline", label: "Timeline" },
  { path: "flags", label: "Suspicious Activity" },
  { path: "objects", label: "Objects" },
  { path: "suspect", label: "Suspect Match" },
  { path: "review", label: "Review & Export" },
];

export default function CaseDashboard() {
  const { caseId } = useParams();
  const playerRef = useRef<VideoPlayerHandle>(null);
  const [chatOpen, setChatOpen] = useState(true);

  const caseQ = useQuery({ queryKey: ["case", caseId], queryFn: () => api<Case>(`/cases/${caseId}`) });
  const mediaQ = useQuery({ queryKey: ["media", caseId], queryFn: () => api<Video[]>(`/cases/${caseId}/media`) });
  const personsQ = useQuery({ queryKey: ["persons", caseId], queryFn: () => api<Person[]>(`/cases/${caseId}/persons`) });
  const eventsQ = useQuery({
    queryKey: ["timeline", caseId],
    queryFn: () => api<Page<TimelineEvent>>(`/cases/${caseId}/timeline?page_size=500`),
  });

  const onSeek = useCallback((ms: number) => {
    playerRef.current?.seekMs(ms);
  }, []);

  const events = eventsQ.data?.items ?? [];
  const eventsById = useMemo(() => {
    const m = new Map<string, TimelineEvent>();
    for (const e of events) {
      m.set(e.id, e);
      m.set(e.id.slice(0, 8), e);
    }
    return m;
  }, [events]);

  if (caseQ.isLoading || !caseQ.data) return <Spinner />;
  const caseData = caseQ.data;
  const video = mediaQ.data?.find((v) => v.stream_url && v.media_type === "video") ?? mediaQ.data?.[0];

  const ctx: DashboardContext = {
    caseData,
    persons: personsQ.data ?? [],
    events,
    eventsById,
    onSeek,
    refetchAll: () => {
      caseQ.refetch();
      personsQ.refetch();
      eventsQ.refetch();
    },
  };

  return (
    <div className="mx-auto max-w-7xl p-4">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <Link to="/cases" className="text-sm text-slate-500 underline">← Cases</Link>
          <h1 className="text-xl font-bold">
            {caseData.case_number} — {caseData.title} <StatusPill status={caseData.status} />
          </h1>
        </div>
        <button onClick={() => setChatOpen((v) => !v)}
                className="rounded border px-3 py-1.5 text-sm">
          {chatOpen ? "Hide" : "Show"} Q&A
        </button>
      </div>
      <DisclaimerBanner />

      <div className="flex gap-4">
        <div className="min-w-0 flex-1">
          {video?.stream_url && (
            video.media_type === "video" ? (
              <VideoPlayer ref={playerRef} src={video.stream_url} events={events} />
            ) : (
              <img src={video.stream_url} alt="uploaded evidence"
                   className="mb-4 max-h-96 rounded" />
            )
          )}
          <nav className="mb-4 flex flex-wrap gap-1 border-b border-slate-800">
            {TABS.map((t) => (
              <NavLink key={t.path} to={t.path} end={t.path === ""}
                       className={({ isActive }) =>
                         `px-3 py-2 text-sm font-medium ${isActive ? "border-b-2 border-slate-800 text-slate-100" : "text-slate-500 hover:text-slate-200"}`}>
                {t.label}
              </NavLink>
            ))}
          </nav>
          <Routes>
            <Route index element={<NarrativeView ctx={ctx} />} />
            <Route path="people" element={<PeopleView ctx={ctx} />} />
            <Route path="timeline" element={<TimelineView ctx={ctx} />} />
            <Route path="flags" element={<FlagsView ctx={ctx} />} />
            <Route path="objects" element={<ObjectsView ctx={ctx} />} />
            <Route path="suspect" element={<SuspectView ctx={ctx} />} />
            <Route path="review" element={<ReviewView ctx={ctx} />} />
          </Routes>
        </div>
        {chatOpen && (
          <div className="w-96 shrink-0">
            <ChatPanel caseId={caseData.id} caseStatus={caseData.status}
                       eventsById={eventsById} onSeek={onSeek} />
          </div>
        )}
      </div>
    </div>
  );
}
