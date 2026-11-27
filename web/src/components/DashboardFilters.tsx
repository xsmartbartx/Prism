import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Filter, Plus, X } from "lucide-react";
import { get, post, type DashboardFilter, type FilterField, type FilterOptions } from "../api";

/**
 * URL parameters that carry filter selections: fv<i> (values), ff<i> / ft<i> (date from / to),
 * fr<i> (a period relative to today, "custom" or "all"), and the cross-filter a click in a tile
 * sets: xf (field), xv (values), xg (time grain), xc (clicked chart).
 */
export const FILTER_PARAM = /^(f[vftr]\d+|x[fvgc])$/;

/** Periods relative to today, worked out by the server (same keys as its PRESETS). */
export const DATE_PRESETS: [string, string][] = [
  ["last_7_days", "Last 7 days"], ["last_30_days", "Last 30 days"], ["last_90_days", "Last 90 days"],
  ["this_month", "This month"], ["last_month", "Last month"],
  ["this_quarter", "This quarter"], ["last_quarter", "Last quarter"],
  ["this_year", "This year"], ["last_year", "Last year"], ["last_12_months", "Last 12 full months"],
];
export const presetLabel = (key: string): string => DATE_PRESETS.find(([k]) => k === key)?.[1] ?? key;

/** What a date-range filter currently selects: a period key, "custom" (dates) or "all". */
export function dateMode(params: URLSearchParams, index: number, filter: DashboardFilter): string {
  const period = params.get(`fr${index}`);
  if (period) return period;
  if (params.get(`ff${index}`) || params.get(`ft${index}`)) return "custom";
  return filter.default || "all";
}
const CROSS_KEYS = ["xf", "xv", "xg", "xc"];

export interface CrossFilter { field: string; values: string[]; grain: string | null; source: string }

export function readCross(params: URLSearchParams): CrossFilter | null {
  const field = params.get("xf");
  const values = params.getAll("xv").filter(Boolean);
  const source = params.get("xc");
  if (!field || !values.length || !source) return null;
  return { field, values, grain: params.get("xg"), source };
}

/** The next URL after clicking a mark: select it, add/remove it (modifier key), or clear it. */
export function pickedParams(params: URLSearchParams, pick: { chartId: string; field: string; grain: string | null; value: string; additive: boolean }): URLSearchParams {
  const cross = readCross(params);
  const sameSource = cross?.source === pick.chartId && cross.field === pick.field;
  let values: string[];
  if (pick.additive && sameSource) {
    values = cross.values.includes(pick.value) ? cross.values.filter((v) => v !== pick.value) : [...cross.values, pick.value];
  } else {
    values = sameSource && cross.values.length === 1 && cross.values[0] === pick.value ? [] : [pick.value];
  }
  const next = new URLSearchParams(params);
  CROSS_KEYS.forEach((k) => next.delete(k));
  if (values.length) {
    next.set("xf", pick.field);
    values.forEach((v) => next.append("xv", v));
    if (pick.grain) next.set("xg", pick.grain);
    next.set("xc", pick.chartId);
  }
  return next;
}

export function withoutCross(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  CROSS_KEYS.forEach((k) => next.delete(k));
  return next;
}

function crossValueLabel(value: string, grain: string | null): string {
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : null;
  if (!d || Number.isNaN(d.getTime())) return value;
  if (grain === "year") return String(d.getFullYear());
  if (grain === "quarter") return `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}`;
  if (grain === "month") return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
  if (grain === "week") return `Week of ${d.toLocaleDateString()}`;
  return d.toLocaleDateString();
}

/** What a click in a tile selected, with a way to clear it. */
export function CrossFilterChip({ cross, onClear }: Readonly<{ cross: CrossFilter; onClear: () => void }>) {
  const shown = cross.values.slice(0, 3).map((v) => crossValueLabel(v, cross.grain)).join(", ");
  const more = cross.values.length > 3 ? ` +${cross.values.length - 3}` : "";
  return (
    <span className="cross-chip">
      <output aria-live="polite"><span className="muted">{cross.field}:</span> <strong>{shown}{more}</strong></output>
      <button type="button" className="btn btn-ghost btn-icon btn-sm" onClick={onClear} aria-label={`Clear the ${cross.field} selection`} title="Clear (Esc)"><X size={13} /></button>
    </span>
  );
}

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
  const hasDefaults = filters.some((f) => f.default);
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
          <X size={14} /> {hasDefaults ? "Reset" : "Clear"}
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
  const mode = dateMode(params, index, filter);
  const { opts } = useOptions(dashboardId, index, mode === "custom");
  const from = params.get(`ff${index}`) ?? "";
  const to = params.get(`ft${index}`) ?? "";
  // Every change says what was chosen ("fr"), so the dashboard's default period stays away.
  const choose = (period: string) => update((p) => {
    p.set(`fr${index}`, period);
    if (period !== "custom") { p.delete(`ff${index}`); p.delete(`ft${index}`); }
  });
  const setDate = (k: string, v: string) => update((p) => { p.set(`fr${index}`, "custom"); if (v) p.set(k, v); else p.delete(k); });
  const bounds = { min: opts?.min ?? undefined, max: opts?.max ?? undefined };
  return (
    <div className={`filter-ctl filter-dates ${mode !== "all" ? "is-active" : ""}`}>
      <span className="muted small">{filter.label}</span>
      <select className="input input-sm" style={{ width: "auto" }} value={mode} onChange={(e) => choose(e.target.value)} aria-label={`${filter.label} period`}>
        <option value="all">All time</option>
        {DATE_PRESETS.map(([k, label]) => <option key={k} value={k}>{label}{filter.default === k ? " (default)" : ""}</option>)}
        <option value="custom">Custom range…</option>
      </select>
      {mode === "custom" && (
        <>
          <input type="date" className="input input-sm" value={from} {...bounds} onChange={(e) => setDate(`ff${index}`, e.target.value)} aria-label={`${filter.label} from`} />
          <span className="muted small">–</span>
          <input type="date" className="input input-sm" value={to} {...bounds} onChange={(e) => setDate(`ft${index}`, e.target.value)} aria-label={`${filter.label} to`} />
        </>
      )}
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
          {f.kind === "date_range" && (
            <select className="input input-sm" style={{ width: "auto" }} value={f.default ?? ""} aria-label={`Default period for ${f.label}`} title="The period the dashboard opens with"
              onChange={(e) => onChange(filters.map((x, j) => (j === i ? { ...x, default: e.target.value || null } : x)))}>
              <option value="">Opens on: all time</option>
              {DATE_PRESETS.map(([k, label]) => <option key={k} value={k}>Opens on: {label.toLowerCase()}</option>)}
            </select>
          )}
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
