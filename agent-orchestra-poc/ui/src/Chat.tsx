import { useCallback, useEffect, useMemo, useState } from "react";
import { Api } from "./api";
import { KIND_FR, PERFORMATIVE_FR, SENDABLE, fmtDateTime } from "./labels";
import { useApp, useOnEvents } from "./store";
import type { ChatMessage, Incident, Me, PendingApproval } from "./types";

const EVENT_TYPES = ["sent", "woken", "vote"] as ("sent" | "woken" | "vote")[];

export function Chat() {
  const { session, names } = useApp();
  const [me, setMe] = useState<Me | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [chain, setChain] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Api.chat().then(setMessages).catch((e) => setError(String(e)));
    Api.approvals().then(setApprovals).catch(() => undefined);
  }, []);
  useEffect(() => { Api.me().then(setMe).catch((e) => setError(String(e))); load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, [load]);
  useEffect(() => { if (session.id === "ing-qualite") Api.incidents().then(setIncidents).catch(() => undefined); }, [session.id]);
  useOnEvents(EVENT_TYPES, load);

  const name = (id: string) => names.get(id) ?? id.replace(/^inbox:/, "").replace(/^routine:/, "routine ").replace(/^approval:.*/, "Comité");
  const threads = useMemo(() => {
    const by = new Map<string, ChatMessage[]>();
    for (const m of messages) by.set(m.chainId, [...(by.get(m.chainId) ?? []), m]);
    return [...by.entries()].map(([id, ms]) => ({ id, ms, last: ms[ms.length - 1] })).sort((a, b) => b.last.createdAt.localeCompare(a.last.createdAt));
  }, [messages]);
  const current = threads.find((t) => t.id === chain) ?? null;

  return (
    <div className="chat" data-testid="chat">
      <aside className="threads">
        <div className="threads-head"><h2>Conversations</h2><button className="ghost" onClick={() => setChain(null)}>Nouvelle</button></div>
        {threads.length === 0 && <p className="muted pad">Aucun message pour le moment.</p>}
        {threads.map((t) => (
          <button key={t.id} className={`thread ${t.id === chain ? "on" : ""}`} onClick={() => setChain(t.id)} data-testid="thread">
            <b>{t.ms[0].body?.slice(0, 54) || "(sans texte)"}</b>
            <span>{name(t.last.from)} · {fmtDateTime(t.last.createdAt)}</span>
          </button>
        ))}
      </aside>
      <section className="pane">
        {error && <p className="error">{error}</p>}
        {session.id === "ing-qualite" && <IncidentPanel incidents={incidents} onDone={(c) => { load(); setChain(c); }} />}
        {approvals.length > 0 && <Approvals approvals={approvals} name={name} onDone={load} />}
        <div className="messages" data-testid="messages">
          {current ? current.ms.map((m) => <Bubble key={m.id} m={m} name={name} />) : <p className="muted pad">Choisissez une conversation, ou écrivez un nouveau message.</p>}
        </div>
        {me && <Composer me={me} chain={chain} name={name} onSent={(c) => { load(); setChain(c); }} />}
      </section>
    </div>
  );
}

function Bubble({ m, name }: { m: ChatMessage; name: (id: string) => string }) {
  const kind = typeof m.payload?.kind === "string" ? m.payload.kind : null;
  return (
    <article className={`bubble ${m.direction}`} data-testid="message">
      <header><b>{m.direction === "out" ? "Vous" : name(m.from)}</b><span className="tag">{PERFORMATIVE_FR[m.performative] ?? m.performative}</span>
        {kind && <span className="tag kind">{KIND_FR[kind] ?? kind}</span>}{m.hasSharedMemory && <span className="tag mem">Mémoire jointe</span>}
        <time>{fmtDateTime(m.createdAt)}</time></header>
      <p>{m.body}</p>
      {m.direction === "out" && <footer>à {m.to.map(name).join(", ")}</footer>}
    </article>
  );
}

function Composer({ me, chain, name, onSent }: { me: Me; chain: string | null; name: (id: string) => string; onSent: (chain: string) => void }) {
  const choices = me.canSendTo.filter((x) => x !== "incidents" && !x.startsWith("kg.") && !x.startsWith("produit."));
  const [to, setTo] = useState(choices[0] ?? "");
  const [perf, setPerf] = useState<string>("request");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!to && choices[0]) setTo(choices[0]); }, [choices.join(",")]);
  const send = async () => {
    if (!text.trim() || !to) return;
    setBusy(true); setErr(null);
    try { const r = await Api.send({ to: [to], performative: perf, body: text.trim(), chainId: chain ?? undefined }); setText(""); onSent(r.chainId); }
    catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
      <div className="row">
        <label>À <select value={to} onChange={(e) => setTo(e.target.value)} data-testid="to">{choices.map((c) => <option key={c} value={c}>{name(c.replace(/^inbox:/, ""))}</option>)}</select></label>
        <label>Type <select value={perf} onChange={(e) => setPerf(e.target.value)}>{SENDABLE.map((p) => <option key={p} value={p}>{PERFORMATIVE_FR[p]}</option>)}</select></label>
        <span className="muted">{chain ? "Réponse dans la conversation" : "Nouvelle conversation"}</span>
      </div>
      <div className="row grow"><textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Votre message…" rows={2} data-testid="compose" />
        <button type="submit" disabled={busy || !text.trim()} data-testid="send">Envoyer</button></div>
      {err && <p className="error">{err}</p>}
    </form>
  );
}

function IncidentPanel({ incidents, onDone }: { incidents: Incident[]; onDone: (chain: string) => void }) {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!id && incidents[0]) setId(incidents[0].id); }, [incidents]);
  const inc = incidents.find((i) => i.id === id);
  const publish = async () => {
    if (!inc) return;
    setBusy(true); setErr(null);
    try {
      const r = await Api.send({ to: ["incidents"], performative: "inform", body: inc.description,
        payload: { kind: "incident", incidentId: inc.id, componentId: inc.componentId, severity: inc.severity } });
      onDone(r.chainId);
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="card incident" data-testid="incident-panel">
      <h3>Déclarer un incident</h3>
      <div className="row">
        <select value={id} onChange={(e) => setId(e.target.value)} data-testid="incident-select">
          {incidents.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.severity} · {i.componentId}</option>)}
        </select>
        <button onClick={publish} disabled={busy || !inc} data-testid="publish-incident">Publier dans le topic « incidents »</button>
      </div>
      {inc && <p className="muted">{inc.description}</p>}{err && <p className="error">{err}</p>}
    </div>
  );
}

function Approvals({ approvals, name, onDone }: { approvals: PendingApproval[]; name: (id: string) => string; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const vote = async (id: string, d: "approve" | "reject") => {
    setBusy(id); setErr(null);
    try { await Api.vote(id, d); onDone(); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };
  return (
    <div className="card approvals" data-testid="approvals">
      <h3>Validations en attente ({approvals.length})</h3>
      {approvals.map((a) => (
        <div key={a.id} className="approval" data-testid="approval">
          <div><b>Lancement de la modification</b> demandé par {name(a.requestedBy)} · politique {a.policy} · {a.votes}/{a.quorum} voix</div>
          <div className="muted">Remplacer <code>{a.args.part_id ?? "?"}</code> par <code>{a.args.replacement_id ?? "?"}</code> — {a.args.description}</div>
          <div className="row"><button className="ok" disabled={busy === a.id} onClick={() => vote(a.id, "approve")} data-testid="approve">Approuver</button>
            <button className="danger" disabled={busy === a.id} onClick={() => vote(a.id, "reject")} data-testid="reject">Refuser</button></div>
        </div>
      ))}
      {err && <p className="error">{err}</p>}
    </div>
  );
}
