import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BarChart3, Database, FileClock, KeyRound, LayoutDashboard, LogOut, Menu, Monitor, Moon, ScrollText, Settings, Sun, Users } from "lucide-react";
import { can, post } from "../api";
import { useApp } from "../app-state";
import { Logo } from "./ui";

function Item({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "active" : "")}>
      {icon}
      {children}
    </NavLink>
  );
}

export default function Layout() {
  const { me, switchWorkspace, theme, setTheme, refresh } = useApp();
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  if (!me) return null;
  const role = me.role;

  const cycleTheme = () => setTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system");
  const ThemeIcon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;

  return (
    <div className="shell">
      <aside className={`sidebar ${open ? "open" : ""}`} onClick={() => setOpen(false)}>
        <NavLink to="/" className="brand">
          <Logo /> Prism
        </NavLink>
        <nav className="nav" aria-label="Main">
          {can.read(role) && <Item to="/datasets" icon={<Database size={17} />}>Datasets</Item>}
          {can.read(role) && <Item to="/charts" icon={<BarChart3 size={17} />}>Charts</Item>}
          {can.read(role) && <Item to="/dashboards" icon={<LayoutDashboard size={17} />}>Dashboards</Item>}
          {can.author(role) && <Item to="/imports" icon={<FileClock size={17} />}>Imports</Item>}
          <div className="nav-section">Workspace</div>
          {can.admin(role) && <Item to="/settings/members" icon={<Users size={17} />}>Members</Item>}
          {can.audit(role) && <Item to="/settings/audit" icon={<ScrollText size={17} />}>Audit log</Item>}
          {can.explore(role) && <Item to="/settings/api-keys" icon={<KeyRound size={17} />}>API keys</Item>}
          <Item to="/settings" icon={<Settings size={17} />}>Settings</Item>
        </nav>
        <div className="sidebar-foot">
          {me.workspaces.length > 1 && (
            <select
              className="input input-sm"
              aria-label="Workspace"
              value={me.workspace.id}
              onClick={(e) => e.stopPropagation()}
              onChange={async (e) => {
                await switchWorkspace(e.target.value);
                nav("/datasets");
              }}
            >
              {me.workspaces.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          )}
          <div className="row" style={{ padding: "4px 8px" }}>
            <div className="grow" style={{ flex: 1, minWidth: 0 }}>
              <div className="truncate" style={{ fontWeight: 600 }}>{me.user.name}</div>
              <div className="truncate muted tiny">{me.workspace.name} · {role}</div>
            </div>
            <button className="btn btn-ghost btn-icon btn-sm" title={`Theme: ${theme}`} aria-label="Toggle theme" onClick={(e) => { e.stopPropagation(); cycleTheme(); }}>
              <ThemeIcon size={16} />
            </button>
            <button
              className="btn btn-ghost btn-icon btn-sm"
              title="Sign out"
              aria-label="Sign out"
              onClick={async () => {
                await post("/api/v1/auth/logout");
                await refresh();
                nav("/login");
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <div className="topbar menu-btn" style={{ display: undefined }}>
          <button className="btn btn-ghost btn-icon menu-btn" aria-label="Open menu" onClick={() => setOpen(true)}>
            <Menu size={18} />
          </button>
          <Logo size={22} />
          <strong>Prism</strong>
        </div>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
