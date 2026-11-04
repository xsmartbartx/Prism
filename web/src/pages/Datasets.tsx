import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Database, Search, Sparkles } from "lucide-react";
import { can, post, type Dataset, type ImportRec } from "../api";
import { useApp, useLoad } from "../app-state";
import Dropzone from "../components/Dropzone";
import { Empty, ErrorBox, PageLoading, StatusBadge, fmtNum, timeAgo } from "../components/ui";

export async function uploadFile(file: File): Promise<ImportRec> {
  const fd = new FormData();
  fd.append("file", file);
  return post<ImportRec>("/api/v1/imports", fd);
}

export default function Datasets() {
  const { me, toast } = useApp();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const { data, error, loading, reload } = useLoad<Dataset[]>(`/api/v1/datasets?q=${encodeURIComponent(q)}`, [q]);
  const [busy, setBusy] = useState(false);
  const author = can.author(me?.role);

  const onFile = async (f: File) => {
    setBusy(true);
    try {
      const imp = await uploadFile(f);
      nav(`/imports/${imp.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const loadSample = async () => {
    setBusy(true);
    try {
      const ds = await post<Dataset>("/api/v1/datasets/sample");
      toast("Sample dataset loaded");
      nav(`/datasets/${ds.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Datasets</h1>
          <p>Typed, versioned tables imported from your files. Certified datasets are listed first.</p>
        </div>
        <div className="row">
          <div style={{ position: "relative" }}>
            <Search size={15} style={{ position: "absolute", left: 10, top: 10 }} color="var(--text-3)" />
            <input className="input" style={{ paddingLeft: 32, width: 240 }} placeholder="Search datasets" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search datasets" />
          </div>
        </div>
      </div>

      {author && (
        <div style={{ marginBottom: 20 }}>
          <Dropzone onFile={onFile} busy={busy} compact={!!data?.length} />
        </div>
      )}

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data ? (
        <PageLoading />
      ) : data && data.length === 0 && !q ? (
        <div className="card">
          <Empty
            icon={<Database size={22} />}
            title="No datasets yet"
            action={
              author && (
                <button className="btn" onClick={loadSample} disabled={busy}>
                  <Sparkles size={16} /> Load a sample sales dataset
                </button>
              )
            }
          >
            {author ? "Drop a spreadsheet above to create your first dataset, or start with sample data to explore Prism." : "Nothing has been shared with you yet. Ask an author to import a dataset."}
          </Empty>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table table-clickable">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th className="num">Rows</th>
                <th className="num">Columns</th>
                <th className="num">Version</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data?.map((d) => (
                <tr key={d.id} onClick={() => nav(`/datasets/${d.id}`)}>
                  <td>
                    <Link to={`/datasets/${d.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 600 }}>{d.name}</Link>
                    {d.description && <div className="muted small truncate" style={{ maxWidth: 420 }}>{d.description}</div>}
                  </td>
                  <td><StatusBadge status={d.status} />{d.quarantine_count ? <span className="badge badge-warning" style={{ marginLeft: 6 }}>{fmtNum(d.quarantine_count)} quarantined</span> : null}</td>
                  <td className="num">{fmtNum(d.row_count)}</td>
                  <td className="num">{fmtNum(d.column_count)}</td>
                  <td className="num">v{d.version ?? "–"}</td>
                  <td className="muted">{timeAgo(d.updated_at)}</td>
                </tr>
              ))}
              {data?.length === 0 && (
                <tr><td colSpan={6} className="muted" style={{ textAlign: "center", padding: 24 }}>No datasets match “{q}”.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
