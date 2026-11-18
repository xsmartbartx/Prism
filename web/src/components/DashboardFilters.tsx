import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Filter, Plus, X } from "lucide-react";
import { get, post, type DashboardFilter, type FilterField, type FilterOptions } from "../api";

/** URL parameters that carry filter selections: fv<i> (values), ff<i> / ft<i> (date from / to). */
export const FILTER_PARAM = /^f[vft]\d+$/;

export function filterQuery(params: URLSearchParams): string {
  const out = new URLSearchParams();
  params.forEach((v, k) => { if (FILTER_PARAM.test(k)) out.append(k, v); });
  const s = out.toString();
  return s ? `&${s}` : "";
}

/** Viewer controls: one per dashboard filter, kept in the URL so a link reproduces the view. */
export function FilterBar({ dashboardId, filters, params, setParams }: {
  dashboardId: string;
  filters: DashboardFilter[];
  params: URLSearchParams;
  setParams: (p: URLSearchParams) => void;
}) {
  const active = [...params.keys()].some((k) => FILTER_PARAM.test(k));
  const update = (mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next);
  };
  return (
    <div className="filter-bar" role="group" aria-label="Dashboard filters">
      <Filter size={15} className="muted" aria-hidden />
      {filters.map((f, i) =>
        f.kind === "date_range" ? (
          <DateRange key={`${f.field}-${i}`} dashboardId={dashboardId} index={i} filter={f} params={params} update={update} />
        ) : (
          <ValuePicker key={`${f.field}-${i}`} dashboardId={dashboardId} index={i} filter={f} params={params} update={update} />
        ),
      )}
      {active && (
        <button className="btn btn-ghost btn-sm" onClick={() => update((p) => [...p.keys()].filter((k) => FILTER_PARAM.test(k)).forEach((k) => p.delete(k)))}>
          <X size={14} /> Clear
        </button>
      )}
    </div>
  );
}

type ControlProps = {
  dashboardId: string;
  index: number;
  filter: DashboardFilter;
  params: URLSearchParams;
  update: (mutate: (p: URLSearchParams) => void) => void;
};

function useOptions(dashboardId: string, index: number, enabled: boolean) {
  const [opts, setOpts] = useState<FilterOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || opts) return;
    let current = true; // a closed picker or a newer request makes this response stale
    setError(null);
    get<FilterOptions>(`/api/v1/dashboards/${dashboardId}/filters/${index}/options`)
      .then((o) => { if (current) { setError(null); setOpts(o); } })
      .catch((e) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [dashboardId, index, enabled, opts]);
  return { opts, error };
}

function ValuePicker({ dashboardId, index, filter, params, update }: ControlProps) {
  const key = `fv${index}`;
  const selected = params.getAll(key);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const { opts, error } = useOptions(dashboardId, index, open);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  // Selected values stay listed even when they are not among the offered ones, so they can be unticked.
  const shown = useMemo(() => {
    const offered = opts?.values ?? [];
    const all = [...selected.filter((v) => !offered.includes(v)), ...offered];
    return all.filter((v) => v.toLowerCase().includes(q.toLowerCase()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts, q, selected.join("\u0000")]);
  const toggle = (v: string) => update((p) => {
    const cur = p.getAll(key);
    p.delete(key);
    (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]).forEach((x) => p.append(key, x));
  });
  const summary = selected.length === 0 ? "All" : selected.length <= 2 ? selected.join(", ") : `${selected.length} selected`;

  return (
    <div className="filter-ctl" ref={ref}>
      <button className={`btn btn-sm ${selected.length ? "btn-active" : ""}`} aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="muted">{filter.label}:</span> <span className="truncate" style={{ maxWidth: 180 }}>{summary}</span> <ChevronDown size={14} />
      </button>
      {open && (
        <div className="filter-pop" role="dialog" aria-label={filter.label}>
          {error ? (
            <div className="muted small">{error}</div>
          ) : !opts ? (
            <div className="muted small">Loading…</div>
          ) : (
            <>
              {(opts.values?.length ?? 0) > 8 && (
                <input className="input input-sm" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} autoFocus aria-label={`Search ${filter.label}`} />
              )}
              <div className="filter-opts">
                {shown.map((v) => (
                  <label key={v} className="filter-opt">
                    <input type="checkbox" checked={selected.includes(v)} onChange={() => toggle(v)} /> <span className="truncate">{v}</span>
                  </label>
                ))}
                {shown.length === 0 && <div className="muted small">No values</div>}
              </div>
              {opts.truncated && <div className="muted small">Showing the first {opts.values?.length} values</div>}
              {(opts.omitted_long ?? 0) > 0 && <div className="muted small">Some values are too long to filter by</div>}
              {selected.length > 0 && (
                <button className="btn btn-ghost btn-sm" onClick={() => update((p) => p.delete(key))}>Clear {filter.label}</button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function DateRange({ dashboardId, index, filter, params, update }: ControlProps) {
  const { opts } = useOptions(dashboardId, index, true);
  const from = params.get(`ff${index}`) ?? "";
  const to = params.get(`ft${index}`) ?? "";
  const set = (k: string, v: string) => update((p) => (v ? p.set(k, v) : p.delete(k)));
  const bounds = { min: opts?.min ?? undefined, max: opts?.max ?? undefined };
  return (
    <div className={`filter-ctl filter-dates ${from || to ? "is-active" : ""}`}>
      <span className="muted small">{filter.label}</span>
      <input type="date" className="input input-sm" value={from} {...bounds} onChange={(e) => set(`ff${index}`, e.target.value)} aria-label={`${filter.label} from`} />
      <span className="muted small">–</span>
      <input type="date" className="input input-sm" value={to} {...bounds} onChange={(e) => set(`ft${index}`, e.target.value)} aria-label={`${filter.label} to`} />
    </div>
  );
}

/** Author controls: choose which fields the dashboard can be filtered by. */
export function FilterEditor({ chartIds, filters, onChange }: {
  chartIds: string[];
  filters: DashboardFilter[];
  onChange: (f: DashboardFilter[]) => void;
}) {
  const [fields, setFields] = useState<FilterField[] | null>(null);
  const idsKey = chartIds.join(",");
  useEffect(() => {
    if (!chartIds.length) { setFields([]); return; }
    let current = true; // a newer layout makes this response stale
    post<FilterField[]>("/api/v1/dashboards/filter-fields", { chart_ids: chartIds })
      .then((f) => { if (current) setFields(f); })
      .catch(() => { if (current) setFields([]); });
    return () => { current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const taken = new Set(filters.map((f) => f.field));
  const choices = (fields ?? []).filter((f) => !taken.has(f.field)).flatMap((f) =>
    f.kinds.map((kind) => ({ value: `${kind}|${f.field}`, label: `${f.field}${kind === "date_range" ? " (date range)" : f.kinds.length > 1 ? " (list of dates)" : ""} · ${f.charts} chart${f.charts === 1 ? "" : "s"}` })),
  );
  const missing = (f: DashboardFilter) => fields !== null && !fields.some((x) => x.field === f.field);

  return (
    <div className="card card-pad stack" style={{ gap: 10 }}>
      <div className="row-between">
        <h3 className="row" style={{ gap: 6 }}><Filter size={16} /> Filters</h3>
        <span className="muted small">Viewers narrow every chart that has the field.</span>
      </div>
      {filters.length === 0 && <p className="muted small" style={{ margin: 0 }}>No filters yet. Add one so viewers can pick a region, a period, a product…</p>}
      {filters.map((f, i) => (
        <div key={f.field} className="row" style={{ flexWrap: "nowrap" }}>
          <input className="input input-sm" style={{ maxWidth: 220 }} value={f.label} maxLength={80} aria-label={`Label for ${f.field}`}
            onChange={(e) => onChange(filters.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
          <span className="chip">{f.field} · {f.kind === "date_range" ? "date range" : "values"}</span>
          {missing(f) && <span className="badge badge-warning">no chart has this field</span>}
          <span style={{ flex: 1 }} />
          <button className="btn btn-ghost btn-icon btn-sm" aria-label={`Remove filter ${f.label}`} onClick={() => onChange(filters.filter((_, j) => j !== i))}><X size={14} /></button>
        </div>
      ))}
      {filters.length < 6 && (
        <div className="row">
          <Plus size={14} className="muted" aria-hidden />
          <select className="input input-sm" style={{ maxWidth: 360 }} value="" disabled={!choices.length} aria-label="Add a filter"
            onChange={(e) => {
              const [kind, ...rest] = e.target.value.split("|");
              const field = rest.join("|");
              if (field) onChange([...filters, { field, kind: kind as DashboardFilter["kind"], label: field }]);
            }}>
            <option value="">{fields === null ? "Loading fields…" : choices.length ? "Add a filter…" : "No more fields to filter by"}</option>
            {choices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
      )}
    </div>
  );
}
