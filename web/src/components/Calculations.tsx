import { Fragment, useEffect, useState } from "react";
import { Calculator, Pencil, Plus, Trash2 } from "lucide-react";
import { post, put, type Calculation, type ColumnContract } from "../api";
import { useApp } from "../app-state";
import { Modal, TypeDot } from "./ui";

interface Preview { type: string; aggregate?: boolean; columns: string[]; rows: { inputs: Record<string, unknown>; value: unknown }[] }

const FUNCTIONS: [string, string][] = [
  ["[Revenue] - [Cost]", "arithmetic: + - * / % (division by zero gives an empty value)"],
  ["SUM · AVG · MIN · MAX · MEDIAN · COUNT · COUNTD", "aggregates: e.g. (SUM([Revenue]) - SUM([Cost])) / SUM([Revenue]) is the true margin of each group a chart shows"],
  ["ROUND(x, 1) · ABS(x) · FLOOR(x) · CEIL(x)", "numbers"],
  ["IF(condition, then, else)", "e.g. IF([Units] >= 10, 'Bulk', 'Single')"],
  ["COALESCE(x, 0) · ISEMPTY(x)", "empty values"],
  ["YEAR · QUARTER · MONTH · DAY · WEEKDAY(date)", "parts of a date"],
  ["DAYS_BETWEEN(a, b) · [Date] + 7", "date arithmetic"],
  ["UPPER · LOWER · TRIM · LEN · LEFT(s, n) · RIGHT(s, n)", "text"],
  ["CONTAINS(s, 'x') · CONCAT(a, b) · a & b", "text"],
  ["= <> < <= > >= · AND · OR · NOT", "conditions; dates compare with 'YYYY-MM-DD'"],
];

function show(v: unknown): string {
  if (v === null || v === undefined) return "(empty)";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toLocaleString(undefined, { maximumFractionDigits: 6 });
  return String(v);
}

function Editor({ datasetId, existing, index, columns, onClose, onSaved }: Readonly<{
  datasetId: string; existing: Calculation[]; index: number | null; columns: ColumnContract[];
  onClose: () => void; onSaved: (c: Calculation[]) => void;
}>) {
  const { toast } = useApp();
  const current = index === null ? null : existing[index];
  const [name, setName] = useState(current?.name ?? "");
  const [expression, setExpression] = useState(current?.expression ?? "");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // A field may use the ones before it.
  const before = index === null ? existing : existing.slice(0, index);

  useEffect(() => {
    if (!expression.trim()) { setPreview(null); setError(null); return; }
    let current = true;
    const t = setTimeout(() => {
      post<Preview>(`/api/v1/datasets/${datasetId}/calculations/preview`, { expression, calculations: before.map(({ name, expression }) => ({ name, expression })) })
        .then((p) => { if (current) { setPreview(p); setError(null); } })
        .catch((e) => { if (current) { setPreview(null); setError((e as Error).message); } });
    }, 350);
    return () => { current = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expression, datasetId]);

  const save = async () => {
    const next = [...existing];
    const item = { name: name.trim(), expression: expression.trim() };
    if (index === null) next.push(item as Calculation); else next[index] = item as Calculation;
    setSaving(true);
    try {
      const r = await put<{ calculations: Calculation[] }>(`/api/v1/datasets/${datasetId}/calculations`, { calculations: next.map(({ name, expression }) => ({ name, expression })) });
      toast(index === null ? `Added ${item.name}` : `Saved ${item.name}`);
      onSaved(r.calculations);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const insert = (text: string) => setExpression((x) => (x && !x.endsWith(" ") ? `${x} ${text}` : `${x}${text}`));
  const fields = [...columns.map((c) => c.name), ...before.map((c) => c.name)];

  return (
    <Modal title={index === null ? "New calculated field" : `Edit ${current?.name}`} onClose={onClose} wide
      footer={<>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={saving || !name.trim() || !expression.trim() || !!error}>{saving ? "Saving…" : "Save field"}</button>
      </>}>
      <div className="stack" style={{ gap: 12 }}>
        <label className="field"><span>Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Profit" maxLength={120} /></label>
        <label className="field"><span>Formula</span>
          <textarea className="input mono" rows={3} value={expression} onChange={(e) => setExpression(e.target.value)} placeholder="[Revenue] - [Cost]" maxLength={1000} spellCheck={false} />
        </label>
        <div className="calc-fields" aria-label="Insert a column">
          {fields.map((f) => <button type="button" key={f} className="chip" onClick={() => insert(`[${f.replace(/]/g, "]]")}]`)}>{f}</button>)}
        </div>
        {error && <p className="small" role="alert" style={{ color: "var(--danger)", margin: 0 }}>{error}</p>}
        {preview?.aggregate && (
          <div className="calc-preview">
            <div className="small muted">Aggregate field (a measure): charts calculate it for each group. Over the whole dataset:</div>
            <div style={{ fontSize: 20, fontWeight: 650 }}>{show(preview.rows[0]?.value)} <span className="small muted">{preview.type}</span></div>
          </div>
        )}
        {preview && !preview.aggregate && (
          <div className="calc-preview">
            <div className="small muted">Result: <span className="row" style={{ display: "inline-flex", gap: 4 }}><TypeDot type={preview.type as ColumnContract["type"]} /> {preview.type}</span> · first rows</div>
            <table className="table table-compact">
              <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}<th>{name.trim() || "Result"}</th></tr></thead>
              <tbody>{preview.rows.map((r, i) => <tr key={i}>{preview.columns.map((c) => <td key={c} className="muted">{show(r.inputs[c])}</td>)}<td><strong>{show(r.value)}</strong></td></tr>)}</tbody>
            </table>
          </div>
        )}
        <details className="small">
          <summary>Functions</summary>
          <dl className="kbd-row" style={{ marginTop: 8 }}>
            {FUNCTIONS.map(([f, d]) => <Fragment key={f}><dt className="mono">{f}</dt><dd>{d}</dd></Fragment>)}
          </dl>
        </details>
      </div>
    </Modal>
  );
}

/** The dataset's calculated fields: list, add, edit, remove (authors). */
export function CalculationsCard({ datasetId, calculations, columns, editable, onChange }: Readonly<{
  datasetId: string; calculations: Calculation[]; columns: ColumnContract[]; editable: boolean; onChange: () => void;
}>) {
  const { toast } = useApp();
  const [editing, setEditing] = useState<number | null | undefined>(undefined);
  const remove = async (i: number) => {
    const next = calculations.filter((_, j) => j !== i).map(({ name, expression }) => ({ name, expression }));
    try {
      await put(`/api/v1/datasets/${datasetId}/calculations`, { calculations: next });
      toast(`Removed ${calculations[i].name}`);
      onChange();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  if (!calculations.length && !editable) return null;
  return (
    <div className="card">
      <div className="card-head">
        <h2 className="row" style={{ gap: 8 }}><Calculator size={16} /> Calculated fields</h2>
        {editable && <button type="button" className="btn btn-sm" onClick={() => setEditing(null)}><Plus size={14} /> Add field</button>}
      </div>
      {calculations.length === 0 ? (
        <p className="muted card-pad" style={{ margin: 0 }}>Add a field computed from the columns, such as <code>[Revenue] - [Cost]</code> or <code>YEAR([Order Date])</code>, and use it in charts like any column.</p>
      ) : (
        <div className="table-wrap" style={{ border: 0 }}>
          <table className="table">
            <thead><tr><th>Field</th><th>Type</th><th>Formula</th>{editable && <th />}</tr></thead>
            <tbody>
              {calculations.map((c, i) => (
                <tr key={c.name}>
                  <td><strong>{c.name}</strong></td>
                  <td><span className="row" style={{ flexWrap: "nowrap" }}><TypeDot type={c.type} /> {c.type}{c.aggregate && <span className="badge" title="Aggregate field: use it as a value in charts">measure</span>}</span></td>
                  <td className="mono small truncate" style={{ maxWidth: 420 }} title={c.expression}>{c.expression}</td>
                  {editable && (
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label={`Edit ${c.name}`} onClick={() => setEditing(i)}><Pencil size={14} /></button>
                      <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label={`Remove ${c.name}`} onClick={() => void remove(i)}><Trash2 size={14} /></button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing !== undefined && (
        <Editor datasetId={datasetId} existing={calculations} index={editing} columns={columns}
          onClose={() => setEditing(undefined)} onSaved={() => onChange()} />
      )}
    </div>
  );
}
