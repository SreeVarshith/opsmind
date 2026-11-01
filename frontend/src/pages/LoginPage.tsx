import { BookOpenCheck, Loader2, ShieldCheck, Zap } from "lucide-react";
import { useState, type FormEvent } from "react";
import { IncidentPreview } from "../components/IncidentPreview";
import { Brand, ErrorNote } from "../components/Layout";
import { login, type User } from "../lib/api";

const POINTS = [
  { icon: BookOpenCheck, label: "Cited answers" },
  { icon: ShieldCheck, label: "Fact-checked" },
  { icon: Zap, label: "Live progress" },
];

export function LoginPage({ notice, onLogin }: { notice: string | null; onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onLogin(await login(username.trim(), password));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't log in.");
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="hidden flex-col items-center justify-center gap-7 border-r border-line bg-panel p-10 lg:flex">
        <div className="w-full max-w-md">
          <Brand size={24} />
          <h1 className="mt-5 text-3xl leading-tight font-semibold tracking-tight">
            From alert to likely fix, with sources you can check
          </h1>
          <p className="mt-2 mb-0 text-ink-2">
            Paste an error and OpsMind finds your runbooks and past incidents, then explains the likely cause and the fix.
          </p>
        </div>
        <IncidentPreview />
        <ul className="m-0 flex w-full max-w-md list-none flex-wrap gap-x-5 gap-y-2 p-0">
          {POINTS.map(({ icon: Icon, label }) => (
            <li key={label} className="flex items-center gap-1.5 text-[13px] text-ink-2">
              <Icon size={15} className="text-accent-ink" aria-hidden />
              {label}
            </li>
          ))}
        </ul>
      </section>

      <section className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm">
          <div className="mb-6 lg:hidden">
            <Brand size={24} />
          </div>
          <h2 className="text-xl font-semibold tracking-tight">Log in</h2>
          <p className="mt-1 mb-5 text-ink-2">Use your OpsMind account.</p>
          <div className="grid gap-3">
            {notice && !error && <ErrorNote>{notice}</ErrorNote>}
            {error && <ErrorNote>{error}</ErrorNote>}
            <label className="grid gap-1 text-[13px] font-medium">
              Username
              <input
                required
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="h-10 rounded-lg border border-line-strong bg-panel px-3 text-sm font-normal outline-none focus:border-accent"
              />
            </label>
            <label className="grid gap-1 text-[13px] font-medium">
              Password
              <input
                required
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-10 rounded-lg border border-line-strong bg-panel px-3 text-sm font-normal outline-none focus:border-accent"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="mt-1 flex h-10 items-center justify-center gap-2 rounded-lg bg-accent font-medium text-panel hover:bg-accent-hover disabled:opacity-60"
            >
              {busy && <Loader2 size={16} className="animate-spin" aria-hidden />}
              Log in
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
