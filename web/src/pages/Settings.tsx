import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, KeyRound, Plus, ShieldAlert, Trash2, UserPlus } from "lucide-react";
import { ROLES, can, del, patch, post, put, type AuditEvent, type LicenseInfo, type Role, type User } from "../api";
import { useApp, useLoad } from "../app-state";
import { Confirm, CopyField, ErrorBox, Modal, PageLoading, fmtBytes, fmtDate, fmtNum, timeAgo } from "../components/ui";

const ROLE_HELP: Record<Role, string> = {
  viewer: "Open dashboards and charts, export within limits",
  explorer: "Viewer + build personal charts and dashboards",
  author: "Explorer + import data and publish datasets",
  steward: "Author + certify datasets",
  admin: "Everything, including members and settings",
  auditor: "Read the audit log only — no data rows",
};

export function SettingsHome() {
  const { me, refresh, toast } = useApp();
  const [name, setName] = useState(me?.user.name ?? "");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [wsName, setWsName] = useState(me?.workspace.name ?? "");
  const [newWs, setNewWs] = useState(false);
  const instance = useLoad<{ version: string; instance_id: string; database: string; storage_bytes: number; base_url: string; max_upload_mb: number }>(can.admin(me?.role) ? "/api/v1/admin/instance" : null);
  if (!me) return null;
  return (
    <>
      <div className="page-head"><div className="grow"><h1>Settings</h1><p>Your profile, workspace and this Prism instance.</p></div></div>
      <div className="grid-2">
        <div className="card card-pad stack">
          <h2>Profile</h2>
          <label className="field">Email<input className="input" value={me.user.email} disabled /></label>
          <label className="field">Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <div>
            <button className="btn" onClick={async () => { try { await patch("/api/v1/auth/me", { name }); await refresh(); toast("Profile saved"); } catch (e) { toast((e as Error).message, "error"); } }}>Save profile</button>
          </div>
        </div>
        <form
          className="card card-pad stack"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await post("/api/v1/auth/password", pw);
              setPw({ current_password: "", new_password: "" });
              toast("Password changed. Other sessions were signed out.");
            } catch (err) {
              toast((err as Error).message, "error");
            }
          }}
        >
          <h2>Password</h2>
          <label className="field">Current password<input className="input" type="password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} autoComplete="current-password" /></label>
          <label className="field">New password <span className="hint">At least 10 characters.</span><input className="input" type="password" required minLength={10} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} autoComplete="new-password" /></label>
          <div><button type="submit" className="btn">Change password</button></div>
        </form>
        {can.admin(me.role) && (
          <div className="card card-pad stack">
            <h2>Workspace</h2>
            <label className="field">Name<input className="input" value={wsName} onChange={(e) => setWsName(e.target.value)} /></label>
            <div className="row">
              <button className="btn" onClick={async () => { try { await patch("/api/v1/workspace", { name: wsName }); await refresh(); toast("Workspace renamed"); } catch (e) { toast((e as Error).message, "error"); } }}>Save</button>
              <button className="btn btn-ghost" onClick={() => setNewWs(true)}><Plus size={16} /> New workspace</button>
            </div>
            <p className="muted small">Your role here: <strong>{me.role}</strong>. <Link to="/settings/members">Manage members</Link> · <Link to="/settings/license">License &amp; plan</Link></p>
          </div>
        )}
        {instance.data && (
          <div className="card card-pad stack">
            <h2>Instance</h2>
            <dl className="kbd-row">
              <dt>Version</dt><dd>{instance.data.version}</dd>
              <dt>Instance ID</dt><dd className="mono">{instance.data.instance_id}</dd>
              <dt>Database</dt><dd>{instance.data.database}</dd>
              <dt>Dataset storage</dt><dd>{fmtBytes(instance.data.storage_bytes)}</dd>
              <dt>Public URL</dt><dd>{instance.data.base_url}</dd>
              <dt>Upload limit</dt><dd>{instance.data.max_upload_mb} MB</dd>
            </dl>
            <p className="muted small"><a href="/api/docs" target="_blank" rel="noreferrer">REST API documentation</a></p>
          </div>
        )}
      </div>
      {newWs && <NewWorkspace onClose={() => setNewWs(false)} />}
    </>
  );
}

function NewWorkspace({ onClose }: { onClose: () => void }) {
  const { switchWorkspace, toast } = useApp();
  const [name, setName] = useState("");
  const create = async () => {
    try {
      const ws = await post<{ id: string }>("/api/v1/workspace/new", { name });
      await switchWorkspace(ws.id);
      onClose();
      toast("Workspace created");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Modal title="New workspace" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={create} disabled={!name.trim()}>Create</button></>}>
      <p className="muted small">Workspaces keep datasets, charts and members fully separate — e.g. one per department or client.</p>
      <label className="field">Name<input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
    </Modal>
  );
}

interface Invite { id: string; email: string; role: Role; expires_at: string; link?: string }

export function Members() {
  const { me, toast } = useApp();
  const members = useLoad<(User & { role: Role })[]>("/api/v1/workspace/members");
  const invites = useLoad<Invite[]>("/api/v1/workspace/invites");
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<{ title: string; url: string } | null>(null);
  const [removing, setRemoving] = useState<User | null>(null);

  if (members.error) return <ErrorBox error={members.error} />;
  if (!members.data) return <PageLoading />;
  return (
    <>
      <div className="page-head">
        <div className="grow"><h1>Members</h1><p>People in <strong>{me?.workspace.name}</strong> and what they can do.</p></div>
        <button className="btn btn-primary" onClick={() => setInviting(true)}><UserPlus size={16} /> Invite</button>
      </div>
      <div className="table-wrap" style={{ marginBottom: 20 }}>
        <table className="table">
          <thead><tr><th>Member</th><th>Role</th><th>Last sign-in</th><th /></tr></thead>
          <tbody>
            {members.data.map((m) => (
              <tr key={m.id}>
                <td><strong>{m.name}</strong><div className="muted small">{m.email}</div></td>
                <td>
                  <select className="input input-sm" style={{ width: 130 }} value={m.role} disabled={m.id === me?.user.id}
                    onChange={async (e) => { try { await patch(`/api/v1/workspace/members/${m.id}`, { role: e.target.value }); toast("Role updated"); void members.reload(); } catch (err) { toast((err as Error).message, "error"); } }}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td className="muted">{timeAgo(m.last_login_at)}</td>
                <td style={{ textAlign: "right" }}>
                  {m.id !== me?.user.id && (
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn btn-sm" onClick={async () => { try { const r = await post<{ link: string }>(`/api/v1/workspace/members/${m.id}/reset-link`); setLink({ title: `Password reset link for ${m.email}`, url: r.link }); } catch (e) { toast((e as Error).message, "error"); } }}>Reset link</button>
                      <button className="btn btn-sm btn-danger" onClick={() => setRemoving(m)}>Remove</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {invites.data && invites.data.length > 0 && (
        <>
          <h2 style={{ marginBottom: 10 }}>Pending invitations</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Email</th><th>Role</th><th>Expires</th><th /></tr></thead>
              <tbody>
                {invites.data.map((i) => (
                  <tr key={i.id}>
                    <td>{i.email}</td><td>{i.role}</td><td className="muted">{fmtDate(i.expires_at, true)}</td>
                    <td style={{ textAlign: "right" }}><button className="btn btn-sm btn-danger" onClick={async () => { await del(`/api/v1/workspace/invites/${i.id}`); void invites.reload(); }}>Revoke</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="card card-pad" style={{ marginTop: 20 }}>
        <h3 style={{ marginBottom: 8 }}>Roles</h3>
        <dl className="kbd-row">{ROLES.map((r) => <Fragment key={r}><dt>{r}</dt><dd>{ROLE_HELP[r]}</dd></Fragment>)}</dl>
      </div>
      {inviting && <InviteModal onClose={() => setInviting(false)} onCreated={(inv) => { setInviting(false); void invites.reload(); setLink({ title: `Invitation for ${inv.email}`, url: inv.link! }); }} />}
      {link && (
        <Modal title={link.title} onClose={() => setLink(null)}>
          <p className="muted small">Send this single-use link to the person (chat, email, …). It is shown only once.</p>
          <CopyField value={link.url} />
        </Modal>
      )}
      {removing && (
        <Confirm title="Remove member?" message={<>Remove <strong>{removing.email}</strong> from this workspace? Their account stays, but they lose access here.</>} confirmLabel="Remove"
          onClose={() => setRemoving(null)} onConfirm={async () => { await del(`/api/v1/workspace/members/${removing.id}`); void members.reload(); toast("Member removed"); }} />
      )}
    </>
  );
}

function InviteModal({ onClose, onCreated }: { onClose: () => void; onCreated: (i: Invite) => void }) {
  const { toast } = useApp();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const submit = async () => {
    try {
      onCreated(await post<Invite>("/api/v1/workspace/invites", { email, role }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <Modal title="Invite a member" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={submit} disabled={!email}>Create invite link</button></>}>
      <label className="field">Email<input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label className="field">Role<span className="hint">{ROLE_HELP[role]}</span>
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select>
      </label>
    </Modal>
  );
}

interface ApiKey { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null; revoked_at: string | null; secret?: string }

export function ApiKeys() {
  const { toast } = useApp();
  const keys = useLoad<ApiKey[]>("/api/v1/workspace/api-keys");
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiKey | null>(null);
  return (
    <>
      <div className="page-head"><div className="grow"><h1>API keys</h1><p>Use the REST API from scripts, notebooks and other tools. Keys act as you, in this workspace.</p></div></div>
      <div className="card card-pad stack" style={{ marginBottom: 16 }}>
        <div className="row">
          <input className="input" style={{ maxWidth: 320 }} placeholder="Key name, e.g. Nightly ETL" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn btn-primary" disabled={!name.trim()} onClick={async () => { try { setCreated(await post<ApiKey>("/api/v1/workspace/api-keys", { name })); setName(""); void keys.reload(); } catch (e) { toast((e as Error).message, "error"); } }}><KeyRound size={16} /> Create key</button>
        </div>
        <p className="muted small">Send it as <code>Authorization: Bearer prism_…</code>. See the <a href="/api/docs" target="_blank" rel="noreferrer">API reference</a>.</p>
      </div>
      {keys.error && <ErrorBox error={keys.error} />}
      {keys.data && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Name</th><th>Key</th><th>Created</th><th>Last used</th><th /></tr></thead>
            <tbody>
              {keys.data.map((k) => (
                <tr key={k.id} style={k.revoked_at ? { opacity: 0.5 } : undefined}>
                  <td>{k.name}</td><td className="mono">prism_{k.prefix}_…</td><td>{fmtDate(k.created_at)}</td><td className="muted">{timeAgo(k.last_used_at)}</td>
                  <td style={{ textAlign: "right" }}>{k.revoked_at ? <span className="badge">revoked</span> : <button className="btn btn-sm btn-danger" onClick={async () => { await del(`/api/v1/workspace/api-keys/${k.id}`); void keys.reload(); }}><Trash2 size={14} /> Revoke</button>}</td>
                </tr>
              ))}
              {keys.data.length === 0 && <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: 20 }}>No keys yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {created?.secret && (
        <Modal title="Your new API key" onClose={() => setCreated(null)}>
          <div className="alert alert-warning"><ShieldAlert size={16} /><div>Copy it now. For your security it won't be shown again.</div></div>
          <CopyField value={created.secret} />
        </Modal>
      )}
    </>
  );
}

export function License() {
  const { toast } = useApp();
  const { data, error, reload } = useLoad<LicenseInfo>("/api/v1/admin/license");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <PageLoading />;
  const statusCls = data.status === "active" ? "badge-success" : data.status === "grace" ? "badge-warning" : data.status === "invalid" || data.status === "expired" ? "badge-danger" : "";
  const meters: [string, string][] = [["users", "Users"], ["workspaces", "Workspaces"], ["datasets", "Datasets"], ["dashboards", "Dashboards"]];
  return (
    <>
      <div className="page-head"><div className="grow"><h1>License &amp; plan</h1><p>Instance <span className="mono">{data.instance_id}</span></p></div></div>
      {data.warnings.map((w) => <div key={w} className="alert alert-warning" style={{ marginBottom: 12 }}><ShieldAlert size={16} /><div>{w}</div></div>)}
      {data.error && <div className="alert alert-danger" style={{ marginBottom: 12 }}><div>{data.error}</div></div>}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card card-pad stack">
          <div className="row"><h2 style={{ flex: 1 }}>{data.plan.name} plan</h2><span className={`badge ${statusCls}`}>{data.status}</span></div>
          {data.customer && <dl className="kbd-row"><dt>Licensed to</dt><dd>{data.customer} ({data.email})</dd><dt>Expires</dt><dd>{data.expires_at ? fmtDate(data.expires_at) : "never"}</dd></dl>}
          <div className="stack" style={{ gap: 10 }}>
            {meters.map(([k, label]) => {
              const limit = data.plan.limits[k];
              const used = data.usage[k] ?? 0;
              const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
              return (
                <div key={k}>
                  <div className="row-between small"><span>{label}</span><span className="muted">{fmtNum(used)} / {limit === null ? "unlimited" : fmtNum(limit)}</span></div>
                  {limit !== null && <div className={`meter ${pct >= 80 ? "warn" : ""}`}><span style={{ width: `${pct}%` }} /></div>}
                </div>
              );
            })}
          </div>
          <div className="row small">{["embed", "api", "white_label"].map((f) => <span key={f} className={`badge ${data.plan.features.includes(f) ? "badge-success" : ""}`}>{data.plan.features.includes(f) ? <CheckCircle2 size={12} /> : null}{{ embed: "Embedding", api: "API keys", white_label: "No Prism branding" }[f]}</span>)}</div>
        </div>
        <div className="card card-pad stack">
          <h2>License key</h2>
          {data.env_locked ? (
            <p className="muted">The license is set by the <code>PRISM_LICENSE_KEY</code> environment variable on the server.</p>
          ) : data.can_manage ? (
            <>
              <textarea className="input mono" rows={5} placeholder="PRISM1.…" value={key} onChange={(e) => setKey(e.target.value)} />
              <div className="row">
                <button className="btn btn-primary" disabled={busy || !key.trim()} onClick={async () => { setBusy(true); try { await put("/api/v1/admin/license", { key: key.trim() }); setKey(""); toast("License installed"); void reload(); } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); } }}>Install key</button>
                {data.source === "database" && <button className="btn btn-danger" onClick={async () => { await del("/api/v1/admin/license"); toast("License removed"); void reload(); }}>Remove</button>}
              </div>
            </>
          ) : (
            <p className="muted">Only the instance owner can change the license.</p>
          )}
          <p className="muted small">Keys verify offline — no data leaves this server. Need more seats or features? Contact sales with your instance ID.</p>
        </div>
      </div>
      <h2 style={{ marginBottom: 10 }}>Compare plans</h2>
      <div className="grid-3">
        {Object.values(data.plans).map((p) => (
          <div key={p.code} className="card card-pad stack" style={p.code === data.plan.code ? { borderColor: "var(--accent)" } : undefined}>
            <div className="row-between"><h3>{p.name}</h3>{p.code === data.plan.code && <span className="badge badge-accent">current</span>}</div>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {Object.entries(p.limits).map(([k, v]) => <li key={k}>{v === null ? "Unlimited" : fmtNum(v)} {k === "upload_mb" ? "MB uploads" : k}</li>)}
              {p.features.filter((f) => f !== "share").map((f) => <li key={f}>{f.replace("_", " ")}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}

export function Audit() {
  const [action, setAction] = useState("");
  const { data, error } = useLoad<{ events: AuditEvent[] }>(`/api/v1/audit?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`, [action]);
  const verify = useLoad<{ ok: boolean; events_checked: number; first_broken_seq: number | null }>("/api/v1/audit/verify");
  const [open, setOpen] = useState<AuditEvent | null>(null);
  return (
    <>
      <div className="page-head">
        <div className="grow"><h1>Audit log</h1><p>Append-only record of every import, publish, share, export and permission change.</p></div>
        <select className="input" style={{ width: 200 }} value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter by action">
          <option value="">All actions</option>
          {["auth", "import", "dataset", "binding", "chart", "dashboard", "share", "member", "invite", "apikey", "license"].map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>
      {verify.data && (
        <div className={`alert ${verify.data.ok ? "alert-success" : "alert-danger"}`} style={{ marginBottom: 16 }}>
          {verify.data.ok ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}
          <div>{verify.data.ok ? `Integrity verified: ${fmtNum(verify.data.events_checked)} events form an unbroken hash chain.` : `Tampering detected at event #${verify.data.first_broken_seq}. Investigate immediately.`}</div>
        </div>
      )}
      {error && <ErrorBox error={error} />}
      {!data ? <PageLoading /> : (
        <div className="table-wrap">
          <table className="table table-clickable">
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>What</th></tr></thead>
            <tbody>
              {data.events.map((e) => (
                <tr key={e.id} onClick={() => setOpen(e)}>
                  <td className="muted nowrap">{fmtDate(e.timestamp, true)}</td>
                  <td>{e.actor ?? "system"}</td>
                  <td><span className="badge">{e.action}</span></td>
                  <td className="truncate" style={{ maxWidth: 520 }}>{e.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && (
        <Modal title={open.action} onClose={() => setOpen(null)} wide>
          <dl className="kbd-row">
            <dt>When</dt><dd>{fmtDate(open.timestamp, true)}</dd>
            <dt>Who</dt><dd>{open.actor ?? "system"}{open.ip ? ` from ${open.ip}` : ""}</dd>
            <dt>Target</dt><dd>{open.target_type} <span className="mono">{open.target_id}</span></dd>
            <dt>Description</dt><dd>{open.description}</dd>
          </dl>
          <pre className="mono" style={{ background: "var(--surface-2)", padding: 12, borderRadius: 6, overflow: "auto", maxHeight: 320, margin: 0 }}>{JSON.stringify(open.details, null, 2)}</pre>
        </Modal>
      )}
    </>
  );
}
