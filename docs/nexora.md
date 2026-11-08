# Prism on the NEXORA platform

NEXORA hosts a Prism instance at `https://prism.onenexora.com`, on the shared platform VM next to
Vigilo, NeuraWall and CodeReviewer. The NEXORA side (product page, status, uptime, backups, edge
route, `deploy.sh prism`) is described in NEXORA's ADR-0016. This file is the Prism side.

## Layout on the host

| What | Where |
|---|---|
| Checkout | `/opt/prism` (this repository, `main`) |
| Compose file | `deploy/nexora/compose.yml`, compose project `prism` |
| Secrets | none on disk in the checkout: the DB password is generated into volume `prism_secrets`, the secret key into `prism_data` |
| Containers | `prism-app-1` (published image `ghcr.io/xsmartbartx/prism:$PRISM_VERSION`), `prism-postgres-1`, one-shot `prism-init-secrets-1` |
| Network | `prism_default`, joined by `edge-caddy-1`; no host ports |
| Data | volumes `prism_pgdata` (metadata), `prism_data` (Parquet datasets, uploads, secret key) and `prism_secrets` |

## Deploy

```bash
/opt/nexora/infrastructure/deployment/deploy.sh prism
```

It takes the host deploy lock, pulls this checkout, pulls the image named by `PRISM_VERSION` and
recreates the app. Migrations run on start-up. To upgrade, bump `PRISM_VERSION` in `/opt/prism/.env`
after a release (or change the default in `compose.yml`), then deploy.

## First start (once)

```bash
sudo git clone https://github.com/xsmartbartx/Prism.git /opt/prism && sudo chown -R opc:opc /opt/prism
cd /opt/prism && sudo docker compose -f deploy/nexora/compose.yml up -d
sudo docker network connect prism_default edge-caddy-1   # until the edge stack is next recreated
```

No secrets file is created. `init-secrets` writes a random database password into the
`prism_secrets` volume on first start (mode 600, one copy for Postgres, one libpq passfile for
Prism) and keeps it on later starts; Prism generates its secret key in `prism_data`. Optional,
non-secret overrides (for example `PRISM_LICENSE_KEY`) go in an env file in `/opt/prism`, which
`deploy.sh prism` passes to Compose when it exists (see `deploy/nexora/env.example`).

Claim the instance **before** the DNS record exists, so nobody else can complete the first-run setup:

```bash
sudo docker exec prism-app-1 prism create-admin --email owner@example.com --random-password --workspace NEXORA
sudo docker exec prism-app-1 prism reset-link --email owner@example.com
```

The second command prints a single-use link (24 hours) where the owner chooses their own password.
Nobody else ever knows it.

## Backups

NEXORA's nightly `backup-all.sh` dumps `prism-postgres-1` and archives the `prism_data` volume.
`prism backup` inside the container also works and is database-agnostic.

## Rollback

Set `PRISM_VERSION` back and deploy. To take the instance offline, remove the edge route and
`docker compose -f deploy/nexora/compose.yml down` (volumes are kept).
