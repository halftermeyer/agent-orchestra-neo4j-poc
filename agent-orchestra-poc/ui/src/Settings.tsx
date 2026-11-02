import { useEffect, useState } from "react";
import { Api } from "./api";
import { fmtDateTime } from "./labels";
import { useApp } from "./store";
import type { ModelsStatus } from "./types";

/** Paramètres → Modèles. La clé est en écriture seule : on n'affiche que les 4 derniers caractères et la date. */
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
  if (session.kind !== "admin") return <div className="card" data-testid="settings"><h2>Paramètres → Modèles</h2><p>Réservé à l'administrateur. Changez d'utilisateur pour y accéder.</p></div>;

  const run = async (fn: () => Promise<void>) => { setBusy(true); setMsg(null); try { await fn(); } catch (e) { setMsg({ ok: false, text: String(e) }); } finally { setBusy(false); } };
  const test = () => run(async () => {
    const r = await Api.testKey(key.trim() || undefined);
    if (r.ok) { setModels(r.models); setMsg({ ok: true, text: `Clé valide : ${r.models.length} modèles disponibles.` }); if (!model && r.models.includes("gemini-2.5-flash")) setModel("gemini-2.5-flash"); }
    else setMsg({ ok: false, text: `Clé refusée : ${r.error ?? "erreur"}` });
  });
  const save = () => run(async () => { const s = await Api.setKey(key.trim()); setKey(""); setStatus(s); setMsg({ ok: true, text: "Clé enregistrée (chiffrée côté passerelle)." }); });
  const del = () => run(async () => { setStatus(await Api.deleteKey()); setModels([]); setMsg({ ok: true, text: "Clé supprimée." }); });
  const choose = () => run(async () => { await Api.selectModel(model); await refresh(); setMsg({ ok: true, text: `Modèle retenu : ${model}.` }); });

  return (
    <div className="settings" data-testid="settings">
      <h2>Paramètres → Modèles</h2>
      <section className="card">
        <h3>Fournisseur : Gemini</h3>
        <p data-testid="key-status">{status === null ? "…" : status.configured
          ? <>Clé configurée <code>…{status.last4}</code> · {status.source === "ui" ? `enregistrée ici le ${status.updatedAt ? fmtDateTime(status.updatedAt) : "?"}` : "valeur initiale de l'environnement (la clé enregistrée ici sera prioritaire)"}</>
          : "Aucune clé configurée."}</p>
        <form onSubmit={(e) => e.preventDefault()}>
          <label>Nouvelle clé API (écriture seule, jamais réaffichée)
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} placeholder="Collez la clé ici" data-testid="key-input" /></label>
          <div className="row">
            <button type="button" onClick={test} disabled={busy || (!key.trim() && !status?.configured)} data-testid="key-test">Tester</button>
            <button type="button" onClick={save} disabled={busy || key.trim().length < 8} data-testid="key-save">{status?.source === "ui" ? "Remplacer" : "Enregistrer"}</button>
            <button type="button" className="danger" onClick={del} disabled={busy || status?.source !== "ui"} data-testid="key-delete">Supprimer</button>
          </div>
        </form>
        {msg && <p className={msg.ok ? "ok-text" : "error"} data-testid="key-message">{msg.text}</p>}
      </section>
      <section className="card">
        <h3>Modèle</h3>
        <p className="muted">Changer de modèle d'un agent crée une nouvelle version de cet agent. Ici : le modèle proposé par défaut.</p>
        <div className="row">
          <select value={model} onChange={(e) => setModel(e.target.value)} disabled={models.length === 0 && !model} data-testid="model-select">
            {!models.includes(model) && model && <option value={model}>{model}</option>}
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button onClick={choose} disabled={busy || !model} data-testid="model-save">Retenir ce modèle</button>
        </div>
        {models.length === 0 && <p className="muted">Cliquez sur « Tester » pour charger la liste des modèles.</p>}
      </section>
    </div>
  );
}
