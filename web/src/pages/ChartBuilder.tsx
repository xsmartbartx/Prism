import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AreaChart, BarChart3, Download, Hash, LineChart, PieChart, Plus, Save, ScatterChart, Share2, Sparkles, Table2, Trash2, Wand2, X } from "lucide-react";
import { can, del, download, get, post, put, type Aggregation, type Chart, type ColumnContract, type Dataset, type Filter, type QueryResult, type QuerySpec, type ViewSpec } from "../api";
import { effectiveTheme, useApp, useLoad } from "../app-state";
import ShareDialog from "../components/ShareDialog";
import { ChartSvg, Confirm, DataTable, ErrorBox, PageLoading, TypeDot } from "../components/ui";

type Mark = ViewSpec["mark"];
type Fn = Aggregation["function"];

interface State {
  mark: Mark;
  x: string;
  ys: { column: string; fn: Fn }[];
  color: string;
  grain: string;
  filters: Filter[];
  sortBy: string;
  sortDir: "asc" | "desc";
  limit: number;
  title: string;
  numberFormat: string;
  currency: string;
  orientation: "vertical" | "horizontal";
  stacked: boolean;
  showValues: boolean;
}

const MARKS: { mark: Mark; label: string; icon: JSX.Element }[] = [
  { mark: "bar", label: "Bar", icon: <BarChart3 size={18} /> },
  { mark: "line", label: "Line", icon: <LineChart size={18} /> },
  { mark: "area", label: "Area", icon: <AreaChart size={18} /> },
  { mark: "pie", label: "Donut", icon: <PieChart size={18} /> },
  { mark: "scatter", label: "Scatter", icon: <ScatterChart size={18} /> },
  { mark: "kpi", label: "KPI", icon: <Hash size={18} /> },
  { mark: "table", label: "Table", icon: <Table2 size={18} /> },
];
const FNS: Fn[] = ["sum", "avg", "count", "count_distinct", "min", "max", "median"];
const OPS: Record<string, string> = { eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", in: "is one of", not_in: "is not one of", contains: "contains", starts_with: "starts with", is_null: "is empty", not_null: "is not empty" };

const EMPTY: State = { mark: "bar", x: "", ys: [], color: "", grain: "", filters: [], sortBy: "", sortDir: "desc", limit: 50, title: "", numberFormat: "auto", currency: "USD", orientation: "vertical", stacked: false, showValues: false };

function outName(ys: State["ys"], i: number): string {
  const y = ys[i];
  if (y.column === "*") return "count";
  const dup = ys.filter((o) => o.column === y.column).length > 1;
  return dup ? `${y.fn}_${y.column}` : y.column;
}

/** Turn the builder state into (query, view) specs. */
export function toSpecs(s: State): { query: QuerySpec; view: ViewSpec } {
  const measures: Aggregation[] = s.ys.map((y, i) => ({ column: y.column, function: y.column === "*" ? "count" : y.fn, alias: outName(s.ys, i) === y.column ? null : outName(s.ys, i) }));
  const yNames = s.ys.map((_, i) => outName(s.ys, i));
  const filters = s.filters.filter((f) => {
    if (!f.column) return false;
    if (f.operator === "is_null" || f.operator === "not_null") return true;
    if (Array.isArray(f.value)) return f.value.length > 0;
    return f.value !== "" && f.value !== null && f.value !== undefined && !(typeof f.value === "number" && Number.isNaN(f.value));
  });
  const display = { title: s.title || null, number_format: s.numberFormat, currency: s.currency, orientation: s.orientation, stacked: s.stacked, show_values: s.showValues };
  const sort = s.sortBy ? [{ column: s.sortBy, direction: s.sortDir }] : [];
  if (s.mark === "kpi") {
    return { query: { measures: measures.slice(0, 1), filters }, view: { mark: "kpi", encodings: yNames.slice(0, 1).map((f) => ({ channel: "y", field: f })), ...display, width: 360, height: 180 } };
  }
  if (s.mark === "scatter") {
    const cols = [s.x, ...s.ys.map((y) => y.column)].filter((c) => c && c !== "*");
    if (s.color) cols.push(s.color);
    return {
      query: { columns: Array.from(new Set(cols)), filters, limit: 5000 },
      view: { mark: "scatter", encodings: [{ channel: "x", field: s.x }, ...(s.ys[0] ? [{ channel: "y" as const, field: s.ys[0].column }] : []), ...(s.color ? [{ channel: "color" as const, field: s.color }] : [])], ...display },
    };
  }
  if (s.mark === "table" && !s.ys.length) {
    const cols = [s.x, s.color].filter(Boolean);
    return { query: { columns: cols, filters, sort, limit: s.limit }, view: { mark: "table", encodings: cols.map((c) => ({ channel: "x", field: c })), ...display } };
  }
  const dims = [s.x, s.mark === "pie" ? "" : s.color].filter(Boolean);
  const ys = s.color && s.mark !== "pie" ? yNames.slice(0, 1) : s.mark === "pie" ? yNames.slice(0, 1) : yNames;
  const encodings: ViewSpec["encodings"] = [];
  if (s.x) encodings.push({ channel: "x", field: s.x });
  ys.forEach((f) => encodings.push({ channel: "y", field: f }));
  if (s.color && s.mark !== "pie") encodings.push({ channel: "color", field: s.color });
  return {
    query: { dimensions: dims, measures: s.color && s.mark !== "pie" ? measures.slice(0, 1) : s.mark === "pie" ? measures.slice(0, 1) : measures, filters, sort, limit: s.limit, time_grain: s.grain && s.x ? { [s.x]: s.grain } : {} },
    view: { mark: s.mark, encodings, ...display, time_grain: s.grain || null },
  };
}

/** Recover builder state from saved or recommended specs. */
export function fromSpecs(q: QuerySpec, v: ViewSpec): State {
  const x = v.encodings.find((e) => e.channel === "x")?.field ?? q.dimensions?.[0] ?? q.columns?.[0] ?? "";
  const color = v.encodings.find((e) => e.channel === "color")?.field ?? (q.dimensions && q.dimensions.length > 1 ? q.dimensions[1] : "");
  let ys: State["ys"] = (q.measures ?? []).map((m) => ({ column: m.column, fn: m.function }));
  if (v.mark === "scatter") ys = v.encodings.filter((e) => e.channel === "y").map((e) => ({ column: e.field, fn: "sum" as Fn }));
  const sort = q.sort?.[0];
  return {
    ...EMPTY,
    mark: v.mark,
    x: v.mark === "kpi" ? "" : x,
    ys,
    color,
    grain: (q.time_grain && x && q.time_grain[x]) || "",
    filters: q.filters ?? [],
    sortBy: sort?.column ?? "",
    sortDir: sort?.direction ?? "desc",
    limit: q.limit ?? 50,
    title: v.title ?? "",
    numberFormat: v.number_format ?? "auto",
    currency: v.currency ?? "USD",
    orientation: v.orientation ?? "vertical",
    stacked: !!v.stacked,
    showValues: !!v.show_values,
  };
}

function defaultState(cols: ColumnContract[]): State {
  const measure = cols.find((c) => c.role === "measure" && (c.type === "integer" || c.type === "float"));
  const time = cols.find((c) => c.type === "date");
  const dim = cols.find((c) => c.role === "dimension" && c.type === "string") ?? cols.find((c) => c.type === "string");
  if (time && measure) return { ...EMPTY, mark: "line", x: time.name, ys: [{ column: measure.name, fn: "sum" }], grain: "month", sortBy: time.name, sortDir: "asc", limit: 500 };
  if (dim && measure) return { ...EMPTY, x: dim.name, ys: [{ column: measure.name, fn: "sum" }], sortBy: measure.name, sortDir: "desc", limit: 25 };
  if (dim) return { ...EMPTY, x: dim.name, ys: [{ column: "*", fn: "count" }], sortBy: "count", sortDir: "desc", limit: 25 };
  return { ...EMPTY, mark: "table", x: cols[0]?.name ?? "" };
}

export default function ChartBuilder() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { me, toast, theme } = useApp();
  const datasets = useLoad<Dataset[]>("/api/v1/datasets");
  const uiTheme = effectiveTheme(theme);
  const [chart, setChart] = useState<Chart | null>(null);
  const [datasetId, setDatasetId] = useState(params.get("dataset") ?? "");
  const [ds, setDs] = useState<Dataset | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<{ svg: string; columns: string[]; rows: Record<string, unknown>[]; total: number } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [showData, setShowData] = useState(false);
  const [saving, setSaving] = useState(false);
  const [share, setShare] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const seq = useRef(0);
  const editable = can.explore(me?.role);

  // Load existing chart
  useEffect(() => {
    if (!id) return;
    get<Chart>(`/api/v1/charts/${id}`)
      .then((c) => {
        setChart(c);
        setName(c.name);
        setDatasetId(c.dataset_id);
        setState(fromSpecs(c.query, c.view));
      })
      .catch((e) => setLoadError(e.message));
  }, [id]);

  // Default to first dataset for new charts
  useEffect(() => {
    if (!id && !datasetId && datasets.data?.length) setDatasetId(datasets.data[0].id);
  }, [id, datasetId, datasets.data]);

  // Load dataset columns
  useEffect(() => {
    if (!datasetId) return;
    get<Dataset>(`/api/v1/datasets/${datasetId}`)
      .then((d) => {
        setDs(d);
        if (!id) {
          setState(defaultState(d.current_version?.columns ?? []));
          setName((n) => n || `${d.name} chart`);
        }
      })
      .catch((e) => setLoadError(e.message));
  }, [datasetId, id]);

  const specs = useMemo(() => (state ? toSpecs(state) : null), [state]);

  // Debounced live preview
  useEffect(() => {
    if (!specs || !datasetId) return;
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      try {
        const res = await post<QueryResult & { svg: string }>("/api/v1/charts/preview", { dataset_id: datasetId, query: specs.query, view: { ...specs.view, theme: uiTheme } });
        if (mine === seq.current) {
          setPreview(res);
          setPreviewError(null);
        }
      } catch (e) {
        if (mine === seq.current) setPreviewError((e as Error).message);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [specs, datasetId, uiTheme]);

  if (loadError) return <ErrorBox error={loadError} />;
  if (datasets.data && datasets.data.length === 0)
    return <ErrorBox error="There are no datasets yet. Import a file first, then build charts on it." />;
  if (!state || !ds) return <PageLoading />;

  const cols = ds.current_version?.columns ?? [];
  const numeric = cols.filter((c) => c.type === "integer" || c.type === "float");
  const set = (p: Partial<State>) => setState((s) => (s ? { ...s, ...p } : s));
  const xCol = cols.find((c) => c.name === state.x);
  const outputs = specs ? (specs.query.columns ?? [...(specs.query.dimensions ?? []), ...state.ys.map((_, i) => outName(state.ys, i))]) : [];

  const save = async () => {
    if (!specs) return;
    setSaving(true);
    try {
      const body = { dataset_id: datasetId, name: name.trim() || "Untitled chart", description: chart?.description ?? "", query: specs.query, view: specs.view };
      const saved = chart ? await put<Chart>(`/api/v1/charts/${chart.id}`, body) : await post<Chart>("/api/v1/charts", body);
      setChart(saved);
      toast("Chart saved");
      if (!id) nav(`/charts/${saved.id}`, { replace: true });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  const suggest = async () => {
    const fields = [state.x, state.color, ...state.ys.map((y) => y.column)].filter((f) => f && f !== "*");
    if (!fields.length) return toast("Pick at least one field first", "error");
    try {
      const rec = await post<{ query: QuerySpec; view: ViewSpec; reason: string }>(`/api/v1/datasets/${datasetId}/recommend`, { fields: Array.from(new Set(fields)).slice(0, 6), title: state.title || null });
      setState(fromSpecs(rec.query, rec.view));
      toast(rec.reason);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const fieldSelect = ({ value, onChange, allowEmpty, only }: { value: string; onChange: (v: string) => void; allowEmpty?: string; only?: ColumnContract[] }) => (
    <select className="input input-sm" value={value} onChange={(e) => onChange(e.target.value)} disabled={!editable}>
      {allowEmpty !== undefined && <option value="">{allowEmpty}</option>}
      {(only ?? cols).map((c) => <option key={c.name} value={c.name}>{c.name} · {c.type}</option>)}
    </select>
  );

  return (
    <>
      <div className="page-head">
        <div className="grow">
          <input className="input" style={{ fontSize: 20, fontWeight: 650, height: 40, maxWidth: 520 }} value={name} onChange={(e) => setName(e.target.value)} aria-label="Chart name" disabled={!editable} />
          <p className="row" style={{ marginTop: 8 }}>
            <span className="muted">Dataset</span>
            <select className="input input-sm" style={{ width: "auto" }} value={datasetId} disabled={!!chart || !editable} onChange={(e) => { setDatasetId(e.target.value); setPreview(null); }}>
              {datasets.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </p>
        </div>
        <div className="row">
          {chart && <button className="btn" onClick={() => download(`/api/v1/charts/${chart.id}/export?format=svg`).catch((e) => toast(e.message, "error"))}><Download size={16} /> SVG</button>}
          {chart && <button className="btn" onClick={() => download(`/api/v1/charts/${chart.id}/export?format=xlsx`).catch((e) => toast(e.message, "error"))}><Download size={16} /> Data</button>}
          {chart && editable && <button className="btn" onClick={() => setShare(true)}><Share2 size={16} /> Share</button>}
          {chart && editable && <button className="btn btn-ghost btn-icon" aria-label="Delete chart" onClick={() => setConfirmDelete(true)}><Trash2 size={16} /></button>}
          {editable && <button className="btn btn-primary" onClick={save} disabled={saving || !!previewError}><Save size={16} /> {saving ? "Saving…" : "Save"}</button>}
        </div>
      </div>

      <div className="builder">
        <div className="card builder-panel">
          <div className="panel-section">
            <h3>Chart type</h3>
            <div className="mark-grid">
              {MARKS.map((m) => (
                <button key={m.mark} className={`mark-btn ${state.mark === m.mark ? "active" : ""}`} onClick={() => set({ mark: m.mark, ys: m.mark === "kpi" && !state.ys.length ? [{ column: numeric[0]?.name ?? "*", fn: numeric[0] ? "sum" : "count" }] : state.ys })} disabled={!editable} aria-pressed={state.mark === m.mark}>
                  {m.icon}{m.label}
                </button>
              ))}
            </div>
            {editable && <button className="btn btn-sm" onClick={suggest}><Wand2 size={14} /> Suggest best chart for these fields</button>}
          </div>

          <div className="panel-section">
            <h3>Data</h3>
            {state.mark !== "kpi" && (
              <label className="field">
                {state.mark === "scatter" ? "X axis (number)" : state.mark === "pie" ? "Slices" : state.mark === "table" ? "Group by" : "X axis"}
                {fieldSelect({ value: state.x, onChange: (v) => set({ x: v, grain: cols.find((c) => c.name === v)?.type === "date" ? state.grain || "month" : "" }), only: state.mark === "scatter" ? numeric : undefined, allowEmpty: state.mark === "table" ? "—" : undefined })}
              </label>
            )}
            {xCol?.type === "date" && state.mark !== "scatter" && state.mark !== "kpi" && (
              <label className="field">
                Time bucket
                <select className="input input-sm" value={state.grain} onChange={(e) => set({ grain: e.target.value })} disabled={!editable}>
                  <option value="">Exact date</option>
                  {["day", "week", "month", "quarter", "year"].map((g) => <option key={g} value={g}>{g[0].toUpperCase() + g.slice(1)}</option>)}
                </select>
              </label>
            )}
            <div className="field" style={{ fontWeight: 550, fontSize: 13 }}>
              {state.mark === "scatter" ? "Y axis (number)" : "Values"}
              <div className="stack" style={{ gap: 6, marginTop: 6 }}>
                {state.ys.map((y, i) => (
                  <div className="row" key={i} style={{ flexWrap: "nowrap" }}>
                    {state.mark !== "scatter" && (
                      <select className="input input-sm" style={{ width: 118 }} value={y.column === "*" ? "count" : y.fn} disabled={!editable || y.column === "*"} onChange={(e) => set({ ys: state.ys.map((o, j) => (j === i ? { ...o, fn: e.target.value as Fn } : o)) })}>
                        {FNS.map((f) => <option key={f} value={f}>{f.replace("_", " ")}</option>)}
                      </select>
                    )}
                    <select className="input input-sm" value={y.column} disabled={!editable} onChange={(e) => set({ ys: state.ys.map((o, j) => (j === i ? { column: e.target.value, fn: e.target.value === "*" ? "count" : numeric.some((c) => c.name === e.target.value) ? o.fn : "count" } : o)) })}>
                      {state.mark !== "scatter" && <option value="*">Row count</option>}
                      {(state.mark === "scatter" ? numeric : cols).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                    </select>
                    {editable && <button className="btn btn-ghost btn-icon btn-sm" aria-label="Remove value" onClick={() => set({ ys: state.ys.filter((_, j) => j !== i) })}><X size={14} /></button>}
                  </div>
                ))}
                {editable && (state.ys.length === 0 || ["bar", "line", "area", "table"].includes(state.mark)) && state.ys.length < 6 && (
                  <button className="btn btn-sm" onClick={() => set({ ys: [...state.ys, { column: numeric[0]?.name ?? "*", fn: numeric[0] ? "sum" : "count" }] })}><Plus size={14} /> Add value</button>
                )}
              </div>
            </div>
            {["bar", "line", "area", "scatter", "table"].includes(state.mark) && (
              <label className="field">
                {state.mark === "table" ? "Then by" : "Split by (colour)"}
                {fieldSelect({ value: state.color, onChange: (v) => set({ color: v }), allowEmpty: "None", only: cols.filter((c) => c.type !== "float") })}
              </label>
            )}
          </div>

          <div className="panel-section">
            <div className="row-between"><h3>Filters</h3>{editable && <button className="btn btn-ghost btn-sm" onClick={() => set({ filters: [...state.filters, { column: cols[0]?.name ?? "", operator: "eq", value: "" }] })}><Plus size={14} /> Add</button>}</div>
            {state.filters.length === 0 && <p className="muted small">All rows are included.</p>}
            {state.filters.map((f, i) => (
              <FilterRow key={i} f={f} cols={cols} disabled={!editable} onChange={(nf) => set({ filters: state.filters.map((o, j) => (j === i ? nf : o)) })} onRemove={() => set({ filters: state.filters.filter((_, j) => j !== i) })} />
            ))}
          </div>

          {state.mark !== "kpi" && state.mark !== "scatter" && (
            <div className="panel-section">
              <h3>Sort &amp; limit</h3>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <select className="input input-sm" value={state.sortBy} onChange={(e) => set({ sortBy: e.target.value })} disabled={!editable}>
                  <option value="">Default order</option>
                  {outputs.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                <select className="input input-sm" style={{ width: 110 }} value={state.sortDir} onChange={(e) => set({ sortDir: e.target.value as "asc" | "desc" })} disabled={!editable || !state.sortBy}>
                  <option value="desc">High → low</option>
                  <option value="asc">Low → high</option>
                </select>
              </div>
              <label className="field">
                Show at most
                <select className="input input-sm" value={state.limit} onChange={(e) => set({ limit: Number(e.target.value) })} disabled={!editable}>
                  {[5, 10, 25, 50, 100, 500, 5000].map((n) => <option key={n} value={n}>{n} rows</option>)}
                </select>
              </label>
            </div>
          )}

          <div className="panel-section">
            <h3>Display</h3>
            <label className="field">Title<input className="input input-sm" value={state.title} onChange={(e) => set({ title: e.target.value })} placeholder="Shown above the chart" disabled={!editable} /></label>
            <div className="grid-2" style={{ gap: 8 }}>
              <label className="field">
                Numbers
                <select className="input input-sm" value={state.numberFormat} onChange={(e) => set({ numberFormat: e.target.value })} disabled={!editable}>
                  {["auto", "compact", "integer", "decimal", "percent", "currency"].map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </label>
              {state.numberFormat === "currency" && (
                <label className="field">
                  Currency
                  <select className="input input-sm" value={state.currency} onChange={(e) => set({ currency: e.target.value })} disabled={!editable}>
                    {["USD", "EUR", "GBP", "PLN", "CHF", "JPY", "CAD", "AUD"].map((c) => <option key={c}>{c}</option>)}
                  </select>
                </label>
              )}
            </div>
            {state.mark === "bar" && (
              <label className="check"><input type="checkbox" checked={state.orientation === "horizontal"} onChange={(e) => set({ orientation: e.target.checked ? "horizontal" : "vertical" })} disabled={!editable} /> Horizontal bars</label>
            )}
            {(state.mark === "bar" || state.mark === "area") && state.color && (
              <label className="check"><input type="checkbox" checked={state.stacked} onChange={(e) => set({ stacked: e.target.checked })} disabled={!editable} /> Stack series</label>
            )}
            {["bar", "line"].includes(state.mark) && (
              <label className="check"><input type="checkbox" checked={state.showValues} onChange={(e) => set({ showValues: e.target.checked })} disabled={!editable} /> Show value labels</label>
            )}
          </div>
        </div>

        <div className="stack">
          <div className="card card-pad">
            {previewError ? (
              <ErrorBox error={previewError} />
            ) : (
              <ChartSvg svg={preview?.svg ?? null} minHeight={400} />
            )}
          </div>
          <div className="row-between">
            <span className="muted small">
              {preview ? <>{preview.total.toLocaleString()} result row{preview.total === 1 ? "" : "s"}{preview.total > preview.rows.length ? ` (showing ${preview.rows.length})` : ""}</> : "Rendering…"}
            </span>
            <button className="btn btn-sm" onClick={() => setShowData((x) => !x)}><Sparkles size={14} /> {showData ? "Hide" : "Show"} data</button>
          </div>
          {showData && preview && <DataTable columns={preview.columns} rows={preview.rows} />}
          <div className="muted tiny">
            Columns: {cols.map((c) => <span key={c.name} className="row" style={{ display: "inline-flex", marginRight: 10, gap: 4 }}><TypeDot type={c.type} />{c.name}</span>)}
          </div>
        </div>
      </div>

      {share && chart && <ShareDialog type="chart" id={chart.id} name={chart.name} onClose={() => setShare(false)} />}
      {confirmDelete && chart && (
        <Confirm
          title="Delete chart?"
          message={<>Delete <strong>{chart.name}</strong>? It is removed from dashboards and its shared links stop working.</>}
          onClose={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await del(`/api/v1/charts/${chart.id}`);
            toast("Chart deleted");
            nav("/charts");
          }}
        />
      )}
    </>
  );
}

function FilterRow({ f, cols, onChange, onRemove, disabled }: { f: Filter; cols: ColumnContract[]; onChange: (f: Filter) => void; onRemove: () => void; disabled: boolean }) {
  const col = cols.find((c) => c.name === f.column);
  const type = col?.type ?? "string";
  const ops = Object.keys(OPS).filter((op) => {
    if (op === "contains" || op === "starts_with") return type === "string";
    if (["gt", "gte", "lt", "lte"].includes(op)) return type !== "boolean";
    return true;
  });
  const needsValue = f.operator !== "is_null" && f.operator !== "not_null";
  const list = f.operator === "in" || f.operator === "not_in";
  const coerce = (raw: string): unknown => {
    if (type === "integer" || type === "float") return raw === "" ? "" : Number(raw);
    if (type === "boolean") return raw === "true";
    return raw;
  };
  return (
    <div className="stack" style={{ gap: 4, padding: 8, border: "1px solid var(--border)", borderRadius: 6 }}>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <select className="input input-sm" value={f.column} disabled={disabled} onChange={(e) => onChange({ column: e.target.value, operator: "eq", value: "" })}>
          {cols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <button className="btn btn-ghost btn-icon btn-sm" aria-label="Remove filter" onClick={onRemove} disabled={disabled}><X size={14} /></button>
      </div>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <select className="input input-sm" style={{ width: 120 }} value={f.operator} disabled={disabled} onChange={(e) => onChange({ ...f, operator: e.target.value, value: e.target.value === "in" || e.target.value === "not_in" ? [] : "" })}>
          {ops.map((op) => <option key={op} value={op}>{OPS[op]}</option>)}
        </select>
        {needsValue &&
          (type === "boolean" && !list ? (
            <select className="input input-sm" value={String(f.value)} disabled={disabled} onChange={(e) => onChange({ ...f, value: e.target.value === "true" })}>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <input
              className="input input-sm"
              type={type === "date" && !list ? "date" : (type === "integer" || type === "float") && !list ? "number" : "text"}
              placeholder={list ? "comma, separated" : "value"}
              disabled={disabled}
              value={list ? (Array.isArray(f.value) ? (f.value as unknown[]).join(", ") : "") : String(f.value ?? "")}
              onChange={(e) =>
                onChange({ ...f, value: list ? e.target.value.split(",").map((x) => x.trim()).filter(Boolean).map(coerce) : coerce(e.target.value) })
              }
            />
          ))}
      </div>
    </div>
  );
}
