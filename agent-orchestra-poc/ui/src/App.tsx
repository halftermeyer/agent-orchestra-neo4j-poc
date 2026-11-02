import { useEffect, useState } from "react";
import { Api, loadSession, saveSession } from "./api";
import { Chat } from "./Chat";
import { ReplayView } from "./Replay";
import { GraphView } from "./GraphView";
import { Scene } from "./Scene";
import { Settings } from "./Settings";
import { Timeline } from "./Timeline";
import { AppProvider, useApp } from "./store";
import type { DemoUser, Session } from "./types";

const TABS = [["chat", "Chat"], ["scene", "Scene"], ["graphe", "Graph"], ["frise", "Timeline"], ["relecture", "Replay"], ["parametres", "Settings → Models"]] as const;
type Tab = (typeof TABS)[number][0];

export default function App() {
  const [session, setSession] = useState<Session | null>(loadSession());
  const login = async (id: string) => { const s = await Api.login(id); saveSession(s); setSession(s); };
  const logout = () => { saveSession(null); setSession(null); };
  if (!session) return <Login onPick={login} />;
  return <AppProvider session={session}><Shell onLogout={logout} /></AppProvider>;
}

function Login({ onPick }: { onPick: (id: string) => Promise<void> }) {
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { Api.users().then(setUsers).catch((e) => setErr(String(e))); }, []);
  return (
    <main className="login" data-testid="login">
      <h1>Agent Orchestra</h1>
      <p className="muted">Demo: pick the user to play. Each user only sees their own inbox.</p>
      {err && <p className="error">{err}</p>}
      <div className="user-grid">
        {users.map((u) => (
          <button key={u.id} className="user-card" onClick={() => onPick(u.id)} data-testid={`user-${u.id}`}>
            <span className="user-dot" style={{ background: u.admin ? "#E8A33D" : `hsl(${[...u.id].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7)} 55% 62%)` }} />
            <b>{u.name}</b><span>{u.title}</span>
          </button>))}
      </div>
    </main>
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const { session, connected } = useApp();
  const [tab, setTab] = useState<Tab>(session.kind === "admin" ? "scene" : "chat");
  return (
    <div className="shell">
      <header>
        <strong className="brand">Agent Orchestra</strong>
        <nav>{TABS.map(([id, label]) => <button key={id} className={`tab ${tab === id ? "on" : ""}`} onClick={() => setTab(id)} data-testid={`tab-${id}`}>{label}</button>)}</nav>
        <span className={`live ${connected ? "on" : ""}`} data-testid="live" title="Event stream">{connected ? "Live stream connected" : "Live stream disconnected"}</span>
        <span className="who" data-testid="who">{session.name}</span>
        <button className="ghost" onClick={onLogout} data-testid="logout">Switch user</button>
      </header>
      <main>
        {tab === "chat" && (session.kind === "user" ? <Chat /> : <div className="card"><p>The administrator has no inbox: pick a person to use the chat.</p></div>)}
        {tab === "scene" && <Scene />}
        {tab === "graphe" && <GraphView />}
        {tab === "frise" && <Timeline />}
        {tab === "relecture" && <ReplayView />}
        {tab === "parametres" && <Settings />}
      </main>
    </div>
  );
}
