import { useState, type FormEvent } from "react";
import { Link2, RefreshCw, Trash2 } from "lucide-react";
import { del, post, put, type DatasetLink, type LinkRefresh, type RefreshSchedule } from "../api";
import { useApp } from "../app-state";
import { Confirm, fmtDate, timeAgo } from "./ui";

export const SCHEDULE_LABELS: Record<RefreshSchedule, string> = {
  manual: "Only when I refresh",
  hourly: "Every hour",
  daily: "Every day",
  weekly: "Every week",
};

const STATUS: Record<NonNullable<DatasetLink["last_status"]>, { label: string; cls: string }> = {
  loaded: { label: "New version loaded", cls: "badge-success" },
  unchanged: { label: "No changes", cls: "" },
  drift: { label: "Columns changed", cls: "badge-danger" },
  failed: { label: "Failed", cls: "badge-danger" },
};

export function refreshMessage(r: LinkRefresh): { text: string; error: boolean } {
  const o = r.outcome;
  if (o.status === "loaded") return { text: `Loaded version ${o.version}: ${o.rows?.toLocaleString()} rows`, error: false };
  if (o.status === "unchanged") return { text: "No changes since the last refresh", error: false };
  return { text: o.error ?? "The refresh failed", error: true };
}

/** The link a dataset refreshes from: schedule, last result, refresh now, edit or remove. */
export function SourceLinkCard({ datasetId, link, canSchedule, onChange }: Readonly<{ datasetId: string; link: DatasetLink; canSchedule: boolean; onChange: () => void }>) {
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState(link.url);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const base = `/api/v1/datasets/${datasetId}/link`;

  const save = async (next: { url?: string; schedule?: RefreshSchedule }) => {
    setBusy(true);
    try {
      await put(base, { url: next.url ?? link.url, schedule: next.schedule ?? link.schedule });
      setEditing(false);
      onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const refreshNow = async () => {
    setBusy(true);
    try {
      const msg = refreshMessage(await post<LinkRefresh>(`${base}/refresh`));
      toast(msg.text, msg.error ? "error" : undefined);
      onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const status = link.last_status ? STATUS[link.last_status] : null;
  return (
    <div className="card">
      <div className="card-head">
        <h2 className="row" style={{ gap: 8 }}><Link2 size={16} /> Source link</h2>
        <div className="row">
          <button type="button" className="btn btn-sm" onClick={refreshNow} disabled={busy}><RefreshCw size={14} /> {busy ? "Refreshing…" : "Refresh now"}</button>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setConfirmRemove(true)} aria-label="Remove link" title="Stop refreshing from this link"><Trash2 size={14} /></button>
        </div>
      </div>
      <div className="card-pad stack" style={{ gap: 12 }}>
        {editing ? (
          <form className="row" onSubmit={(e: FormEvent) => { e.preventDefault(); void save({ url }); }}>
            <input className="input grow mono" type="url" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Link" required />
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !url.trim()}>Save</button>
            <button type="button" className="btn btn-sm" onClick={() => { setEditing(false); setUrl(link.url); }}>Cancel</button>
          </form>
        ) : (
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <span className="mono small truncate grow" title={link.url}>{link.url}</span>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>Change</button>
          </div>
        )}
        <div className="row small" style={{ gap: 16 }}>
          <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
            <span className="muted">Refresh</span>
            <select className="input input-sm" style={{ width: "auto" }} aria-label="Refresh schedule" value={link.schedule} disabled={busy} onChange={(e) => void save({ schedule: e.target.value as RefreshSchedule })}>
              {(Object.keys(SCHEDULE_LABELS) as RefreshSchedule[]).map((s) => {
                const locked = s !== "manual" && !canSchedule && s !== link.schedule;
                return <option key={s} value={s} disabled={locked}>{SCHEDULE_LABELS[s]}{locked ? " (Pro plan)" : ""}</option>;
              })}
            </select>
          </span>
          {link.schedule !== "manual" && link.next_run_at && <span className="muted">Next: {fmtDate(link.next_run_at, true)}</span>}
          <span className="muted">
            Last checked {timeAgo(link.last_run_at)}
            {status && <> · <span className={`badge ${status.cls}`}>{status.label}</span></>}
          </span>
        </div>
        {link.last_error && <p className="small" style={{ color: "var(--danger)", margin: 0 }}>{link.last_error}</p>}
      </div>
      {confirmRemove && (
        <Confirm
          title="Remove the link?"
          message="The dataset and its versions stay. It just stops refreshing from this link; you can still load new files by hand."
          confirmLabel="Remove link"
          onClose={() => setConfirmRemove(false)}
          onConfirm={async () => {
            try {
              await del(base);
              onChange();
            } catch (e) {
              toast((e as Error).message, "error");
            }
          }}
        />
      )}
    </div>
  );
}

/** A small form for a link: used to import from a link, and to attach one to a dataset. */
export function LinkForm({ onSubmit, busy, label, placeholder }: Readonly<{ onSubmit: (url: string) => void | Promise<void>; busy: boolean; label: string; placeholder?: string }>) {
  const [url, setUrl] = useState("");
  return (
    <form
      className="row link-form"
      style={{ flexWrap: "nowrap" }}
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim()) void onSubmit(url.trim());
      }}
    >
      <Link2 size={16} color="var(--text-3)" aria-hidden />
      <input className="input grow" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={placeholder ?? "https://…"} aria-label={label} />
      <button type="submit" className="btn" disabled={busy || !url.trim()}>{label}</button>
    </form>
  );
}
