import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { User } from "../api/types";
import { Spinner } from "../components/shared";
import { useAuth } from "../state/auth";

export default function AdminPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "investigator" });
  const [error, setError] = useState("");

  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/admin/users"),
    enabled: user?.role === "admin",
  });
  const chainQ = useQuery({
    queryKey: ["chain"],
    queryFn: () => api<{ ok: boolean; first_broken_row_id: number | null }>("/admin/audit/verify"),
    enabled: user?.role === "admin",
  });
  const create = useMutation({
    mutationFn: () => api("/admin/users", { method: "POST", body: form }),
    onSuccess: () => {
      setForm({ email: "", full_name: "", password: "", role: "investigator" });
      setError("");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Failed"),
  });

  if (user?.role !== "admin") return <div className="p-10 text-center">Admin access required.</div>;

  return (
    <div className="mx-auto max-w-4xl p-6">
      <Link to="/cases" className="text-sm text-slate-500 underline">← Cases</Link>
      <h1 className="mb-6 mt-2 text-2xl font-bold">Administration</h1>

      <div className={`mb-6 rounded p-3 text-sm ${chainQ.data?.ok ? "bg-emerald-950/60 text-emerald-300 ring-1 ring-emerald-800" : "bg-red-50 text-red-300"}`}>
        Audit chain: {chainQ.isLoading ? "verifying…" : chainQ.data?.ok ? "intact ✓" : `BROKEN at row ${chainQ.data?.first_broken_row_id}`}
      </div>

      <div className="mb-6 surface p-4">
        <h2 className="mb-3 font-semibold">Create user</h2>
        {error && <div className="mb-2 rounded-md bg-red-950/60 p-2 text-sm text-red-300">{error}</div>}
        <div className="grid grid-cols-2 gap-2">
          <input className="rounded-md border p-2 text-sm" placeholder="Email" value={form.email}
                 onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="rounded-md border p-2 text-sm" placeholder="Full name" value={form.full_name}
                 onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <input className="rounded-md border p-2 text-sm" type="password" placeholder="Password" value={form.password}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <select className="rounded-md border p-2 text-sm" value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="investigator">investigator</option>
            <option value="supervisor">supervisor</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <button onClick={() => create.mutate()} className="mt-3 rounded bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500">
          Create
        </button>
      </div>

      {usersQ.isLoading ? <Spinner /> : (
        <table className="w-full surface overflow-hidden">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
              <th className="p-3">Email</th><th className="p-3">Name</th><th className="p-3">Role</th>
            </tr>
          </thead>
          <tbody>
            {usersQ.data?.map((u) => (
              <tr key={u.id} className="border-b border-slate-800 last:border-0">
                <td className="p-3 text-sm">{u.email}</td>
                <td className="p-3 text-sm">{u.full_name}</td>
                <td className="p-3 text-sm">{u.role}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
