# Prism

**Self-hosted data platform — drop a spreadsheet, get a trustworthy chart, share a link.**

Prism turns Excel and CSV files into typed, versioned datasets, lets people build charts and dashboards without SQL, and shares them with a link — on your own server, with an audit trail for every number.

- **Imports that don't lie.** Prism detects header rows, number/date formats and column types, then asks you to confirm what it can't be sure of. Rows that don't fit go to a quarantine you can inspect — nothing is silently coerced.
- **Refreshes that fail loudly.** Load next month's file and Prism checks it against the dataset's column contract. A renamed or missing column stops the load with a clear message instead of producing a wrong number.
- **Charts as specifications.** Bar, line, area, donut, scatter, KPI and table charts render server-side to accessible SVG — the same output on screen, in exports and on share pages.
- **Share safely.** Public links are read-only, expiring, revocable and counted; embeds are opt-in.
- **Audit everything.** Every import, publish, share and export is recorded in a tamper-evident, hash-chained log.
- **Runs anywhere.** One container, SQLite or PostgreSQL, automatic HTTPS, daily backups. No data leaves your server — license keys verify offline.

## Quick start (local trial)

```bash
docker compose -f deploy/compose.local.yml up --build
```

Open <http://localhost:8080>, create the owner account, and click **Load a sample sales dataset**.

## Production

```bash
cd deploy
cp env.example .env        # set PRISM_DOMAIN, ACME_EMAIL, PRISM_SECRET_KEY
docker compose up -d
```

Caddy obtains a Let's Encrypt certificate for `PRISM_DOMAIN`; backups run daily into the data volume. Full guide: [docs/install.md](docs/install.md).

## Plans

| | Community | Pro | Business |
|---|---|---|---|
| Users | 5 | 25 (or as licensed) | Unlimited |
| Workspaces | 1 | 3 | Unlimited |
| Datasets / dashboards | 10 / 5 | Unlimited | Unlimited |
| Upload size | 25 MB | 500 MB | 2 GB |
| Embedding, API keys, no Prism branding | — | ✓ | ✓ |
| Priority support | — | — | ✓ |

Community is free. Pro and Business are unlocked with an offline-verified license key (Settings → License or `PRISM_LICENSE_KEY`). See [docs/admin-guide.md](docs/admin-guide.md#license).

## Documentation

| Guide | For |
|---|---|
| [Install & operate](docs/install.md) | Deployment, HTTPS, PostgreSQL, backups, upgrades |
| [User guide](docs/user-guide.md) | Importing, reviewing, charts, dashboards, sharing |
| [Admin guide](docs/admin-guide.md) | Members, roles, license, audit log |
| [API](docs/api.md) | REST API with API keys (`/api/docs` on your instance) |
| [Security](docs/security.md) | Security model and responsible disclosure |
| [Selling Prism](docs/selling.md) | Vendor operations: pricing, issuing license keys, support |
| [Architecture](docs/prism-architecture-and-vision.md) | Design and roadmap |

## Development

Requirements: Python 3.11+, Node 22+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
(cd web && npm ci && npm run build)    # UI served by the API at /
PRISM_DATA_DIR=./var-dev prism serve   # http://localhost:8080
```

For UI work with hot reload run `npm run dev` in `web/` (proxies the API on :8080) and open <http://localhost:5173>.

```bash
pytest                      # 400+ tests
ruff check . && mypy core data presentation catalog schemas server tools
(cd web && npm run typecheck)
```

### Repository layout

```
core/          Type system, strict locale-aware parsing, errors, clock
data/          Connectors (CSV, XLSX), detection & proposals, load runner,
               Parquet dataset store, profiler, query compiler + DuckDB engine
presentation/  View spec, SVG renderer, recommendations, CSV/XLSX export
server/        FastAPI app, services (auth, imports, artifacts, licensing),
               metadata DB + Alembic migrations, backup/restore, CLI
web/           React + TypeScript web UI
deploy/        Dockerfile, compose (Caddy TLS, backups, PostgreSQL)
site/          Marketing landing page (static)
tools/         Vendor-only tooling (license issuing) — not shipped
tests/         Unit, integration and API tests
```

## License

Commercial software. See [LICENSE](LICENSE).
