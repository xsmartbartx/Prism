# Selling Prism — vendor operations

Internal guide for running Prism as a product. Not shipped to customers.

## Offer

| Plan | Suggested price | Limits | For |
|---|---|---|---|
| Community | Free | 5 users, 1 workspace, 10 datasets, 5 dashboards, 25 MB uploads, Prism branding on share pages | Evaluation, small teams, lead generation |
| Pro | €49 / instance / month, or €490 / year | 25 users (adjustable via `seats`), 3 workspaces, unlimited datasets/dashboards, 500 MB uploads, embedding, API keys, white-label share pages | Departments replacing spreadsheet reporting |
| Business | €199 / instance / month, or €1,990 / year | Unlimited users/workspaces, 2 GB uploads, priority support | Multi-team or client-facing deployments |

Prices are starting points: adjust in `site/index.html` and here. Limits live in `PLANS` in `server/services/licensing.py`; changing them affects every instance on upgrade, so grandfather existing customers through license `seats`/`workspaces` overrides rather than lowering defaults.

## Signing key — protect it

- The private key is `.secrets/license-signing-key.pem` (gitignored). **Move it to a password manager or HSM and delete the local copy after issuing.** Anyone with it can mint licenses.
- Its public half is `VENDOR_PUBLIC_KEY` in `server/services/licensing.py`. Rotating means generating a new pair, shipping a release with the new public key, and re-issuing keys to every customer.

## Issue a license

```bash
python tools/issue_license.py issue \
  --key /secure/path/license-signing-key.pem \
  --customer "Acme GmbH" --email it@acme.example \
  --plan pro --months 12 --seats 40
```

- `--months 0` issues a perpetual key (e.g. lifetime deals).
- `--seats` / `--workspaces` override the plan defaults.
- Send the printed `PRISM1.…` key to the customer. They paste it in **Settings → License** or set `PRISM_LICENSE_KEY`.
- Record license id (`lid` in the payload), customer, plan, seats and expiry in your CRM; renewals are new keys with a later `expires_at`.

Expired keys give a 14-day grace period before falling back to Community limits; no customer data is ever deleted.

## Taking payment

Keys are offline, so any checkout works: Stripe Payment Links / Checkout, Paddle or Lemon Squeezy (merchant of record handles EU VAT), or invoices for annual contracts. A minimal automated flow:

1. Checkout success webhook → your small issuing service (holds the signing key) → `issue_license.py` logic (`tools.issue_license.make_payload` + `sign`).
2. Email the key and the install guide link.
3. On renewal payment, issue a key with the new expiry.

## Release process

1. Update `CHANGELOG.md` and the version in `pyproject.toml`, `server/__init__.py` and `web/package.json`.
2. `git tag v1.x.y && git push --tags` — the Release workflow publishes `ghcr.io/xsmartbartx/prism:1.x.y` (amd64 + arm64) and attaches `compose.yml`, `Caddyfile`, `env.example` to the GitHub release.
3. Customers upgrade by changing `PRISM_IMAGE` and running `docker compose pull && docker compose up -d`.

If the repository is private, customers need registry access: either publish the image to a public registry, or issue per-customer pull tokens.

## Support checklist

- Ask for: Prism version (Settings → Instance), instance ID, `docker compose logs prism --since 1h`, and the request id shown in error messages.
- Common fixes: password reset (`prism reset-password`), restore from backup (`prism restore`), certificate issues (DNS/ports 80+443 for Caddy).

## Before the first sale

- Have a lawyer review `LICENSE` (EULA), and publish terms, privacy notice and a support policy on the website.
- Set the security contact referenced in `docs/security.md`.
- Point the landing page CTA links (`site/index.html`) at your checkout and contact addresses.
