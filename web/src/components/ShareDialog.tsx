import { useEffect, useState } from "react";
import { Link2, Trash2 } from "lucide-react";
import { del, get, post, type Share } from "../api";
import { useApp } from "../app-state";
import { CopyField, Modal, Spinner, timeAgo } from "./ui";

const EXPIRY = [
  { label: "Never", hours: null },
  { label: "1 day", hours: 24 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
  { label: "1 year", hours: 24 * 365 },
];

export default function ShareDialog({ type, id, name, onClose }: { type: "chart" | "dashboard"; id: string; name: string; onClose: () => void }) {
  const { toast } = useApp();
  const [shares, setShares] = useState<Share[] | null>(null);
  const [created, setCreated] = useState<Share | null>(null);
  const [expiry, setExpiry] = useState<number | null>(null);
  const [embed, setEmbed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () => get<Share[]>(`/api/v1/shares?artifact_id=${id}`).then(setShares).catch((e) => toast(e.message, "error"));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const create = async () => {
    setBusy(true);
    try {
      const s = await post<Share>("/api/v1/shares", { artifact_type: type, artifact_id: id, expires_in_hours: expiry, allow_embed: embed });
      setCreated(s);
      load();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const active = (shares ?? []).filter((s) => s.active);
  return (
    <Modal title={`Share “${name}”`} onClose={onClose}>
      <p className="muted small">
        Anyone with the link can view this {type} read-only, including its data as displayed. Links can expire and can be revoked at any time. Every view is counted.
      </p>
      {created?.url ? (
        <div className="stack">
          <div className="alert alert-success"><div>Link created. Copy it now — it is shown only once.</div></div>
          <label className="field">Public link<CopyField value={created.url} /></label>
          {created.embed_url && (
            <label className="field">
              Embed code
              <CopyField value={`<iframe src="${created.embed_url}" width="100%" height="480" style="border:0" loading="lazy"></iframe>`} />
            </label>
          )}
          <button className="btn" onClick={() => setCreated(null)}>Create another link</button>
        </div>
      ) : (
        <div className="stack">
          <div className="grid-2">
            <label className="field">
              Expires
              <select className="input" value={expiry ?? ""} onChange={(e) => setExpiry(e.target.value ? Number(e.target.value) : null)}>
                {EXPIRY.map((x) => (
                  <option key={x.label} value={x.hours ?? ""}>{x.label}</option>
                ))}
              </select>
            </label>
            <label className="check" style={{ alignSelf: "end", height: 34 }}>
              <input type="checkbox" checked={embed} onChange={(e) => setEmbed(e.target.checked)} /> Allow embedding (iframe)
            </label>
          </div>
          <button className="btn btn-primary" onClick={create} disabled={busy}>
            <Link2 size={16} /> Create public link
          </button>
        </div>
      )}
      <div className="sep" />
      <h3>Active links</h3>
      {shares === null ? (
        <Spinner />
      ) : active.length === 0 ? (
        <p className="muted small">No active links.</p>
      ) : (
        <div className="stack" style={{ gap: 6 }}>
          {active.map((s) => (
            <div key={s.id} className="row-between card" style={{ padding: "8px 12px" }}>
              <div className="small">
                Created {timeAgo(s.created_at)} · {s.use_count} views · {s.expires_at ? `expires ${new Date(s.expires_at).toLocaleDateString()}` : "no expiry"}
                {s.allow_embed && <span className="badge" style={{ marginLeft: 6 }}>embed</span>}
              </div>
              <button
                className="btn btn-sm btn-danger"
                onClick={async () => {
                  await del(`/api/v1/shares/${s.id}`);
                  toast("Link revoked");
                  load();
                }}
              >
                <Trash2 size={14} /> Revoke
              </button>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
