import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Database, Eye, Table2 } from "lucide-react";
import { post, type DatabaseTable, type ImportRec } from "../api";
import { Modal, fmtNum } from "./ui";

const SSL_LABELS: Record<string, string> = {
  require: "Encrypted (require)",
  "verify-full": "Encrypted, certificate checked (verify-full)",
  disable: "Not encrypted (private networks only)",
};

/** Connect to PostgreSQL, pick a table or view, and start an import from it. */
export function DatabaseImport({ onClose }: Readonly<{ onClose: () => void }>) {
  const nav = useNavigate();
  const [form, setForm] = useState({ host: "", port: "5432", database: "", user: "", password: "", sslmode: "require" });
  const [tables, setTables] = useState<DatabaseTable[] | null>(null);
  const [table, setTable] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const conn = () => ({ ...form, port: Number(form.port) || null });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    setTables(null); // new details: list the tables again
  };

  const listTables = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ tables: DatabaseTable[] }>("/api/v1/imports/database/tables", conn());
      setTables(r.tables);
      setTable(r.tables[0]?.name ?? "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const importTable = async () => {
    setBusy(true);
    setError(null);
    try {
      const imp = await post<ImportRec>("/api/v1/imports/database", { ...conn(), table });
      nav(`/imports/${imp.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal title="Connect a PostgreSQL database" onClose={onClose} wide
      footer={tables && tables.length > 0 && (
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={importTable} disabled={busy || !table}><Database size={16} /> {busy ? "Reading…" : "Import table"}</button>
        </>
      )}>
      <form className="stack" style={{ gap: 12 }} onSubmit={listTables}>
        <p className="muted small" style={{ margin: 0 }}>
          Prism reads one table or view into a dataset, in a read-only session, and can refresh it from the database later.
          Use an account that can only read: the password is stored encrypted on this server.
        </p>
        <div className="grid-db">
          <label className="field"><span>Host</span><input className="input" value={form.host} onChange={set("host")} placeholder="db.example.com" required autoComplete="off" /></label>
          <label className="field"><span>Port</span><input className="input" value={form.port} onChange={set("port")} inputMode="numeric" /></label>
          <label className="field"><span>Database</span><input className="input" value={form.database} onChange={set("database")} required autoComplete="off" /></label>
          <label className="field"><span>User</span><input className="input" value={form.user} onChange={set("user")} required autoComplete="off" /></label>
          <label className="field"><span>Password</span><input className="input" type="password" value={form.password} onChange={set("password")} autoComplete="new-password" /></label>
          <label className="field"><span>Connection</span>
            <select className="input" value={form.sslmode} onChange={set("sslmode")}>
              {Object.entries(SSL_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        </div>
        {error && <p className="small" role="alert" style={{ color: "var(--danger)", margin: 0 }}>{error}</p>}
        <div className="row">
          <button type="submit" className="btn" disabled={busy || !form.host || !form.database || !form.user}><Eye size={16} /> {busy && !tables ? "Connecting…" : "Show tables"}</button>
        </div>
      </form>

      {tables && (
        tables.length === 0 ? (
          <p className="muted" style={{ marginTop: 16 }}>Connected, but this account cannot read any tables.</p>
        ) : (
          <fieldset className="db-tables" style={{ marginTop: 16 }}>
            <legend className="small muted">Choose a table or view ({tables.length})</legend>
            {tables.map((t) => (
              <label key={t.name} className="filter-opt">
                <input type="radio" name="db-table" value={t.name} checked={table === t.name} onChange={() => setTable(t.name)} />
                <Table2 size={14} aria-hidden /> <span className="truncate grow">{t.name}</span>
                <span className="muted small">{t.kind}{t.rows != null && t.rows >= 0 ? ` · ~${fmtNum(t.rows)} rows` : ""}</span>
              </label>
            ))}
          </fieldset>
        )
      )}
    </Modal>
  );
}
