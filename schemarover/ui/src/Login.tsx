import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { authenticate } from "./api";
import ThemeToggle from "./ThemeToggle";

export default function Login() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const signup = mode === "signup";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authenticate(mode, email, password, invite);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="px-6 sm:px-10 py-6 flex items-center justify-between">
        <span className="font-display text-[15px] font-semibold tracking-tight">
          Schema<span className="text-signal">Rover</span>
        </span>
        <ThemeToggle />
      </header>

      <main className="flex-1 grid place-items-center px-6 pb-24">
        <form onSubmit={submit} className="w-full max-w-sm bg-card border border-rule rounded p-6 space-y-4">
          <h1 className="font-display text-2xl font-semibold tracking-tight">
            {signup ? "Create an account" : "Log in"}
          </h1>
          <label className="block text-xs text-slate">
            Email
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full text-sm bg-paper border border-rule rounded px-3 py-2 outline-none focus:border-signal text-ink"
            />
          </label>
          <label className="block text-xs text-slate">
            Password
            <input
              type="password"
              required
              minLength={signup ? 8 : undefined}
              autoComplete={signup ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full text-sm bg-paper border border-rule rounded px-3 py-2 outline-none focus:border-signal text-ink"
            />
          </label>
          {signup && (
            <label className="block text-xs text-slate">
              Invite code
              <input
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                autoComplete="off"
                className="mt-1 w-full font-mono text-sm bg-paper border border-rule rounded px-3 py-2 outline-none focus:border-signal text-ink"
              />
            </label>
          )}
          {error && (
            <p role="alert" className="font-mono text-xs text-alarm break-words">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-ink text-onink text-sm rounded px-5 py-2 transition hover:bg-signal hover:text-onsignal disabled:opacity-30"
          >
            {busy ? "…" : signup ? "Sign up" : "Log in"}
          </button>
          <button
            type="button"
            onClick={() => {
              setMode(signup ? "login" : "signup");
              setError(null);
            }}
            className="w-full text-xs text-slate transition hover:text-signal"
          >
            {signup ? "Already have an account? Log in" : "New here? Create an account"}
          </button>
        </form>
      </main>
    </div>
  );
}
