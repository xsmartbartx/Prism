import { useRef, useState } from "react";
import { UploadCloud } from "lucide-react";
import { Spinner } from "./ui";

export default function Dropzone({ onFile, busy, compact }: { onFile: (f: File) => void; busy?: boolean; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={`dropzone ${over ? "over" : ""}`}
      style={compact ? { padding: 18 } : undefined}
      role="button"
      tabIndex={0}
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f && !busy) onFile(f);
      }}
    >
      <input
        ref={input}
        type="file"
        hidden
        accept=".csv,.tsv,.txt,.xlsx,.xlsm,.sqlite,.sqlite3,.db,.parquet"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      {busy ? (
        <div className="row" style={{ justifyContent: "center" }}><Spinner label="Uploading and analysing…" /></div>
      ) : (
        <div className="stack" style={{ alignItems: "center", gap: 6 }}>
          <UploadCloud size={compact ? 22 : 30} color="var(--accent)" />
          <strong>Drop a spreadsheet or database file here, or click to browse</strong>
          <span className="muted small">Excel (.xlsx, .xlsm), delimited text (.csv, .tsv), SQLite (.sqlite, .db) or Parquet. Prism detects headers, types and locale — you confirm.</span>
        </div>
      )}
    </div>
  );
}
