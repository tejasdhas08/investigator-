import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ChatMessage, Page, TimelineEvent } from "../api/types";
import CitedText from "./CitedText";

const EXAMPLES = [
  "Who was present when Person B fell?",
  "Is there any evidence of a weapon?",
  "What did Person C do throughout the footage?",
];

export default function ChatPanel({ caseId, caseStatus, eventsById, onSeek }: {
  caseId: string;
  caseStatus: string;
  eventsById: Map<string, TimelineEvent>;
  onSeek: (ms: number) => void;
}) {
  const qc = useQueryClient();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const historyQ = useQuery({
    queryKey: ["chat", caseId],
    queryFn: () => api<Page<ChatMessage>>(`/cases/${caseId}/chat?page_size=200`),
  });

  const ask = useMutation({
    mutationFn: (question: string) =>
      api<{ message: ChatMessage }>(`/cases/${caseId}/chat`, { method: "POST", body: { question } }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["chat", caseId] }),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [historyQ.data?.items.length, ask.isPending]);

  const messages = historyQ.data?.items ?? [];

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || ask.isPending) return;
    setInput("");
    ask.mutate(q);
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col rounded border bg-slate-900 shadow-sm">
      <div className="border-b px-3 py-2">
        <div className="text-sm font-semibold">Case Q&A</div>
        <div className="text-[11px] text-red-300">AI-assisted analysis — verify against footage. Not evidence.</div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && !ask.isPending && (
          <div className="text-sm text-slate-500">
            <p className="mb-2">Ask a follow-up question about this case. Try:</p>
            <ul className="space-y-1">
              {EXAMPLES.map((ex) => (
                <li key={ex}>
                  <button className="text-left text-sky-400 underline" onClick={() => setInput(ex)}>{ex}</button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id}
               className={`rounded-lg p-2.5 text-sm ${m.role === "user" ? "ml-6 bg-slate-800" : "mr-2 border bg-slate-900"}`}>
            <CitedText text={m.content} eventsById={eventsById} onSeek={onSeek} />
          </div>
        ))}
        {ask.isPending && <div className="text-sm text-slate-400">Answering…</div>}
        {ask.isError && (
          <div className="rounded bg-red-50 p-2 text-xs text-red-300">
            {(ask.error as Error).message || "Q&A temporarily unavailable — try again shortly."}
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={submit} className="flex gap-2 border-t p-2">
        <input value={input} onChange={(e) => setInput(e.target.value)}
               disabled={caseStatus !== "complete"}
               placeholder={caseStatus === "complete" ? "Ask about this case…" : "Available once analysis completes"}
               className="flex-1 rounded-md border p-2 text-sm" />
        <button disabled={ask.isPending || caseStatus !== "complete"}
                className="rounded bg-sky-600 px-3 text-sm text-white hover:bg-sky-500 disabled:opacity-50">Send</button>
      </form>
    </div>
  );
}
