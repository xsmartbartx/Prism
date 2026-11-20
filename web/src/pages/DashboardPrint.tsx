import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { get, type Dashboard, type TileRender } from "../api";
import { useLoad } from "../app-state";
import { FILTER_PARAM, readCross, withoutCross } from "../components/DashboardFilters";
import { ErrorBox, PageLoading } from "../components/ui";

const PAGE_WIDTH = 1000; // CSS px across the printable area; tiles are sized from it

/** What the URL's filters select, in words, for the page header. */
function filterSummary(d: Dashboard, params: URLSearchParams): string[] {
  const out: string[] = [];
  d.filters.forEach((f, i) => {
    if (f.kind === "values") {
      const values = params.getAll(`fv${i}`);
      if (values.length) out.push(`${f.label}: ${values.join(", ")}`);
    } else {
      const from = params.get(`ff${i}`), to = params.get(`ft${i}`);
      if (from || to) out.push(`${f.label}: ${from ?? "…"} to ${to ?? "…"}`);
    }
  });
  const cross = readCross(params);
  if (cross) out.push(`${cross.field}: ${cross.values.join(", ")} (selected in a chart)`);
  return out;
}

function PrintTile({ dashboardId, chartId, width, query, onDone }: Readonly<{
  dashboardId: string; chartId: string; width: number; query: string; onDone: () => void;
}>) {
  const [tile, setTile] = useState<TileRender | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    get<TileRender>(`/api/v1/dashboards/${dashboardId}/charts/${chartId}/render?theme=light&width=${width}${query}`)
      .then(setTile)
      .catch((e) => setError((e as Error).message))
      .finally(onDone);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, chartId, width, query]);
  if (error) return <p className="muted small">{error}</p>;
  if (!tile) return <div className="skeleton" style={{ height: 200 }} />;
  return (
    <>
      {tile.skipped.length > 0 && <p className="tile-note">Not filtered by {tile.skipped.join(", ")}.</p>}
      {/* SVG from Prism's own renderer, which escapes all text. */}
      <div className="chart-svg" dangerouslySetInnerHTML={{ __html: tile.svg }} />
    </>
  );
}

/** A dashboard laid out for paper: light charts, the filters in words, then the browser's print dialog. */
export default function DashboardPrint() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const { data, error } = useLoad<Dashboard>(`/api/v1/dashboards/${id}`);
  const [done, setDone] = useState(0);
  const [printed, setPrinted] = useState(false);
  const generated = useMemo(() => new Date().toLocaleString(), []);
  const cross = readCross(params);

  const query = (chartId: string): string => {
    const p = cross?.source === chartId ? withoutCross(params) : params;
    const out = new URLSearchParams();
    p.forEach((v, k) => { if (FILTER_PARAM.test(k)) out.append(k, v); });
    const s = out.toString();
    return s ? `&${s}` : "";
  };

  const tiles = data ? [...data.layout].sort((a, b) => a.y - b.y || a.x - b.x) : [];
  // "?preview" shows the page without opening the print dialog.
  const autoPrint = !params.has("preview");
  useEffect(() => {
    if (!autoPrint || !data || printed || done < tiles.length) return;
    setPrinted(true);
    document.title = data.name;
    // Let the charts paint before the dialog opens.
    const t = setTimeout(() => window.print(), 300);
    return () => clearTimeout(t);
  }, [autoPrint, data, done, tiles.length, printed]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <PageLoading />;
  const summary = filterSummary(data, params);
  return (
    <div className="print-page" style={{ maxWidth: PAGE_WIDTH }}>
      <div className="print-toolbar no-print">
        <span className="muted small">{done < tiles.length ? `Preparing ${done}/${tiles.length} charts…` : "Ready"}</span>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => window.print()} disabled={done < tiles.length}><Printer size={14} /> Print or save as PDF</button>
      </div>
      <header className="print-head">
        <h1>{data.name}</h1>
        {data.description && <p>{data.description}</p>}
        <p className="small muted">Generated {generated}{summary.length ? "" : " · no filters"}</p>
        {summary.length > 0 && <ul className="print-filters">{summary.map((s) => <li key={s}>{s}</li>)}</ul>}
      </header>
      <div className="print-grid">
        {tiles.map((t) => {
          const chart = data.charts?.[t.chart_id];
          return (
            <section key={t.chart_id} className="print-tile" style={{ gridColumn: `span ${t.w}` }}>
              <h2>{chart?.name ?? "Chart"}</h2>
              <PrintTile dashboardId={data.id} chartId={t.chart_id} width={Math.round((t.w / 12) * PAGE_WIDTH) - 24}
                query={query(t.chart_id)} onDone={() => setDone((n) => n + 1)} />
            </section>
          );
        })}
      </div>
      <footer className="small muted print-foot">Prism · {data.name}</footer>
    </div>
  );
}
