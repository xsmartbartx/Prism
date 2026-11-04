import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BarChart3, FileClock, LayoutDashboard, Plus } from "lucide-react";
import { can, getText, post, type Chart, type Dashboard, type Dataset, type ImportRec } from "../api";
import { effectiveTheme, useApp, useLoad } from "../app-state";
import { ChartSvg, Empty, ErrorBox, Modal, PageLoading, fmtBytes, timeAgo } from "../components/ui";

function Thumb({ id }: { id: string }) {
  const { theme } = useApp();
  const t = effectiveTheme(theme);
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    getText(`/api/v1/charts/${id}/render?width=560&height=280&theme=${t}`).then(setSvg).catch(() => setFailed(true));
  }, [id, t]);
  if (failed) return <div className="muted small" style={{ height: 140, display: "grid", placeItems: "center" }}>Preview unavailable</div>;
  return <ChartSvg svg={svg} minHeight={140} />;
}

export function Charts() {
  const { me } = useApp();
  const nav = useNavigate();
  const { data, error, reload } = useLoad<Chart[]>("/api/v1/charts");
  const datasets = useLoad<Dataset[]>("/api/v1/datasets");
  const dsName = (id: string) => datasets.data?.find((d) => d.id === id)?.name ?? "";
  return (
    <>
      <div className="page-head">
        <div className="grow"><h1>Charts</h1><p>Saved visualisations. Each chart is a query plus a view specification over a dataset version.</p></div>
        {can.explore(me?.role) && <button className="btn btn-primary" onClick={() => nav("/charts/new")}><Plus size={16} /> New chart</button>}
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {!data ? (
        <PageLoading />
      ) : data.length === 0 ? (
        <div className="card">
          <Empty icon={<BarChart3 size={22} />} title="No charts yet" action={can.explore(me?.role) && <button className="btn btn-primary" onClick={() => nav("/charts/new")}><Plus size={16} /> Build your first chart</button>}>
            Pick a dataset, choose what to compare, and Prism suggests the right chart.
          </Empty>
        </div>
      ) : (
        <div className="grid-cards">
          {data.map((c) => (
            <Link key={c.id} to={`/charts/${c.id}`} className="card" style={{ color: "inherit", textDecoration: "none", overflow: "hidden" }}>
              <div style={{ padding: 10, borderBottom: "1px solid var(--border)" }}><Thumb id={c.id} /></div>
              <div style={{ padding: "10px 14px" }}>
                <div style={{ fontWeight: 600 }} className="truncate">{c.name}</div>
                <div className="muted small truncate">{dsName(c.dataset_id)} · {c.view.mark} · {timeAgo(c.updated_at)}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function Dashboards() {
  const { me, toast } = useApp();
  const nav = useNavigate();
  const { data, error, reload } = useLoad<Dashboard[]>("/api/v1/dashboards");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const create = async () => {
    try {
      const d = await post<Dashboard>("/api/v1/dashboards", { name: name.trim() || "Untitled dashboard", layout: [] });
      nav(`/dashboards/${d.id}?edit=1`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <>
      <div className="page-head">
        <div className="grow"><h1>Dashboards</h1><p>Arrange charts into a page you can share with a single link.</p></div>
        {can.explore(me?.role) && <button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={16} /> New dashboard</button>}
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {!data ? (
        <PageLoading />
      ) : data.length === 0 ? (
        <div className="card"><Empty icon={<LayoutDashboard size={22} />} title="No dashboards yet">Save a few charts, then combine them into a dashboard.</Empty></div>
      ) : (
        <div className="grid-cards">
          {data.map((d) => (
            <Link key={d.id} to={`/dashboards/${d.id}`} className="card card-pad" style={{ color: "inherit", textDecoration: "none" }}>
              <div className="row"><LayoutDashboard size={18} color="var(--accent)" /><strong className="truncate">{d.name}</strong></div>
              <p className="muted small" style={{ marginTop: 6 }}>{d.layout.length} chart{d.layout.length === 1 ? "" : "s"} · updated {timeAgo(d.updated_at)}</p>
              {d.description && <p className="small truncate" style={{ marginTop: 4 }}>{d.description}</p>}
            </Link>
          ))}
        </div>
      )}
      {creating && (
        <Modal title="New dashboard" onClose={() => setCreating(false)} footer={<><button className="btn" onClick={() => setCreating(false)}>Cancel</button><button className="btn btn-primary" onClick={create}>Create</button></>}>
          <label className="field">Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()} placeholder="e.g. Monthly sales review" /></label>
        </Modal>
      )}
    </>
  );
}

export function Imports() {
  const { data, error, reload } = useLoad<ImportRec[]>("/api/v1/imports");
  const label: Record<string, string> = { ready: "ready to publish", needs_review: "needs review", loaded: "published", failed: "failed", uploaded: "uploaded" };
  const cls: Record<string, string> = { ready: "badge-accent", needs_review: "badge-warning", loaded: "badge-success", failed: "badge-danger" };
  return (
    <>
      <div className="page-head"><div className="grow"><h1>Imports</h1><p>Every uploaded file and what happened to it.</p></div></div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {!data ? (
        <PageLoading />
      ) : data.length === 0 ? (
        <div className="card"><Empty icon={<FileClock size={22} />} title="No uploads yet">Drop a file on the Datasets page to start.</Empty></div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>File</th><th>Status</th><th className="num">Size</th><th>Uploaded</th><th /></tr></thead>
            <tbody>
              {data.map((i) => (
                <tr key={i.id}>
                  <td><strong>{i.filename}</strong>{i.error && <div className="small" style={{ color: "var(--danger)", whiteSpace: "normal", maxWidth: 520 }}>{i.error}</div>}</td>
                  <td><span className={`badge ${cls[i.status] ?? ""}`}>{label[i.status] ?? i.status}</span></td>
                  <td className="num">{fmtBytes(i.size_bytes)}</td>
                  <td className="muted">{timeAgo(i.created_at)}</td>
                  <td>
                    {i.status === "loaded" && i.dataset_id ? <Link to={`/datasets/${i.dataset_id}`}>Open dataset</Link> : i.status !== "failed" ? <Link to={`/imports/${i.id}`}>Review</Link> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
