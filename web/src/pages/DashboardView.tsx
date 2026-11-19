import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowDown, ArrowUp, Check, Pencil, Plus, Share2, Trash2, X } from "lucide-react";
import { can, del, get, getText, put, type Chart, type Dashboard, type DashboardFilter, type Tile, type TileRender } from "../api";
import { effectiveTheme, useApp, useLoad } from "../app-state";
import { CrossFilterChip, FilterBar, FilterEditor, filterQuery, pickedParams, readCross, withoutCross } from "../components/DashboardFilters";
import ShareDialog from "../components/ShareDialog";
import { ChartSvg, Confirm, Empty, ErrorBox, Modal, PageLoading } from "../components/ui";

/**
 * One tile. A saved tile renders through the dashboard, so the viewer's filters narrow it;
 * a tile just added in the editor (not saved yet) renders on its own.
 */
interface Pick { field: string; grain: string | null; value: string; additive: boolean }

function TileChart({ dashboardId, id, theme, query, live, highlight, onPick }: {
  dashboardId: string; id: string; theme: string; query: string; live: boolean;
  /** Values selected by clicking this tile: shown highlighted, the rest dimmed. */
  highlight?: string[];
  onPick?: (pick: Pick) => void;
}) {
  const [svg, setSvg] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Selections can change faster than tiles render: only the latest request may update the tile.
    // The previous chart stays up (dimmed) until the new one arrives, so clicks don't flash.
    let current = true;
    setErr(null);
    if (live) {
      get<TileRender>(`/api/v1/dashboards/${dashboardId}/charts/${id}/render?theme=${theme}${query}`)
        .then((r) => { if (current) { setSvg(r.svg); setSkipped(r.skipped); } })
        .catch((e) => { if (current) setErr(e.message); });
    } else {
      setSkipped([]);
      getText(`/api/v1/charts/${id}/render?theme=${theme}`)
        .then((svg) => { if (current) setSvg(svg); })
        .catch((e) => { if (current) setErr(e.message); });
    }
    return () => { current = false; };
  }, [dashboardId, id, theme, query, live]);

  useEffect(() => {
    const el = box.current?.querySelector(".chart-svg");
    if (!el) return;
    const picking = !!highlight?.length;
    el.classList.toggle("picking", picking);
    el.querySelectorAll(".pick").forEach((m) => m.classList.toggle("picked", picking && !!highlight?.includes(m.getAttribute("data-pick") ?? "")));
  }, [svg, highlight]);

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    const mark = (e.target as Element).closest?.(".pick");
    const root = box.current?.querySelector("svg[data-pick-field]");
    const value = mark?.getAttribute("data-pick");
    const field = root?.getAttribute("data-pick-field");
    if (!onPick || !value || !field) return;
    onPick({ field, grain: root?.getAttribute("data-pick-grain") ?? null, value, additive: e.shiftKey || e.metaKey || e.ctrlKey });
  };

  if (err) return <div className="muted small">{err}</div>;
  return (
    <>
      {skipped.length > 0 && <p className="tile-note">Not filtered by {skipped.join(", ")}: this chart's data has no such field.</p>}
      {/* Clicking a mark is a shortcut; the dashboard filters remain the keyboard path. */}
      <div ref={box} className={onPick ? "pickable" : undefined} onClick={onClick}>
        <ChartSvg svg={svg} minHeight={220} />
      </div>
    </>
  );
}

export default function DashboardView() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const { me, toast, theme } = useApp();
  const { data, error, reload, setData } = useLoad<Dashboard>(`/api/v1/dashboards/${id}`);
  const [edit, setEdit] = useState(params.get("edit") === "1");
  const [layout, setLayout] = useState<Tile[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [filters, setFilters] = useState<DashboardFilter[]>([]);
  const [adding, setAdding] = useState(false);
  const [share, setShare] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [charts, setCharts] = useState<Record<string, Chart>>({});
  const editable = can.explore(me?.role);
  const t = effectiveTheme(theme);
  const fq = filterQuery(params);
  const cross = edit ? null : readCross(params);
  // The tile that was clicked keeps all its marks (highlighting the choice), so its own query
  // leaves the cross-filter out and it does not reload on every click.
  const sourceQuery = filterQuery(withoutCross(params));

  useEffect(() => {
    if (!cross) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setParams(withoutCross(params)); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cross, params, setParams]);

  useEffect(() => {
    if (!data) return;
    setLayout([...data.layout].sort((a, b) => a.y - b.y || a.x - b.x));
    setName(data.name);
    setDescription(data.description);
    setFilters(data.filters ?? []);
    setCharts(data.charts ?? {});
  }, [data]);

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <PageLoading />;

  const save = async () => {
    // Flow layout: assign y in order; widths are user-chosen.
    let x = 0, y = 0;
    const flowed = layout.map((tile) => {
      if (x + tile.w > 12) { x = 0; y += 1; }
      const out = { ...tile, x, y };
      x += tile.w;
      return out;
    });
    try {
      const saved = await put<Dashboard>(`/api/v1/dashboards/${id}`, { name, description, layout: flowed, filters: filters.map((f) => ({ ...f, label: f.label.trim() || f.field })) });
      setData({ ...saved, charts });
      setEdit(false);
      setParams({});
      toast("Dashboard saved");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= layout.length) return;
    const copy = [...layout];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    setLayout(copy);
  };

  return (
    <>
      <div className="page-head">
        <div className="grow">
          {edit ? (
            <div className="stack" style={{ gap: 6, maxWidth: 560 }}>
              <input className="input" style={{ fontSize: 20, fontWeight: 650, height: 40 }} value={name} onChange={(e) => setName(e.target.value)} aria-label="Dashboard name" />
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description (optional)" aria-label="Description" />
            </div>
          ) : (
            <>
              <h1>{data.name}</h1>
              {data.description && <p>{data.description}</p>}
            </>
          )}
        </div>
        <div className="row">
          {edit ? (
            <>
              <button className="btn" onClick={() => setAdding(true)}><Plus size={16} /> Add chart</button>
              <button className="btn" onClick={() => { setEdit(false); setParams({}); void reload(); }}><X size={16} /> Cancel</button>
              <button className="btn btn-primary" onClick={save}><Check size={16} /> Save</button>
            </>
          ) : (
            editable && (
              <>
                <button className="btn" onClick={() => setShare(true)}><Share2 size={16} /> Share</button>
                <button className="btn" onClick={() => setEdit(true)}><Pencil size={16} /> Edit</button>
                <button className="btn btn-ghost btn-icon" aria-label="Delete dashboard" onClick={() => setConfirmDelete(true)}><Trash2 size={16} /></button>
              </>
            )
          )}
        </div>
      </div>

      {edit ? (
        <div style={{ marginBottom: 16 }}>
          <FilterEditor chartIds={layout.map((x) => x.chart_id)} filters={filters} onChange={setFilters} />
        </div>
      ) : (
        layout.length > 0 && (data.filters.length > 0 || cross) && (
          <div className="filter-row">
            {data.filters.length > 0 && <FilterBar dashboardId={data.id} filters={data.filters} params={params} setParams={setParams} />}
            {cross && <CrossFilterChip cross={cross} onClear={() => setParams(withoutCross(params))} />}
          </div>
        )
      )}

      {layout.length === 0 ? (
        <div className="card">
          <Empty icon={<Plus size={22} />} title="This dashboard is empty" action={editable && <button className="btn btn-primary" onClick={() => { setEdit(true); setAdding(true); }}><Plus size={16} /> Add a chart</button>}>
            Add saved charts and choose how wide each one is.
          </Empty>
        </div>
      ) : (
        <div className="dash-grid">
          {layout.map((tile, i) => {
            const c = charts[tile.chart_id];
            return (
              <div key={tile.chart_id + i} className="card dash-tile" style={{ gridColumn: `span ${tile.w}` }}>
                <div className="card-head">
                  <h3 className="truncate">{c ? <Link to={`/charts/${c.id}`} style={{ color: "inherit" }}>{c.name}</Link> : "Chart"}</h3>
                  {edit && (
                    <div className="row" style={{ flexWrap: "nowrap", gap: 4 }}>
                      <select className="input input-sm" style={{ width: 90 }} value={tile.w} onChange={(e) => setLayout(layout.map((x, j) => (j === i ? { ...x, w: Number(e.target.value) } : x)))} aria-label="Width">
                        {[3, 4, 6, 8, 12].map((w) => <option key={w} value={w}>{w === 12 ? "Full" : `${w}/12`}</option>)}
                      </select>
                      <button className="btn btn-ghost btn-icon btn-sm" aria-label="Move up" onClick={() => move(i, -1)}><ArrowUp size={14} /></button>
                      <button className="btn btn-ghost btn-icon btn-sm" aria-label="Move down" onClick={() => move(i, 1)}><ArrowDown size={14} /></button>
                      <button className="btn btn-ghost btn-icon btn-sm" aria-label="Remove" onClick={() => setLayout(layout.filter((_, j) => j !== i))}><X size={14} /></button>
                    </div>
                  )}
                </div>
                <div className="tile-body">
                  <TileChart dashboardId={data.id} id={tile.chart_id} theme={t}
                    query={edit ? "" : cross?.source === tile.chart_id ? sourceQuery : fq}
                    live={!edit && data.layout.some((x) => x.chart_id === tile.chart_id)}
                    highlight={cross?.source === tile.chart_id ? cross.values : undefined}
                    onPick={edit ? undefined : (pick) => setParams(pickedParams(params, { chartId: tile.chart_id, ...pick }))} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {adding && (
        <AddChart
          existing={layout.map((x) => x.chart_id)}
          onClose={() => setAdding(false)}
          onAdd={(c) => {
            setCharts((m) => ({ ...m, [c.id]: c }));
            setLayout((l) => [...l, { chart_id: c.id, x: 0, y: 0, w: c.view.mark === "kpi" ? 3 : 6, h: 4 }]);
          }}
        />
      )}
      {share && <ShareDialog type="dashboard" id={data.id} name={data.name} onClose={() => setShare(false)} />}
      {confirmDelete && (
        <Confirm
          title="Delete dashboard?"
          message={<>Delete <strong>{data.name}</strong>? The charts themselves are kept. Shared links stop working.</>}
          onClose={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await del(`/api/v1/dashboards/${id}`);
            toast("Dashboard deleted");
            nav("/dashboards");
          }}
        />
      )}
    </>
  );
}

function AddChart({ existing, onAdd, onClose }: { existing: string[]; onAdd: (c: Chart) => void; onClose: () => void }) {
  const [charts, setCharts] = useState<Chart[] | null>(null);
  useEffect(() => {
    get<Chart[]>("/api/v1/charts").then(setCharts).catch(() => setCharts([]));
  }, []);
  return (
    <Modal title="Add a chart" onClose={onClose}>
      {!charts ? (
        <PageLoading />
      ) : charts.length === 0 ? (
        <p className="muted">No saved charts yet. <Link to="/charts/new">Build one</Link> first.</p>
      ) : (
        <div className="stack" style={{ gap: 6 }}>
          {charts.map((c) => (
            <button key={c.id} className="btn" style={{ justifyContent: "space-between" }} onClick={() => { onAdd(c); onClose(); }} disabled={existing.includes(c.id)}>
              <span className="truncate">{c.name}</span>
              <span className="muted small">{existing.includes(c.id) ? "added" : c.view.mark}</span>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}
