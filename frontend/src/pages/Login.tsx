import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../state/auth";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needsTotp, setNeedsTotp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password, totp || undefined);
      navigate("/cases");
    } catch (err) {
      if (err instanceof ApiError && err.code === "totp_required") {
        setNeedsTotp(true);
        setError("Enter your authenticator code.");
      } else {
        setError(err instanceof Error ? err.message : "Login failed");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form onSubmit={submit} className="w-96 surface p-8">
        <h1 className="mb-1 text-xl font-bold">CrimeScene AI</h1>
        <p className="mb-6 text-xs text-slate-500">
          Investigation co-pilot — authorized personnel only. All activity is audit-logged.
        </p>
        {error && <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-800">{error}</div>}
        <label className="mb-1 block text-sm font-medium">Email</label>
        <input className="mb-3 w-full rounded border p-2" type="email" value={email}
               onChange={(e) => setEmail(e.target.value)} required autoFocus />
        <label className="mb-1 block text-sm font-medium">Password</label>
        <input className="mb-3 w-full rounded border p-2" type="password" value={password}
               onChange={(e) => setPassword(e.target.value)} required />
        {needsTotp && (
          <>
            <label className="mb-1 block text-sm font-medium">TOTP code</label>
            <input className="mb-3 w-full rounded border p-2" inputMode="numeric" value={totp}
                   onChange={(e) => setTotp(e.target.value)} />
          </>
        )}
        <button disabled={busy}
                className="w-full rounded bg-slate-800 p-2 font-medium text-white hover:bg-slate-700 disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
