import { BookOpenCheck, Loader2, ShieldCheck, Zap } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Brand, ErrorNote } from "../components/Layout";
import { login, type User } from "../lib/api";

const POINTS = [
  { icon: BookOpenCheck, title: "Cited answers", text: "Every step links back to your runbooks, tickets and postmortems." },
  { icon: ShieldCheck, title: "Fact-checked", text: "Careful mode checks each sentence and flags what it can't verify." },
  { icon: Zap, title: "Fast under pressure", text: "Paste an error and get likely causes and fixes in seconds." },
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
      <section className="hidden flex-col justify-center gap-8 border-r border-line bg-panel p-12 lg:flex">
        <div className="max-w-md">
          <Brand size={24} />
          <h1 className="mt-6 text-3xl leading-tight font-semibold tracking-tight">
            Resolve incidents with answers you can verify
          </h1>
        </div>
        <ul className="grid max-w-md gap-5">
          {POINTS.map(({ icon: Icon, title, text }) => (
            <li key={title} className="flex gap-3">
              <span className="mt-0.5 self-start rounded-lg bg-accent-soft p-2 text-accent-ink">
                <Icon size={18} aria-hidden />
              </span>
              <div>
                <div className="font-medium">{title}</div>
                <div className="text-ink-2">{text}</div>
              </div>
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
