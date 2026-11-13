import { useState, type FormEvent } from "react";
import { api, setToken } from "../api";
import type { User } from "../types";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = mode === "login" ? await api.login(email, password) : await api.register(email, name, password);
      setToken(res.access_token);
      onLogin(res.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-[radial-gradient(ellipse_at_top,#17203a,#07090f_60%)] p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-ink-600 bg-ink-800/80 p-6 shadow-2xl backdrop-blur">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300">Ghost Infrastructure</div>
          <h1 className="mt-1 text-xl font-semibold text-white">See what your systems really depend on</h1>
        </div>

        {mode === "register" && (
          <div>
            <label className="label">Name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
        )}
        <div>
          <label className="label">Email</label>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </div>
        <div>
          <label className="label">Password</label>
          <input className="input" type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>

        {error && <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}

        <button className="btn btn-primary w-full py-2" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>

        <div className="flex items-center justify-between text-xs text-slate-400">
          <button type="button" className="hover:text-white" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Create an account" : "I already have an account"}
          </button>
          <button
            type="button"
            className="hover:text-white"
            onClick={() => {
              setMode("login");
              setEmail("demo@ghostinfra.dev");
              setPassword("demo1234");
            }}
          >
            Use demo account
          </button>
        </div>
      </form>
    </div>
  );
}
