# Security

## Model

| Area | Control |
|---|---|
| Transport | HTTPS via Caddy (automatic certificates); HSTS when the base URL is https |
| Passwords | scrypt (N=2^14, r=8, p=1) with per-user salt; minimum 10 characters |
| Sessions | 256-bit random tokens in `HttpOnly`, `SameSite=Lax`, `Secure` (on https) cookies; only SHA-256 hashes are stored; password change/reset revokes other sessions |
| CSRF | Cookie-authenticated writes require the `X-Prism-CSRF` header (not settable cross-site without CORS, which is disabled) |
| Brute force | Failed sign-ins limited per IP and per account (10 per 15 minutes); failures are audited |
| Authorization | Role checks in the service layer for every operation; workspaces isolate all artifacts |
| API keys | Shown once, stored hashed, revocable, scoped to one workspace |
| Share links | Random tokens stored hashed; read-only server-rendered pages with no JavaScript; expiry, revocation, view counting; embedding opt-in |
| Queries | No raw SQL surface. Specs are validated against the column contract and compiled to parameterised SQL with quoted identifiers; DuckDB runs per query with external file/network access disabled and configuration locked; hard timeout |
| File parsing | Size limits, zip-bomb checks (uncompressed size and ratio), `defusedxml` for XLSX, values-only reads (formulas are never evaluated, macros ignored), row/column/cell caps |
| Exports | Formula-injection neutralisation in CSV and XLSX |
| Browser | Strict Content-Security-Policy (no inline scripts), `X-Frame-Options: DENY` except embeds, `nosniff`, restrictive Permissions-Policy |
| Container | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges` |
| Audit | Append-only, SHA-256 hash-chained events with integrity verification |
| Logging | Structured JSON; share tokens and API keys are redacted |
| Licensing | Offline Ed25519 verification — no telemetry, no phone-home |

## Data handling

All data stays on your server: metadata in SQLite/PostgreSQL, datasets as Parquet files in the data volume, original uploads under `uploads/`. Deleting a dataset removes its Parquet files. Backups contain everything needed to restore and should be stored encrypted.

## Reporting a vulnerability

Email the security contact listed on the vendor's website with a description and reproduction steps. Please do not open public issues for vulnerabilities. We aim to acknowledge reports within 2 business days.
