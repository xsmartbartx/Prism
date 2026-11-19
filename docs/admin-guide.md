# Admin guide

## Members and roles

**Members** (admins only) lists everyone in the current workspace.

| Role | Can |
|---|---|
| Viewer | Open datasets, charts and dashboards; export |
| Explorer | Viewer + build and share their own charts and dashboards |
| Author | Explorer + import files, publish and refresh datasets, edit others' charts |
| Steward | Author + certify or deprecate datasets |
| Admin | Everything, including members, invites, workspace settings |
| Auditor | Read the audit log only — cannot see data rows |

The Auditor role is deliberately separate: reviewing who did what should not require seeing the data.

### Invite people

**Invite** → email + role → **Create invite link**. Send the single-use link (valid 72 hours) by any channel; the person chooses their own password. No mail server is needed. Pending invites count toward the plan's seat limit.

### Reset a password

**Members → Reset link** creates a 24-hour single-use link. Using it signs the person out everywhere. From the server: `prism reset-password --email …`.

### Workspaces

Workspaces separate datasets, charts, dashboards, members and the audit view completely — e.g. one per department or client. Create one in **Settings → New workspace**; switch with the selector in the sidebar.

## Certification

Stewards mark datasets **Certified** (requires a description) or **Deprecated**. Certified datasets are listed first so people find the trusted version.

## License

**Settings → License & plan** shows the plan, usage against limits and the instance ID.

- The instance owner (first account) pastes a key and clicks **Install key**, or sets `PRISM_LICENSE_KEY` on the server (which then takes precedence).
- Keys verify offline with a public key built into Prism. Nothing is sent anywhere.
- When a key expires there is a 14-day grace period, then Community limits apply. **No data is deleted**: existing datasets and dashboards stay readable; creating beyond the limits is blocked, embeds and API keys stop working, and share pages show Prism branding again.

Need more seats? Contact your vendor with your instance ID.

## Links and scheduled refresh

Authors can import a dataset from an `https://` link or a PostgreSQL table and refresh it from there on a schedule (Pro and Business). The Prism process checks every 30 seconds for refreshes that are due and runs them with the access of the author who set the schedule. Server settings:

| Variable | Default | Effect |
|---|---|---|
| `PRISM_LINK_IMPORTS` | `true` | `false` turns off importing and refreshing from links and databases (and the scheduler) |
| `PRISM_LINK_ALLOW_PRIVATE` | `false` | `true` lets links and database connections reach private network addresses, e.g. an intranet file server or an office database. Loopback and cloud metadata addresses stay refused |
| `PRISM_LINK_TIMEOUT_S` | `60` | Time limit for one download, redirects included |
| `PRISM_SCHEDULER` | `true` | `false` stops this process running scheduled refreshes (for example on a second replica sharing the database; schedules are leased, so running it on several is also safe) |

Each failed refresh is in the audit log (`dataset.refresh_failed`, or `dataset.drift` when the columns changed). See [Security → Links](security.md#links) for how downloads are protected.

## API keys

**API keys** (explorers and above, Pro/Business) create personal keys that act as the user in the current workspace. They're shown once and stored hashed. Admins see and can revoke all keys in the workspace.

## Audit log

**Audit log** (admins, auditors) shows every sign-in failure, import, publish, refresh, drift, chart/dashboard change, share, export, role change and license change, with actor and IP. Click an event for full details, including the dataset version and content hashes behind a chart.

Each event stores the hash of the previous one. The banner at the top re-verifies the whole chain: if any row was edited or deleted in the database, it reports where the chain breaks.
