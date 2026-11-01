import { FileText, Loader2, Lock, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { ErrorNote, PageHeader } from "../components/Layout";
import { formatDate } from "../lib/answer";
import { deleteUpload, documentStats, listUploads, uploadDocument, type UploadedDocument } from "../lib/api";

const TYPE_LABELS: Record<string, string> = {
  runbook: "Runbooks",
  postmortem: "Postmortems",
  log: "Log patterns",
  ticket: "Tickets",
};

export function DocumentsPage() {
  const [items, setItems] = useState<UploadedDocument[] | null>(null);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [access, setAccess] = useState("public");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listUploads()
      .then(setItems)
      .catch((e: Error) => setError(e.message));
    documentStats()
      .then((s) => setStats(s.by_source_type))
      .catch(() => setStats(null));
  }, []);

  const upload = async (file: File | undefined) => {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const doc = await uploadDocument(file, access);
      setItems((all) => [doc, ...(all ?? []).filter((d) => d.id !== doc.id)]);
      setNotice(`${doc.filename} is now searchable.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    }
    setBusy(false);
    if (picker.current) picker.current.value = "";
  };

  const remove = async (doc: UploadedDocument) => {
    if (!window.confirm(`Remove ${doc.filename} from the knowledge base? This can't be undone.`)) return;
    try {
      await deleteUpload(doc.id);
      setItems((all) => all?.filter((d) => d.id !== doc.id) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't remove it.");
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void upload(e.dataTransfer.files[0]);
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl p-5">
        <PageHeader title="Documents" description="Add your team's runbooks and postmortems so OpsMind can answer from them." />

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`rounded-xl border border-dashed bg-panel p-6 text-center transition-colors ${
            dragging ? "border-accent bg-accent-soft" : "border-line-strong"
          }`}
        >
          {busy ? (
            <Loader2 size={22} className="mx-auto animate-spin text-accent" aria-hidden />
          ) : (
            <Upload size={22} className="mx-auto text-ink-3" aria-hidden />
          )}
          <p className="mt-2 font-medium">{busy ? "Reading and indexing..." : "Drop a file here"}</p>
          <p className="text-[13px] text-ink-2">PDF, Markdown or text, up to 5 MB</p>
          <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              Who can see it
              <select
                value={access}
                onChange={(e) => setAccess(e.target.value)}
                className="rounded-md border border-line-strong bg-panel px-2 py-1 text-xs text-ink"
              >
                <option value="public">Everyone</option>
                <option value="restricted">Admins and SREs</option>
              </select>
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => picker.current?.click()}
              className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-panel hover:bg-accent-hover disabled:opacity-50"
            >
              Choose file
            </button>
            <input
              ref={picker}
              type="file"
              accept=".pdf,.md,.markdown,.txt"
              className="hidden"
              aria-label="Choose a file to upload"
              onChange={(e) => void upload(e.target.files?.[0])}
            />
          </div>
        </div>

        <div className="mt-3 grid gap-2" aria-live="polite">
          {error && <ErrorNote>{error}</ErrorNote>}
          {notice && <div className="rounded-lg bg-good-soft px-3 py-2 text-[13px] text-good">{notice}</div>}
        </div>

        <h2 className="mt-6 mb-2 text-sm font-semibold">Your documents</h2>
        {items === null && !error && <Loader2 size={18} className="animate-spin text-accent" aria-label="Loading" />}
        {items?.length === 0 && <p className="text-ink-2">Upload a document to answer from your own procedures.</p>}
        {items && items.length > 0 && (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-panel">
            {items.map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-4 py-2.5">
                <FileText size={16} className="shrink-0 text-ink-3" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{d.filename}</div>
                  <div className="text-xs text-ink-3">
                    {d.uploaded_by} · {formatDate(d.uploaded_at)}
                  </div>
                </div>
                {d.access === "restricted" && (
                  <span className="flex items-center gap-1 rounded-md bg-warn-soft px-1.5 py-0.5 text-xs text-warn">
                    <Lock size={11} aria-hidden /> Restricted
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => void remove(d)}
                  aria-label={`Remove ${d.filename}`}
                  title="Remove"
                  className="rounded-md p-1.5 text-ink-3 hover:bg-bad-soft hover:text-bad"
                >
                  <Trash2 size={15} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}

        {stats && (
          <>
            <h2 className="mt-6 mb-2 text-sm font-semibold">Built-in knowledge base</h2>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {Object.entries(stats)
                .filter(([type]) => type !== "uploaded")
                .map(([type, count]) => (
                  <div key={type} className="rounded-xl border border-line bg-panel p-3">
                    <dt className="text-xs text-ink-2">{TYPE_LABELS[type] ?? type}</dt>
                    <dd className="m-0 text-xl font-semibold tabular-nums">{count}</dd>
                  </div>
                ))}
            </dl>
          </>
        )}
      </div>
    </div>
  );
}
