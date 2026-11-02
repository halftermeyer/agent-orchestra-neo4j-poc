import { useEffect, useState } from "react";
import { Api } from "./api";
import { fmtDateTime } from "./labels";
import { useApp } from "./store";
import type { ModelsStatus } from "./types";

/** Settings → Models. The key is write-only: only the last 4 characters and the date are shown. */
export function Settings() {
  const { session } = useApp();
  const [status, setStatus] = useState<ModelsStatus | null>(null);
  const [key, setKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => Api.models().then((s) => { setStatus(s); if (s.model) setModel(s.model); }).catch((e) => setMsg({ ok: false, text: String(e) }));
  useEffect(() => { if (session.kind === "admin") void refresh(); }, [session.kind]);
  if (session.kind !== "admin") return <div className="card" data-testid="settings"><h2>Settings → Models</h2><p>Admin only. Switch user to access it.</p></div>;

  const run = async (fn: () => Promise<void>) => { setBusy(true); setMsg(null); try { await fn(); } catch (e) { setMsg({ ok: false, text: String(e) }); } finally { setBusy(false); } };
  const test = () => run(async () => {
    const r = await Api.testKey(key.trim() || undefined);
    if (r.ok) { setModels(r.models); setMsg({ ok: true, text: `Valid key: ${r.models.length} models available.` }); if (!model && r.models.includes("gemini-2.5-flash")) setModel("gemini-2.5-flash"); }
    else setMsg({ ok: false, text: `Key rejected: ${r.error ?? "error"}` });
  });
  const save = () => run(async () => { const s = await Api.setKey(key.trim()); setKey(""); setStatus(s); setMsg({ ok: true, text: "Key saved (encrypted on the gateway side)." }); });
  const del = () => run(async () => { setStatus(await Api.deleteKey()); setModels([]); setMsg({ ok: true, text: "Key deleted." }); });
  const choose = () => run(async () => { await Api.selectModel(model); await refresh(); setMsg({ ok: true, text: `Model selected: ${model}.` }); });

  return (
    <div className="settings" data-testid="settings">
      <h2>Settings → Models</h2>
      <section className="card">
        <h3>Provider: Gemini</h3>
        <p data-testid="key-status">{status === null ? "…" : status.configured
          ? <>Key configured <code>…{status.last4}</code> · {status.source === "ui" ? `saved here on ${status.updatedAt ? fmtDateTime(status.updatedAt) : "?"}` : "initial value from the environment (the key saved here takes precedence)"}</>
          : "No key configured."}</p>
        <form onSubmit={(e) => e.preventDefault()}>
          <label>New API key (write-only, never shown again)
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} placeholder="Paste the key here" data-testid="key-input" /></label>
          <div className="row">
            <button type="button" onClick={test} disabled={busy || (!key.trim() && !status?.configured)} data-testid="key-test">Test</button>
            <button type="button" onClick={save} disabled={busy || key.trim().length < 8} data-testid="key-save">{status?.source === "ui" ? "Replace" : "Save"}</button>
            <button type="button" className="danger" onClick={del} disabled={busy || status?.source !== "ui"} data-testid="key-delete">Delete</button>
          </div>
        </form>
        {msg && <p className={msg.ok ? "ok-text" : "error"} data-testid="key-message">{msg.text}</p>}
      </section>
      <section className="card">
        <h3>Model</h3>
        <p className="muted">Switching an agent's model creates a new version of that agent. Here: the default model offered.</p>
        <div className="row">
          <select value={model} onChange={(e) => setModel(e.target.value)} disabled={models.length === 0 && !model} data-testid="model-select">
            {!models.includes(model) && model && <option value={model}>{model}</option>}
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button onClick={choose} disabled={busy || !model} data-testid="model-save">Use this model</button>
        </div>
        {models.length === 0 && <p className="muted">Click “Test” to load the model list.</p>}
      </section>
    </div>
  );
}
