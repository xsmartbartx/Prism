# Install & operate Prism

Prism ships as one container image. The recommended single-server setup is Docker Compose with Caddy in front for automatic HTTPS.

## Requirements

- A Linux server (x86-64 or ARM64) with Docker Engine 24+ and the Compose plugin
- 2 vCPU / 4 GB RAM handles a department; add RAM for multi-million-row datasets
- A DNS name pointing at the server, and ports 80 and 443 open (for HTTPS certificates)

## 1. Configure

```bash
mkdir prism && cd prism
# From a release: download compose.yml, Caddyfile and env.example
# From source:   cd deploy
cp env.example .env
```

Edit `.env`:

| Variable | Required | Meaning |
|---|---|---|
| `PRISM_DOMAIN` | yes | Public hostname, e.g. `analytics.example.com` |
| `ACME_EMAIL` | yes | Email for Let's Encrypt notices |
| `PRISM_SECRET_KEY` | recommended | Random 48+ character string (`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`) |
| `PRISM_LICENSE_KEY` | no | Pro/Business key (can also be pasted in the UI) |
| `PRISM_MAX_UPLOAD_MB` | no | Server-side upload ceiling (default 100) |
| `PRISM_BACKUP_KEEP` | no | Daily backups to keep (default 14) |
| `PRISM_DATABASE_URL` | no | PostgreSQL URL; empty = embedded SQLite |
| `PRISM_DATABASE_PASSWORD` | no | Database password, escaped into the URL (compose sets it from `POSTGRES_PASSWORD`) |
| `PRISM_CLIENT_IP_HEADER` | no | Client-IP header of a CDN that is the only way in (e.g. `CF-Connecting-IP`) |
| `PRISM_IMAGE` | no | Image tag, e.g. `ghcr.io/xsmartbartx/prism:1.0.0` (pin in production) |

## 2. Start

```bash
docker compose up -d
docker compose ps          # prism should be "healthy"
```

Open `https://PRISM_DOMAIN` and create the owner account. The first account owns the instance and the license.

Prefer the command line? `docker compose exec prism prism create-admin --email you@example.com`.

## PostgreSQL (optional)

SQLite (WAL mode) is the default and suits most single-node installs. For higher write concurrency or managed databases:

```bash
# in .env
POSTGRES_PASSWORD=<strong password>
PRISM_DATABASE_URL=postgresql+psycopg://prism@postgres:5432/prism   # no password here

docker compose --profile postgres up -d
```

Any PostgreSQL 14+ works, including managed services; point `PRISM_DATABASE_URL` at it and skip the profile.

## Backups

The `backup` service writes `prism-backup-<timestamp>.tar.gz` into `/var/lib/prism/backups` every 24 hours and keeps the newest `PRISM_BACKUP_KEEP`.

```bash
docker compose exec prism prism backup --include-uploads   # on demand
docker compose cp prism:/var/lib/prism/backups ./backups   # copy off the server
```

Copy archives off the machine (object storage, another host). An archive contains all metadata as JSON plus the dataset Parquet files, so it restores onto SQLite or PostgreSQL:

```bash
docker compose cp ./prism-backup-20261104T020000Z.tar.gz prism:/tmp/
docker compose exec prism prism restore /tmp/prism-backup-20261104T020000Z.tar.gz --force
docker compose restart prism
```

## Upgrades

```bash
# .env: PRISM_IMAGE=ghcr.io/xsmartbartx/prism:<new version>
docker compose exec prism prism backup
docker compose pull && docker compose up -d
```

Database migrations run automatically on start-up and are forward-only. Keep the pre-upgrade backup until you have checked the new version.

## Operations

| Task | Command |
|---|---|
| Logs (structured JSON) | `docker compose logs -f prism` |
| Health | `GET /healthz` (process), `GET /readyz` (database + storage) |
| Reset a password | `docker compose exec prism prism reset-password --email user@example.com` |
| Apply migrations manually | `docker compose exec prism prism migrate` |

Share and API-key tokens are redacted from logs.

## Running without Docker

```bash
pip install "prism[postgres] @ <wheel or source path>"
export PRISM_DATA_DIR=/var/lib/prism PRISM_BASE_URL=https://analytics.example.com
prism serve --host 127.0.0.1 --port 8080
```

Build the web UI with `npm ci && npm run build` in `web/` and set `PRISM_STATIC_DIR` to `web/dist`. Put a TLS-terminating reverse proxy in front and pass `--forwarded-allow-ips` with its address.

## Hardening checklist

- Serve only over HTTPS (`PRISM_BASE_URL=https://…`) — session cookies are then marked `Secure`.
- Keep the container read-only with dropped capabilities (the provided compose file does this).
- Restrict SSH and the Docker socket; Prism needs no inbound ports besides 80/443 on Caddy.
- Ship backups off-host and test a restore quarterly.
- Review the audit log integrity banner (Audit log page) periodically.
