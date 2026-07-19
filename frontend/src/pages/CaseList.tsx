import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { CaseListItem, Page } from "../api/types";
import { Spinner, StatusPill } from "../components/shared";
import { useAuth } from "../state/auth";

const PROCESSING = ["uploading", "queued", "ingesting", "detecting", "narrating"];

export default function CaseList() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["cases", q, status],
    queryFn: () =>
      api<Page<CaseListItem>>(
        `/cases?page=1&page_size=100${q ? `&q=${encodeURIComponent(q)}` : ""}${status ? `&status=${status}` : ""}`,
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some((c) => PROCESSING.includes(c.status)) ? 10000 : false,
  });

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Cases</h1>
        <div className="flex items-center gap-3">
          {user?.role === "admin" && <Link to="/admin" className="text-sm text-slate-400 underline">Admin</Link>}
          <span className="text-sm text-slate-500">{user?.full_name} ({user?.role})</span>
          <button onClick={() => logout().then(() => navigate("/login"))}
                  className="text-sm text-slate-400 underline">Sign out</button>
          <Link to="/cases/new" className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500">
            New Case
          </Link>
        </div>
      </div>
      <div className="mb-4 flex gap-2">
        <input placeholder="Search title or case number…" value={q} onChange={(e) => setQ(e.target.value)}
               className="w-72 rounded-md border p-2 text-sm" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border p-2 text-sm">
          <option value="">All statuses</option>
          {["created", "queued", "ingesting", "detecting", "narrating", "complete", "failed", "archived"].map(
            (s) => <option key={s} value={s}>{s}</option>,
          )}
        </select>
      </div>
      {isLoading ? <Spinner /> : (
        <table className="w-full surface overflow-hidden">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
              <th className="p-3">Case #</th><th className="p-3">Title</th>
              <th className="p-3">Status</th><th className="p-3">People</th><th className="p-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((c) => (
              <tr key={c.id} className="cursor-pointer border-b border-slate-800 last:border-0 hover:bg-slate-800/60"
                  onClick={() => navigate(PROCESSING.includes(c.status) || c.status === "created"
                    ? `/cases/${c.id}/processing` : `/cases/${c.id}`)}>
                <td className="p-3 font-mono text-sm">{c.case_number}</td>
                <td className="p-3 text-sm">{c.title}</td>
                <td className="p-3"><StatusPill status={c.status} /></td>
                <td className="p-3 text-sm">{c.person_count_total ?? "—"}</td>
                <td className="p-3 text-sm text-slate-500">{new Date(c.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {data?.items.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-sm text-slate-500">No cases yet.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
