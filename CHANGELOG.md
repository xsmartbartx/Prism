# Changelog

## 1.9.0 — 2026-11-24

- Pivot tables: a **Pivot** chart type lays one value out as a grid, with a field down the rows and, optionally, another across the columns (for example revenue by region × channel). Rows and columns get totals when they add up correctly (sums, counts, minimums and maximums) and none for averages, medians or distinct counts, where a total would mislead; **Totals** turns them off. **Heat map** shades each cell by its value. Clicking a row on a dashboard filters the other charts to it. Up to 200 rows and 20 columns are shown, with a note when there are more.
- Chart builder: a sort on a field the chart no longer shows (for example after changing the x axis) is dropped instead of failing the preview.
- Security: web dependency updates clear all open Dependabot alerts. React Router 6.28 → 7.18 fixes open redirects (including via backslash paths in links and navigation) and a constructor injection in error deserialisation; Vite 5.4 → 6.4 (with esbuild 0.25) fixes development-server file-access and cross-origin issues. `npm audit` reports no vulnerabilities. No changes to how Prism works.

## 1.8.0 — 2026-11-23

- Dashboard export: **Print** opens a paper-ready view of the dashboard (name, filters in words, generation time, every chart in light colours) and the browser's print dialog, for printing or saving as PDF; **Excel** downloads a workbook with a sheet per chart, filters and click selections applied, and an *About* sheet summarising the dashboard, time, exporter, filters and any chart they could not apply to. Sheet names are made Excel-safe and unique; formula injection is neutralised; exports are audited.

## 1.7.0 — 2026-11-20

- Aggregate fields: calculated fields can use `SUM`, `AVG`, `MIN`, `MAX`, `MEDIAN`, `COUNT` and `COUNTD`, which makes them measures that charts calculate for each group, e.g. the true margin `(SUM([Revenue]) - SUM([Cost])) / SUM([Revenue])` rather than an average of per-row margins. They appear under **Aggregate fields** in the chart builder's Values (function *formula*, `"value"` in the API), can use row fields and earlier aggregate fields, and preview their value over the whole dataset. Every column must be inside an aggregate, and aggregates do not nest.

## 1.6.0 — 2026-11-19

- Calculated fields: on a dataset's Overview, add columns computed from the others with spreadsheet-like formulas (`[Revenue] - [Cost]`, `IF([Units] >= 10, 'Bulk', 'Single')`, `YEAR([Order Date])`), checked as you type with a preview of the first rows. Charts, dashboard filters and click-to-filter use them like any column. Formulas are parsed and type-checked by Prism's own grammar (bracketed columns, a fixed function list, bound literal values) and never reach SQL as text; division by zero gives an empty value. A field a chart uses cannot be removed. Adds migration `0005`.

## 1.5.0 — 2026-11-19

- PostgreSQL sources: **Datasets → Connect a PostgreSQL database** lists the tables and views an account can read and imports one through the usual review. The dataset can then be refreshed from the database by hand or on a schedule, like a link: unchanged rows (in any order) make no new version, and changes go through the contract and drift checks. Connections follow the link address rules (no internal, loopback or metadata addresses; private networks only when allowed), run in read-only sessions with timeouts, read whole tables only (no user SQL, up to one million rows), and keep the password encrypted on the dataset's source. Adds migration `0004`.

- Image builds compile the web UI once, on the build machine's own platform, instead of once per target platform under emulation. Release builds are faster and no longer hang in the arm64 `npm ci` step; the release job also fails after 30 minutes instead of waiting for GitHub's 6-hour limit.

## 1.4.0 — 2026-11-19

- Click to filter on dashboards: clicking a bar, line point or donut slice filters the other charts on the dashboard to that value (on any field, no filter set up needed). The clicked chart keeps its bars and highlights the choice; a chip shows the selection, and Esc, a second click or × clears it. Shift/Ctrl/⌘-click selects several values; on a time axis grouped by week, month, quarter or year a click selects the whole period. The selection is part of the page address, combines with dashboard filters, and is applied as bound parameters like any filter.
- Charts whose query groups the category axis by time now label it by that grain even when the saved view did not say so (charts made through the API).

## 1.3.0 — 2026-11-18

- Import from a link: paste an `https://` link to a CSV, Excel, Parquet or SQLite file (a published Google Sheet, a raw GitHub file, an export URL) and Prism downloads it into the usual review. The dataset remembers the link: **Refresh now** downloads it again, and a schedule (every hour, day or week; Pro and Business) keeps it current. An unchanged file (`304 Not Modified`, or identical bytes) makes no new version; a changed one goes through the same contract and drift checks as an upload. Failures are shown on the dataset and audited, and a schedule pauses after five in a row or when its owner loses access.
- Downloads are protected against server-side request forgery: https only, every address of every hop (redirects included) must be public, the connection is pinned to the checked address with TLS verified for the host name, plus size and time limits. `PRISM_LINK_ALLOW_PRIVATE` opts in to intranet addresses; loopback and cloud metadata addresses are always refused. `PRISM_LINK_IMPORTS=false` turns the feature off.
- Adds migration `0003` (a `dataset_links` table and `imports.source_url`).

## 1.2.0 — 2026-11-18

- Dashboard filters: authors add up to six filters (a list of values, or a date range) and viewers narrow every chart that has the field at once. Fields match across datasets ignoring case and spacing; a chart without the field says it is not filtered. Selections live in the page address, so links keep them, and shared dashboard links offer the same filters as a plain form with no JavaScript. Filters are bound parameters ANDed onto each chart's own query, so they can only narrow what a chart shows. Adds migration `0002` (a `filters` column on dashboards).

## 1.1.0 — 2026-11-18

- Import SQLite databases (`.sqlite`, `.sqlite3`, `.db`) and Parquet files (`.parquet`). A database's tables appear in the review's table picker, and the dataset is named after the table. Both go through the same type proposal, review, versioning and refresh as spreadsheets. Uploaded databases are opened in memory, read-only and hardened: only ordinary tables are offered, nothing runs through a view or trigger, and each read has a time limit. BLOB values are skipped with a warning; Parquet nested values become JSON text and zoned timestamps become UTC.
- NEXORA host stack generates its own secrets: a one-shot `init-secrets` service writes a random database password into a private volume (Postgres reads it as a file, Prism through a libpq passfile), and Prism keeps generating its secret key in its data volume. No secrets file is needed on the host.

## 1.0.1 — 2026-11-04

- Hosting on the NEXORA platform: `deploy/nexora/compose.yml` (compose project `prism`, PostgreSQL 16, published image, no host ports; served by the shared edge Caddy).
- `prism create-admin --random-password` and `prism reset-link --email …` hand an account over with a single-use link, so no password is ever chosen for someone or sent.
- Fix: `PRISM_FORWARDED_ALLOW_IPS` was never read, so behind the bundled proxy every request looked like it came from the proxy and failed sign-ins shared one rate-limit bucket. It is now honoured, and `PRISM_CLIENT_IP_HEADER` (e.g. `CF-Connecting-IP`) names the real client behind a CDN.
- `PRISM_DATABASE_PASSWORD` is escaped into the database URL, so the Postgres password may contain any character; both compose files use it.
- Fix: accepting an admin-issued password-reset link now re-enables a disabled account.
- Landing page: contact hello@onenexora.com and USD prices, matching onenexora.com/pricing.
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
