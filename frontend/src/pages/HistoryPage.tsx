import { Loader2, MessageSquare, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorNote, PageHeader } from "../components/Layout";
import { formatDate } from "../lib/answer";
import { deleteConversation, listConversations, type ConversationSummary } from "../lib/api";

export function HistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listConversations()
      .then(setItems)
      .catch((e: Error) => setError(e.message));
  }, []);

  const remove = async (item: ConversationSummary) => {
    if (!window.confirm(`Delete "${item.title}"? This can't be undone.`)) return;
    try {
      await deleteConversation(item.id);
      setItems((all) => all?.filter((c) => c.id !== item.id) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete it.");
    }
  };

  const shown = items?.filter((c) => c.title.toLowerCase().includes(filter.trim().toLowerCase())) ?? [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl p-5">
        <PageHeader title="History" description="Your past incidents. Open one to read it or ask a follow-up." />
        {error && <ErrorNote>{error}</ErrorNote>}
        {items === null && !error && <Loader2 size={18} className="animate-spin text-accent" aria-label="Loading" />}
        {items?.length === 0 && (
          <div className="rounded-xl border border-dashed border-line-strong p-8 text-center">
            <MessageSquare size={20} className="mx-auto text-ink-3" aria-hidden />
            <p className="mt-2 font-medium">Start your first incident</p>
            <p className="text-ink-2">Questions you ask are saved here.</p>
            <Link to="/" className="mt-3 inline-block rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-panel hover:bg-accent-hover">
              Ask a question
            </Link>
          </div>
        )}
        {items && items.length > 0 && (
          <>
            <label className="mb-3 flex items-center gap-2 rounded-lg border border-line-strong bg-panel px-3 focus-within:border-accent">
              <Search size={15} className="text-ink-3" aria-hidden />
              <span className="sr-only">Search history</span>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search your incidents"
                className="h-9 w-full bg-transparent outline-none placeholder:text-ink-3"
              />
            </label>
            {shown.length === 0 && <p className="text-ink-2">No incidents match that search.</p>}
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-panel">
              {shown.map((c) => (
                <li key={c.id} className="flex items-center gap-2 pr-2 hover:bg-panel-2">
                  <button type="button" onClick={() => navigate(`/?c=${c.id}`)} className="min-w-0 flex-1 px-4 py-3 text-left">
                    <span className="block truncate font-medium">{c.title}</span>
                    <span className="text-xs text-ink-3">{formatDate(c.updated)}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(c)}
                    aria-label={`Delete ${c.title}`}
                    title="Delete"
                    className="rounded-md p-2 text-ink-3 hover:bg-bad-soft hover:text-bad"
                  >
                    <Trash2 size={15} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
