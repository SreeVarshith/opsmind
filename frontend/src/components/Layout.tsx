import { Activity, BarChart3, FileText, History, LogOut, MessageSquare, Moon, Sun } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { User } from "../lib/api";

const ROLE_LABELS: Record<string, string> = { admin: "Admin", sre: "SRE", developer: "Developer" };

export function Brand({ size = 20 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight text-ink">
      <span className="grid place-items-center rounded-md bg-accent p-1 text-panel">
        <Activity size={size - 4} strokeWidth={2.5} aria-hidden />
      </span>
      OpsMind
    </span>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("opsmind-theme", next ? "dark" : "light");
    } catch {
      /* the choice just won't be remembered */
    }
    setDark(next);
  };
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className="rounded-md p-1.5 text-ink-2 hover:bg-panel-2 hover:text-ink"
    >
      {dark ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
    </button>
  );
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex shrink-0 items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] transition-colors ${
    isActive ? "bg-accent-soft font-medium text-accent-ink" : "text-ink-2 hover:bg-panel-2 hover:text-ink"
  }`;

export function Layout(props: { user: User; canManage: boolean; onLogout: () => void; children: ReactNode }) {
  const { user, canManage, onLogout, children } = props;
  const items = [
    { to: "/", label: "Ask", icon: MessageSquare, show: true, end: true },
    { to: "/history", label: "History", icon: History, show: true, end: false },
    { to: "/documents", label: "Documents", icon: FileText, show: canManage, end: false },
    { to: "/monitoring", label: "Monitoring", icon: BarChart3, show: canManage, end: false },
  ].filter((i) => i.show);

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-line bg-panel md:w-52 md:border-r md:border-b-0">
        <div className="flex items-center justify-between px-4 py-3 md:py-4">
          <Brand />
          <div className="flex items-center gap-1 md:hidden">
            <ThemeToggle />
            <button
              type="button"
              onClick={onLogout}
              aria-label="Log out"
              className="rounded-md p-1.5 text-ink-2 hover:bg-panel-2"
            >
              <LogOut size={16} aria-hidden />
            </button>
          </div>
        </div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-2 pb-2 [scrollbar-width:none] md:flex-1 md:flex-col md:pb-0">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={linkClass}>
              <Icon size={16} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden items-center gap-2 border-t border-line px-3 py-3 md:flex">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-medium">{user.username}</div>
            <div className="text-xs text-ink-3">{ROLE_LABELS[user.role] ?? user.role}</div>
          </div>
          <ThemeToggle />
          <button
            type="button"
            onClick={onLogout}
            aria-label="Log out"
            title="Log out"
            className="rounded-md p-1.5 text-ink-2 hover:bg-panel-2 hover:text-ink"
          >
            <LogOut size={16} aria-hidden />
          </button>
        </div>
      </aside>
      <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="mb-5">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="mt-0.5 text-ink-2">{description}</p>}
    </header>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-[13px] text-ink">
      {children}
    </div>
  );
}
