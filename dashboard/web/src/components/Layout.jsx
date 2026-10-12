import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { convLabel, enc, fmtAgo } from "../lib.js";
import { useCrumbState, useDirectory, useLive } from "../live.jsx";

function SyncStatus() {
  const { status, connected, lastChange } = useLive();
  const [, setNow] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setNow((n) => n + 1), 5000);
    return () => clearInterval(t);
  }, []);
  const state = status?.state;
  const progress = status?.progress;
  let line;
  if (!status) line = "connecting…";
  else if (state === "disabled") line = "Slack sync off (no token)";
  else if (progress) line = `${state === "backfilling" ? "Backfilling" : "Syncing"} ${progress.current} (${progress.done + 1}/${progress.total})`;
  else if (state === "error") line = "Sync error";
  else line = `Synced ${fmtAgo(status.last_sync_at)}`;
  return (
    <div className="sync">
      <div className="sync-row">
        <span className={`live-dot${connected ? " on" : ""}`} title={connected ? "Live updates connected" : "Reconnecting…"} />
        <span>{connected ? "Live" : "Offline"}</span>
        <span className="sync-line">{line}</span>
      </div>
      {status?.token && (
        <div className="sync-meta">
          {status.team ? `${status.team} · ` : ""}{status.token} token · {status.readable}/{status.conversations} readable
        </div>
      )}
      {lastChange && <div className="sync-meta">last change {fmtAgo(new Date(lastChange.at).toISOString())}</div>}
      {status?.error && <div className="sync-error">{status.error}</div>}
      {status?.warnings?.length > 0 && (
        <details className="sync-warn">
          <summary>{status.warnings.length} sync warning{status.warnings.length > 1 ? "s" : ""}</summary>
          <ul>{status.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function Sidebar({ open }) {
  const navigate = useNavigate();
  const { users, convs, selectedUser, setSelectedUser, userName } = useDirectory();
  const channels = convs.filter((c) => !c.is_dm);
  const dms = convs.filter((c) => c.is_dm);
  const item = (c) => (
    <NavLink key={c.id} className="nav-item" to={`/c/${enc(c.id)}`} title={c.is_member === false ? "Not readable by the sync token" : c.topic || ""}>
      {c.is_dm ? <span className="dot dot-dm" /> : <span className="hash">{c.is_private ? "🔒" : "#"}</span>}
      <span className={`nav-label${c.is_member === false ? " dim" : ""}`}>{convLabel(c, userName)}</span>
      <span className="count">{c.message_count || ""}</span>
    </NavLink>
  );
  return (
    <aside className={`sidebar${open ? " open" : ""}`}>
      <div className="brand">
        <span className="brand-mark">◆</span>
        <span>AI Coworker</span>
        <ThemeToggle />
      </div>
      <label className="picker">
        <span className="picker-label">User</span>
        <select value={selectedUser} onChange={(e) => {
          setSelectedUser(e.target.value);
          navigate(e.target.value ? `/u/${enc(e.target.value)}` : "/");
        }}>
          <option value="">All users</option>
          {users.filter((u) => !u.alias_of && !u.deleted).map((u) => (
            <option key={u.id} value={u.id}>{u.name}{u.is_bot ? " (bot)" : ""} · {u.message_count} msgs</option>
          ))}
        </select>
      </label>
      <nav>
        <NavLink className="nav-item" to="/" end>Overview</NavLink>
        <div className="nav-section">Channels</div>
        {channels.length ? channels.map(item) : <div className="nav-empty">none</div>}
        <div className="nav-section">Direct messages</div>
        {dms.length ? dms.map(item) : <div className="nav-empty">{selectedUser ? "no DMs for this user" : "no DMs recorded"}</div>}
        <div className="nav-section">Agent traces</div>
        <NavLink className="nav-item" to="/runs/orchestrator"><span className="dot dot-orch" />Orchestrator runs</NavLink>
        <NavLink className="nav-item" to="/runs/github_agent"><span className="dot dot-gh" />GitHub agent runs</NavLink>
        <NavLink className="nav-item" to="/jobs"><span className="dot dot-job" />Coding jobs (sandbox)</NavLink>
      </nav>
      <SyncStatus />
    </aside>
  );
}

function ThemeToggle() {
  const toggle = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch { /* storage unavailable */ }
  };
  return <button className="theme-toggle" onClick={toggle} title="Toggle light/dark">◐</button>;
}

function Crumbs() {
  const crumbs = useCrumbState();
  return (
    <div className="crumbs">
      {crumbs.map(([label, to], i) => (
        <span key={i} className="crumb">
          {i > 0 && <span className="sep">›</span>}
          {to ? <Link to={to}>{label}</Link> : <span>{label}</span>}
        </span>
      ))}
    </div>
  );
}

// Tooltips for chart marks: any element with data-tip.
function useTooltips() {
  useEffect(() => {
    const tip = document.getElementById("tooltip");
    const move = (e) => {
      const t = e.target.closest?.("[data-tip]");
      if (!t) { tip.hidden = true; return; }
      tip.textContent = t.getAttribute("data-tip");
      tip.hidden = false;
      tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
      tip.style.top = `${e.clientY + 14}px`;
    };
    document.addEventListener("mousemove", move);
    return () => document.removeEventListener("mousemove", move);
  }, []);
}

export function Layout({ children, flush }) {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useTooltips();
  useEffect(() => setOpen(false), [location.pathname]);
  return (
    <div className="app">
      <Sidebar open={open} />
      <div className="main-wrap">
        <header className="topbar">
          <button className="menu-btn" aria-label="Menu" onClick={() => setOpen((o) => !o)}>☰</button>
          <Crumbs />
        </header>
        <main className={`main${flush ? " flush" : ""}`}>{children}</main>
      </div>
    </div>
  );
}
