import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { BarChart3, Download, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { can, del, download, patch, post, type Chart, type Dataset, type QueryResult } from "../api";
import { useApp, useLoad } from "../app-state";
import { Confirm, DataTable, ErrorBox, Modal, PageLoading, StatusBadge, TypeDot, fmtDate, fmtNum, timeAgo } from "../components/ui";
import Dropzone from "../components/Dropzone";

type Tab = "overview" | "data" | "quarantine" | "versions" | "settings";

export default function DatasetDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { me, toast } = useApp();
  const { data: ds, error, reload } = useLoad<Dataset>(`/api/v1/datasets/${id}`);
  const [tab, setTab] = useState<Tab>("overview");
  const [refreshing, setRefreshing] = useState(false);
  const [showRefresh, setShowRefresh] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const charts = useLoad<Chart[]>(`/api/v1/charts?dataset_id=${id}`);

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!ds) return <PageLoading />;
  const v = ds.current_version;
  const role = me?.role;

  const onRefresh = async (f: File) => {
    setRefreshing(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await post<Dataset & { load: { rows: number; quarantined: number } }>(`/api/v1/datasets/${id}/refresh`, fd);
      toast(`Loaded version ${res.current_version?.version}: ${fmtNum(res.load.rows)} rows`);
      setShowRefresh(false);
      void reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <div className="row"><h1>{ds.name}</h1><StatusBadge status={ds.status} /></div>
          <p>{ds.description || "No description"} · updated {timeAgo(ds.updated_at)}</p>
        </div>
        <div className="row">
          {can.explore(role) && (
            <>
              <button className="btn" onClick={() => download(`/api/v1/datasets/${id}/export?format=xlsx`).catch((e) => toast(e.message, "error"))}><Download size={16} /> Excel</button>
              <button className="btn" onClick={() => download(`/api/v1/datasets/${id}/export?format=csv`).catch((e) => toast(e.message, "error"))}><Download size={16} /> CSV</button>
            </>
          )}
          {can.author(role) && <button className="btn" onClick={() => setShowRefresh(true)}><RefreshCw size={16} /> Load new file</button>}
          {can.explore(role) && <button className="btn btn-primary" onClick={() => nav(`/charts/new?dataset=${id}`)}><BarChart3 size={16} /> New chart</button>}
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: 16, gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
        <div className="card stat"><div className="label">Rows</div><div className="value">{fmtNum(v?.row_count)}</div></div>
        <div className="card stat"><div className="label">Columns</div><div className="value">{fmtNum(v?.columns.length)}</div></div>
        <div className="card stat"><div className="label">Version</div><div className="value">v{v?.version ?? "–"}</div></div>
        <div className="card stat">
          <div className="label">Quarantined rows</div>
          <div className="value" style={{ color: v?.quarantine_count ? "var(--warning)" : undefined }}>{fmtNum(v?.quarantine_count ?? 0)}</div>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {(["overview", "data", "quarantine", "versions", "settings"] as Tab[])
          .filter((t) => t !== "settings" || can.author(role))
          .map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
      </div>

      {tab === "overview" && v && (
        <div className="stack">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Column</th><th>Type</th><th>Role</th><th className="num">Empty</th><th className="num">Distinct</th><th>Range / top values</th></tr>
              </thead>
              <tbody>
                {v.columns.map((c) => {
                  const s = v.profile.columns[c.name];
                  const range = s?.min !== undefined ? `${typeof s.min === "number" ? fmtNum(s.min) : s.min} → ${typeof s.max === "number" ? fmtNum(s.max as number) : s.max}` : s?.top?.map((t) => `${String(t.value)} (${fmtNum(t.count)})`).join(", ");
                  return (
                    <tr key={c.name}>
                      <td><strong>{c.name}</strong>{c.description && <div className="muted small">{c.description}</div>}</td>
                      <td><span className="row" style={{ flexWrap: "nowrap" }}><TypeDot type={c.type} /> {c.type}</span></td>
                      <td className="muted">{c.role}</td>
                      <td className="num">{s ? `${Math.round(s.null_ratio * 100)}%` : "–"}</td>
                      <td className="num">{fmtNum(s?.distinct)}</td>
                      <td className="muted small truncate" style={{ maxWidth: 360 }}>{range ?? "–"}{s?.mean !== undefined && <> · mean {fmtNum(Math.round(s.mean * 100) / 100)}</>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="card">
            <div className="card-head"><h2>Charts on this dataset</h2></div>
            <div className="card-pad">
              {charts.data?.length ? (
                <div className="stack" style={{ gap: 6 }}>
                  {charts.data.map((c) => <Link key={c.id} to={`/charts/${c.id}`}>{c.name}</Link>)}
                </div>
              ) : (
                <p className="muted">No charts yet.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "data" && <DataTab id={id} />}
      {tab === "quarantine" && <QuarantineTab id={id} />}
      {tab === "versions" && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Version</th><th className="num">Rows</th><th className="num">Quarantined</th><th>Loaded</th><th>Content hash</th><th>Source file hash</th></tr></thead>
            <tbody>
              {ds.versions?.map((x) => (
                <tr key={x.id}>
                  <td>v{x.version} {x.id === ds.current_version_id && <span className="badge badge-accent">current</span>}</td>
                  <td className="num">{fmtNum(x.row_count)}</td>
                  <td className="num">{fmtNum(x.quarantine_count)}</td>
                  <td>{fmtDate(x.created_at, true)}</td>
                  <td className="mono muted">{x.content_hash.slice(0, 16)}…</td>
                  <td className="mono muted">{x.source_sha256?.slice(0, 16)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "settings" && <SettingsTab ds={ds} onSaved={reload} onDelete={() => setConfirmDelete(true)} />}

      {showRefresh && (
        <Modal title="Load a new version" onClose={() => setShowRefresh(false)}>
          <p className="muted small">
            The file is checked against this dataset's column contract. Columns are matched by header name, so reordered columns and extra title rows are fine. A missing column or a wrong type stops the load with a clear message instead of producing wrong numbers.
          </p>
          <Dropzone onFile={onRefresh} busy={refreshing} compact />
        </Modal>
      )}
      {confirmDelete && (
        <Confirm
          title="Delete dataset?"
          message={<>This permanently deletes <strong>{ds.name}</strong>, all its versions and every chart built on it. Shared links stop working. This cannot be undone.</>}
          onClose={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await del(`/api/v1/datasets/${id}`);
            toast("Dataset deleted");
            nav("/datasets");
          }}
        />
      )}
    </>
  );
}

function DataTab({ id }: { id: string }) {
  const [offset, setOffset] = useState(0);
  const { data, error } = useLoad<QueryResult & { types: Record<string, string> }>(`/api/v1/datasets/${id}/rows?limit=100&offset=${offset}`, [offset]);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <PageLoading />;
  return (
    <div className="stack">
      <DataTable columns={data.columns} rows={data.rows} types={data.types} />
      <div className="row-between">
        <span className="muted small">Rows {fmtNum(offset + 1)}–{fmtNum(Math.min(offset + 100, data.total))} of {fmtNum(data.total)}</span>
        <div className="row">
          <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous</button>
          <button className="btn btn-sm" disabled={offset + 100 >= data.total} onClick={() => setOffset(offset + 100)}>Next</button>
        </div>
      </div>
    </div>
  );
}

function QuarantineTab({ id }: { id: string }) {
  const { data, error } = useLoad<{ _source_row: number; _reason: string; _raw: string }[]>(`/api/v1/datasets/${id}/quarantine`);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <PageLoading />;
  if (!data.length) return <div className="alert alert-success"><ShieldCheck size={16} /><div>Every row of the current version passed the column contract.</div></div>;
  return (
    <div className="stack">
      <p className="muted">These rows were kept out of the dataset because they didn't match the column contract. Fix them in the source file and load a new version.</p>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th className="num">Source row</th><th>Reason</th><th>Raw values</th></tr></thead>
          <tbody>
            {data.map((r) => (
              <tr key={r._source_row}><td className="num">{r._source_row}</td><td>{r._reason}</td><td className="mono muted truncate" style={{ maxWidth: 420 }}>{r._raw.split("␟").join(" | ")}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SettingsTab({ ds, onSaved, onDelete }: { ds: Dataset; onSaved: () => void; onDelete: () => void }) {
  const { me, toast } = useApp();
  const [name, setName] = useState(ds.name);
  const [description, setDescription] = useState(ds.description);
  const [status, setStatus] = useState(ds.status);
  const [busy, setBusy] = useState(false);
  return (
    <div className="grid-2">
      <div className="card card-pad stack">
        <h2>Details</h2>
        <label className="field">Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="field">Description<textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <label className="field">
          Status <span className="hint">Only stewards can certify. Certified datasets need a description and are listed first.</span>
          <select className="input" value={status} disabled={!can.steward(me?.role)} onChange={(e) => setStatus(e.target.value as Dataset["status"])}>
            <option value="draft">Draft</option>
            <option value="certified">Certified</option>
            <option value="deprecated">Deprecated</option>
          </select>
        </label>
        <div>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const body: Record<string, unknown> = { name, description };
                if (status !== ds.status) body.status = status;
                await patch(`/api/v1/datasets/${ds.id}`, body);
                toast("Saved");
                onSaved();
              } catch (e) {
                toast((e as Error).message, "error");
              } finally {
                setBusy(false);
              }
            }}
          >
            Save changes
          </button>
        </div>
      </div>
      <div className="card card-pad stack">
        <h2>Danger zone</h2>
        <p className="muted">Deleting removes all versions, charts built on this dataset and their shared links.</p>
        <div><button className="btn btn-danger" onClick={onDelete}><Trash2 size={16} /> Delete dataset</button></div>
      </div>
    </div>
  );
}
