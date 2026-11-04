import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, RefreshCw } from "lucide-react";
import { post, type ColumnProposal, type Dataset, type ImportRec, type PrismType } from "../api";
import { useApp, useLoad } from "../app-state";
import { ErrorBox, PageLoading, TypeDot, fmtBytes, fmtNum, timeAgo } from "../components/ui";

const TYPES: PrismType[] = ["string", "integer", "float", "date", "boolean"];
const ROLES = ["dimension", "measure", "time", "identifier", "geography", "metadata"];
const LOCALES = [
  ["en_US", "English (US) — 1,234.5 · MM/DD"],
  ["en_GB", "English (UK) — 1,234.5 · DD/MM"],
  ["de_DE", "German — 1.234,5 · DD.MM"],
  ["fr_FR", "French — 1 234,5 · DD/MM"],
  ["pl_PL", "Polish — 1 234,5 · DD.MM"],
  ["es_ES", "Spanish — 1.234,5 · DD/MM"],
  ["nl_NL", "Dutch — 1.234,5 · DD-MM"],
];

interface Decision extends ColumnProposal { include: boolean }

export default function ImportReview() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { toast } = useApp();
  const { data: imp, error, setData } = useLoad<ImportRec>(`/api/v1/imports/${id}`);
  const [cols, setCols] = useState<Decision[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tolerance, setTolerance] = useState(5);
  const [busy, setBusy] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);

  useEffect(() => {
    if (!imp) return;
    setCols(imp.proposal.columns.map((c) => ({ ...c, include: true })));
    setName((n) => n || imp.filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
  }, [imp]);

  const p = imp?.proposal;
  const ambiguous = cols.filter((c) => c.include && c.ambiguous);

  const repropose = async (changes: { sheet?: string | null; header_row?: number | null; locale?: string | null }) => {
    if (!imp) return;
    setBusy(true);
    try {
      const updated = await post<ImportRec>(`/api/v1/imports/${imp.id}/propose`, {
        sheet: changes.sheet ?? p?.sheet ?? null,
        header_row: changes.header_row === undefined ? p?.header_row : changes.header_row,
        locale: changes.locale ?? p?.locale ?? null,
      });
      setData(updated);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const update = (i: number, patch: Partial<Decision>) =>
    setCols((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch, ambiguous: patch.type ? false : c.ambiguous } : c)));

  const commit = async () => {
    if (!imp || !p) return;
    setBusy(true);
    setCommitError(null);
    try {
      const ds = await post<Dataset & { load: { rows: number; quarantined: number } }>(`/api/v1/imports/${imp.id}/commit`, {
        dataset_name: name.trim(),
        description,
        sheet: p.sheet,
        header_row: p.header_row,
        data_start_row: p.data_start_row,
        locale: p.locale,
        max_quarantine_ratio: tolerance / 100,
        columns: cols.map((c) => ({ index: c.index, source_name: c.source_name, name: c.name.trim(), type: c.type, role: c.role, locale: c.locale, nullable: c.nullable, include: c.include })),
      });
      toast(`Published ${fmtNum(ds.load.rows)} rows${ds.load.quarantined ? `, ${fmtNum(ds.load.quarantined)} quarantined` : ""}`);
      nav(`/datasets/${ds.id}`);
    } catch (e) {
      setCommitError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const headerOptions = useMemo(() => {
    const opts = [{ v: -1, l: "No header row (use column_1, column_2, …)" }];
    for (let i = 0; i < 20; i++) opts.push({ v: i, l: `Row ${i + 1}` });
    return opts;
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!imp || !p) return <PageLoading />;

  if (imp.status === "loaded")
    return (
      <div className="card card-pad stack">
        <div className="alert alert-success"><CheckCircle2 size={18} /><div>This import was published{imp.dataset_id && <> as a <Link to={`/datasets/${imp.dataset_id}`}>dataset</Link></>}.</div></div>
      </div>
    );

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1 className="row"><FileSpreadsheet size={20} /> Review import</h1>
          <p>{imp.filename} · {fmtBytes(imp.size_bytes)} · uploaded {timeAgo(imp.created_at)} · ~{fmtNum(p.row_estimate)} data rows{p.sample_truncated ? " (sampled)" : ""}</p>
        </div>
        <div className="row">
          <button className="btn" onClick={() => nav("/datasets")}>Cancel</button>
          <button className="btn btn-primary" onClick={commit} disabled={busy || !name.trim() || imp.status === "failed" || !cols.some((c) => c.include)}>
            {busy ? "Working…" : "Publish dataset"}
          </button>
        </div>
      </div>

      {imp.status === "failed" && <ErrorBox error={imp.error ?? "This file could not be read."} />}
      {commitError && <div style={{ marginBottom: 16 }}><ErrorBox error={commitError} /></div>}
      {p.warnings.map((w) => (
        <div key={w} className="alert alert-warning" style={{ marginBottom: 12 }}><AlertTriangle size={16} /><div>{w}</div></div>
      ))}
      {ambiguous.length > 0 && (
        <div className="alert alert-warning" style={{ marginBottom: 16 }}>
          <AlertTriangle size={16} />
          <div>
            <strong>{ambiguous.length} column{ambiguous.length > 1 ? "s need" : " needs"} a decision.</strong> Some values in {ambiguous.map((c) => `“${c.name}”`).join(", ")} don't match the proposed type. Pick a type (rows that still don't fit are quarantined, never silently changed), or choose “string” to keep text as-is.
          </div>
        </div>
      )}

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card card-pad stack">
          <h2>Dataset</h2>
          <label className="field">Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></label>
          <label className="field">Description <span className="hint">Optional — what this data is and where it comes from.</span><textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        </div>
        <div className="card card-pad stack">
          <h2>Structure</h2>
          {imp.file_kind === "xlsx" && imp.sheet_names.length > 0 && (
            <label className="field">
              Sheet
              <select className="input" value={p.sheet ?? ""} disabled={busy} onChange={(e) => repropose({ sheet: e.target.value, header_row: null })}>
                {imp.sheet_names.map((s) => (
                  <option key={s.name} value={s.name}>{s.name}{s.hidden ? " (hidden)" : ""}</option>
                ))}
              </select>
            </label>
          )}
          <div className="grid-2">
            <label className="field">
              Header row <span className="hint">Detected with {Math.round(p.confidence * 100)}% confidence</span>
              <select className="input" value={p.header_row} disabled={busy} onChange={(e) => repropose({ header_row: Number(e.target.value) })}>
                {headerOptions.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
              </select>
            </label>
            <label className="field">
              Number &amp; date format
              <select className="input" value={p.locale} disabled={busy} onChange={(e) => repropose({ locale: e.target.value })}>
                {LOCALES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          </div>
          <label className="field">
            Quarantine tolerance <span className="hint">Fail the import if more than this share of rows can't be read.</span>
            <select className="input" value={tolerance} onChange={(e) => setTolerance(Number(e.target.value))}>
              {[0, 1, 5, 10, 25].map((t) => <option key={t} value={t}>{t}%</option>)}
            </select>
          </label>
          {busy && <div className="row muted small"><RefreshCw size={14} /> Re-analysing…</div>}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head"><h2>Columns</h2><span className="muted small">{cols.filter((c) => c.include).length} of {cols.length} included</span></div>
        <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>Use</th>
                <th>Name</th>
                <th>Type</th>
                <th>Role</th>
                <th>Evidence</th>
                <th className="num">Empty</th>
              </tr>
            </thead>
            <tbody>
              {cols.map((c, i) => {
                const best = c.candidates.find((x) => x.type === c.type);
                return (
                  <tr key={c.index} className={`${c.include ? "" : "col-excluded"} ${c.include && c.ambiguous ? "amb" : ""}`}>
                    <td><input type="checkbox" aria-label={`Include ${c.name}`} checked={c.include} onChange={(e) => update(i, { include: e.target.checked })} /></td>
                    <td>
                      <input className="input input-sm" style={{ minWidth: 160 }} value={c.name} onChange={(e) => update(i, { name: e.target.value })} aria-label="Column name" />
                      {c.source_name && c.source_name !== c.name && <div className="tiny muted">from “{c.source_name}”</div>}
                    </td>
                    <td>
                      <div className="row" style={{ flexWrap: "nowrap" }}>
                        <TypeDot type={c.type} />
                        <select className="input input-sm" value={c.type} onChange={(e) => update(i, { type: e.target.value as PrismType })} aria-label="Column type">
                          {TYPES.map((t) => {
                            const cand = c.candidates.find((x) => x.type === t);
                            return <option key={t} value={t}>{t}{cand && t !== "string" ? ` (${Math.round(cand.confidence * 100)}%)` : ""}</option>;
                          })}
                        </select>
                      </div>
                    </td>
                    <td>
                      <select className="input input-sm" value={c.role} onChange={(e) => update(i, { role: e.target.value })} aria-label="Column role">
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td className="small" style={{ whiteSpace: "normal", minWidth: 220 }}>
                      {best?.samples.length ? <span className="muted">e.g. {best.samples.slice(0, 3).map((s) => `“${s}”`).join(", ")}</span> : null}
                      {best?.failures.length ? <div style={{ color: "var(--warning)" }}>won't parse: {best.failures.map((s) => `“${s}”`).join(", ")}</div> : null}
                      {c.notes.filter((n) => !n.startsWith("Only")).map((n) => <div key={n} className="muted">{n}</div>)}
                    </td>
                    <td className="num muted">{Math.round(c.null_ratio * 100)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Preview</h2><span className="muted small">First {p.preview.length} data rows as read from the file</span></div>
        <div className="table-wrap" style={{ border: 0, borderRadius: 0, maxHeight: 420 }}>
          <table className="table">
            <thead>
              <tr>{cols.map((c) => <th key={c.index} className={c.include ? "" : "col-excluded"}>{c.name}</th>)}</tr>
            </thead>
            <tbody>
              {p.preview.map((row, r) => (
                <tr key={r}>{cols.map((c) => <td key={c.index} className={c.include ? "" : "col-excluded"}>{row[c.index] || <span className="muted">—</span>}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
