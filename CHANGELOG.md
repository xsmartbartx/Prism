# Changelog

## 1.0.1 — 2026-11-04

- Hosting on the NEXORA platform: `deploy/nexora/compose.yml` (compose project `prism`, PostgreSQL 16, published image, no host ports; served by the shared edge Caddy).
- `prism create-admin --random-password` and `prism reset-link --email …` hand an account over with a single-use link, so no password is ever chosen for someone or sent.
- Security hardening from the SonarCloud review: hash-locked, wheel-only dependency installs; actions pinned to commit SHAs; npm without lifecycle scripts; vendor license tool confined to its working directory.

## 1.0.0 — 2026-11-04

First commercial release.

### Product
- Web application: first-run setup, sign-in, workspaces, light/dark themes, responsive layout.
- Import of Excel (`.xlsx`, `.xlsm`) and delimited text with header-row, locale and type detection; human review of ambiguous columns; quarantine with tolerance gate.
- Versioned datasets stored as Parquet; refresh with header-name matching and drift detection; profiling; certification.
- Chart builder with live server-side rendering: bar (vertical/horizontal, grouped/stacked), line, area, donut, scatter, KPI, table; time buckets, filters, sort, number/currency formats; recommendations.
- Dashboards; public share links and embeds with expiry, revocation and view counts.
- CSV/XLSX/SVG export with formula-injection protection.
- Members, roles (viewer, explorer, author, steward, admin, auditor), invite and reset links without SMTP, personal API keys.
- Tamper-evident audit log with integrity verification.
- Offline license keys with Community, Pro and Business plans.

### Platform
- REST API with OpenAPI docs; DuckDB query engine with sandboxed, parameterised execution.
- SQLite or PostgreSQL metadata store with Alembic migrations.
- Docker image (non-root, read-only), Compose deployment with automatic HTTPS (Caddy), daily backups, DB-agnostic backup/restore.
- CI for lint, types, tests (SQLite and PostgreSQL), UI build and container smoke test; tagged releases publish multi-arch images.
