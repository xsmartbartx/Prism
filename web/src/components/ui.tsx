import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, X } from "lucide-react";
import type { PrismType } from "../api";

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id="pg" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#6d5efc" />
          <stop offset="1" stopColor="#22b8cf" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="#11131a" />
      <path d="M32 12 52 48H12Z" fill="none" stroke="url(#pg)" strokeWidth="5" strokeLinejoin="round" />
      <path d="M38 34h14M40 39h12M42 44h10" stroke="#f28e2b" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="row muted" role="status">
      <div className="spinner" />
      {label && <span>{label}</span>}
    </div>
  );
}

export function PageLoading() {
  return (
    <div className="stack">
      <div className="skeleton" style={{ height: 28, width: 240 }} />
      <div className="skeleton" style={{ height: 120 }} />
      <div className="skeleton" style={{ height: 240 }} />
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="alert alert-danger" role="alert">
      <div>{error}</div>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="icon">{icon}</div>
      <h3>{title}</h3>
      {children && <div style={{ maxWidth: 440 }}>{children}</div>}
      {action}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const root = ref.current;
    const target =
      root?.querySelector<HTMLElement>(".modal-body input:not([readonly]), .modal-body select, .modal-body textarea") ??
      root?.querySelector<HTMLElement>(".modal-foot .btn-primary, .modal-body button") ??
      root?.querySelector<HTMLElement>("button");
    target?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref} style={wide ? { maxWidth: 820 } : undefined}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn btn-ghost btn-icon btn-sm" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ title, message, confirmLabel = "Delete", onConfirm, onClose, danger = true }: { title: string; message: ReactNode; confirmLabel?: string; onConfirm: () => Promise<void> | void; onClose: () => void; danger?: boolean }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button
            className={danger ? "btn btn-danger" : "btn btn-primary"}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                onClose();
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      <div>{message}</div>
    </Modal>
  );
}

export function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-field">
      <input className="input" readOnly value={value} onFocus={(e) => e.currentTarget.select()} />
      <button
        className="btn btn-icon"
        aria-label="Copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard blocked: the field is selectable */
          }
        }}
      >
        {copied ? <Check size={16} /> : <Copy size={16} />}
      </button>
    </div>
  );
}

const TYPE_LABEL: Record<PrismType, string> = { string: "Abc", integer: "123", float: "1.2", date: "Cal", boolean: "T/F" };

export function TypeDot({ type }: { type: PrismType }) {
  return (
    <span className={`type-dot t-${type}`} title={type}>
      {TYPE_LABEL[type] ?? "?"}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls = status === "certified" ? "badge-success" : status === "deprecated" ? "badge-danger" : "";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function ChartSvg({ svg, minHeight }: { svg: string | null; minHeight?: number }) {
  if (!svg) return <div className="skeleton" style={{ height: minHeight ?? 260 }} />;
  // SVG is produced by Prism's server-side renderer, which escapes all text.
  return <div className="chart-svg" dangerouslySetInnerHTML={{ __html: svg }} />;
}

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  return new Intl.NumberFormat().format(n);
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function fmtDate(s: string | null | undefined, withTime = false): string {
  if (!s) return "–";
  const d = new Date(s);
  return withTime ? d.toLocaleString() : d.toLocaleDateString();
}

export function timeAgo(s: string | null | undefined): string {
  if (!s) return "never";
  const sec = (Date.now() - new Date(s).getTime()) / 1000;
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  if (sec < 86400 * 30) return `${Math.floor(sec / 86400)} d ago`;
  return new Date(s).toLocaleDateString();
}

export function DataTable({ columns, rows, types, max = 500 }: { columns: string[]; rows: Record<string, unknown>[]; types?: Record<string, string>; max?: number }) {
  const numeric = (c: string) => types?.[c] === "integer" || types?.[c] === "float" || (!types && rows.some((r) => typeof r[c] === "number"));
  return (
    <div className="table-wrap" style={{ maxHeight: 520 }}>
      <table className="table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} className={numeric(c) ? "num" : ""}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, max).map((r, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const v = r[c];
                if (v === null || v === undefined) return <td key={c} className="null">null</td>;
                const text = typeof v === "number" ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 }).format(v) : String(v);
                return <td key={c} className={numeric(c) ? "num" : ""}>{text}</td>;
              })}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={Math.max(columns.length, 1)} className="muted" style={{ textAlign: "center", padding: 24 }}>No rows</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
