import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { get, post } from "../api";
import { useApp } from "../app-state";
import { ErrorBox, Logo, Spinner } from "../components/ui";

function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="center-page">
      <div className="card auth-card">
        <div className="card-pad stack">
          <div className="auth-logo"><Logo size={32} /> Prism</div>
          <div style={{ textAlign: "center" }}>
            <h1 style={{ fontSize: 20 }}>{title}</h1>
            {subtitle && <p className="muted" style={{ marginTop: 6 }}>{subtitle}</p>}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

export function Setup() {
  const { refresh } = useApp();
  const nav = useNavigate();
  const [f, setF] = useState({ name: "", email: "", password: "", workspace_name: "" });
  const { busy, error, run } = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await post("/api/v1/setup", { ...f, workspace_name: f.workspace_name || "My workspace" });
      await refresh();
      nav("/datasets");
    });
  };
  return (
    <AuthCard title="Welcome to Prism" subtitle="Create the owner account for this instance.">
      <form className="stack" onSubmit={submit}>
        {error && <ErrorBox error={error} />}
        <label className="field">Your name<input className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoComplete="name" /></label>
        <label className="field">Email<input className="input" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" /></label>
        <label className="field">
          Password <span className="hint">At least 10 characters.</span>
          <input className="input" type="password" required minLength={10} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" />
        </label>
        <label className="field">Workspace name<input className="input" placeholder="e.g. Finance team" value={f.workspace_name} onChange={(e) => setF({ ...f, workspace_name: e.target.value })} /></label>
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      </form>
    </AuthCard>
  );
}

export function Login() {
  const { refresh } = useApp();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();
  return (
    <AuthCard title="Sign in" subtitle="Use the account your administrator created for you.">
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await post("/api/v1/auth/login", { email, password });
            await refresh();
            nav("/datasets");
          });
        }}
      >
        {error && <ErrorBox error={error} />}
        <label className="field">Email<input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" autoFocus /></label>
        <label className="field">Password<input className="input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted small" style={{ textAlign: "center" }}>Forgot your password? Ask a workspace admin for a reset link.</p>
      </form>
    </AuthCard>
  );
}

interface InviteInfo { email: string; role: string; kind: string; workspace: string }

export function AcceptInvite() {
  const { token = "" } = useParams();
  const { refresh } = useApp();
  const nav = useNavigate();
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();

  useEffect(() => {
    get<InviteInfo>(`/api/v1/invites/${encodeURIComponent(token)}`).then(setInfo).catch((e) => setLoadErr(e.message));
  }, [token]);

  if (loadErr)
    return (
      <AuthCard title="Link unavailable">
        <ErrorBox error={loadErr} />
        <Link to="/login" className="btn btn-block">Go to sign in</Link>
      </AuthCard>
    );
  if (!info) return <div className="center-page"><Spinner /></div>;
  const reset = info.kind === "reset";
  return (
    <AuthCard
      title={reset ? "Choose a new password" : `Join ${info.workspace}`}
      subtitle={reset ? info.email : `You've been invited as ${info.role} (${info.email}).`}
    >
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            await post(`/api/v1/invites/${encodeURIComponent(token)}/accept`, { name, password });
            await refresh();
            nav("/datasets");
          });
        }}
      >
        {error && <ErrorBox error={error} />}
        {!reset && <label className="field">Your name<input className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>}
        <label className="field">
          {reset ? "New password" : "Choose a password"} <span className="hint">At least 10 characters.</span>
          <input className="input" type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </label>
        <button className="btn btn-primary btn-block" disabled={busy}>{reset ? "Save password" : "Join workspace"}</button>
      </form>
    </AuthCard>
  );
}
