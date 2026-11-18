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
| File parsing | Size limits, zip-bomb checks (uncompressed size and ratio), `defusedxml` for XLSX, values-only reads (formulas are never evaluated, macros ignored), row/column/cell caps. SQLite uploads are opened in memory only, read-only (`query_only`, `trusted_schema` off), behind an authorizer that allows reads of ordinary tables and nothing reached through a view or trigger, with a time limit per read; Parquet is read by pyarrow in batches |
| Links | Server-side downloads for link imports are https-only and checked against server-side request forgery on every hop (see [Links](#links)) |
| Exports | Formula-injection neutralisation in CSV and XLSX |
| Browser | Strict Content-Security-Policy (no inline scripts), `X-Frame-Options: DENY` except embeds, `nosniff`, restrictive Permissions-Policy |
| Container | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges` |
| Audit | Append-only, SHA-256 hash-chained events with integrity verification |
| Logging | Structured JSON; share tokens and API keys are redacted |
| Licensing | Offline Ed25519 verification — no telemetry, no phone-home |

## Links

Importing or refreshing a dataset from a link makes the Prism server download that link, so the request comes from inside your network. To stop a link (or a redirect) being used to reach internal services, the cloud metadata endpoint or other containers, every hop is checked before Prism connects:

- `https://` only; no `user:password@` in the address; at most 5 redirects, each checked again.
- Every address the host name resolves to must be public. Loopback, link-local (including `169.254.169.254` and AWS's `fd00:ec2::254`), multicast, unspecified, documentation and reserved addresses are always refused, including when they are wrapped in IPv6 (IPv4-mapped, 6to4, NAT64). Private networks (10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7) are refused unless `PRISM_LINK_ALLOW_PRIVATE=true`.
- Prism connects to the address it checked (no second DNS lookup that a short-lived answer could change), with TLS certificates verified for the host name.
- Responses must be uncompressed and within the upload size limit; one time limit (`PRISM_LINK_TIMEOUT_S`, default 60 s) covers the whole download, redirects included.
- The file type is decided from the content, never from the server's headers, and the file then goes through the same hardened parsers as an upload.

Downloads made by refreshes are not kept on disk (the version records the file's SHA-256). Links are visible only to authors and above. Turn the feature off entirely with `PRISM_LINK_IMPORTS=false`.

## Data handling

All data stays on your server: metadata in SQLite/PostgreSQL, datasets as Parquet files in the data volume, original uploads under `uploads/`. Deleting a dataset removes its Parquet files. Backups contain everything needed to restore and should be stored encrypted.

## Reporting a vulnerability

Email the security contact listed on the vendor's website with a description and reproduction steps. Please do not open public issues for vulnerabilities. We aim to acknowledge reports within 2 business days.
