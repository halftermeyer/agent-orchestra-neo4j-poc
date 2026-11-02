import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const SHOTS = "test-results/screens";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
const pick = async (page: Page, id: string) => { await page.goto("/"); await page.evaluate(() => sessionStorage.clear()); await page.goto("/"); await page.getByTestId(`user-${id}`).click(); };

test.describe.configure({ mode: "serial" });

// historique du flux vide au départ : sinon les réveils d'une exécution précédente se superposent aux attentes
const BASE = process.env.UI_URL ?? "http://localhost:15173";
async function adminApi<T>(path: string, body?: unknown): Promise<T> {
  const login = await (await fetch(`${BASE}/api/demo/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ userId: "admin" }) })).json();
  const r = await fetch(`${BASE}/api${path}`, { method: body === undefined ? "GET" : "POST", headers: { "content-type": "application/json", authorization: `Bearer ${login.token}` }, body: body === undefined ? undefined : JSON.stringify(body) });
  return r.json() as Promise<T>;
}
let runId = "";

test.beforeAll(async () => {
  execSync("docker compose --profile app restart cdc", { cwd: "..", stdio: "ignore" });
  for (let i = 0; i < 40; i++) {
    try { if ((await fetch("http://localhost:18001/health")).ok) return; } catch { /* démarrage */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("le consommateur CDC ne redémarre pas");
});

// la relecture lira tout ce que les tests précédents auront produit : on ouvre un enregistrement avant eux
test.beforeAll(async () => { runId = (await adminApi<{ id: string }>("/replay/runs", { name: "Enregistrement e2e", note: "tests de navigateur" })).id; });

test("choix de l'utilisateur de démonstration, flux connecté", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("login")).toBeVisible();
  for (const id of ["ing-qualite", "comite-1", "comite-2", "comite-3", "chef-projet", "admin"]) await expect(page.getByTestId(`user-${id}`)).toBeVisible();
  await shot(page, "01-login");
  await page.getByTestId("user-ing-qualite").click();
  await expect(page.getByTestId("who")).toHaveText("Ingénieur qualité");
  await expect(page.getByTestId("live")).toHaveText("Flux connecté");
  await expect(page.getByTestId("chat")).toBeVisible();
  await expect(page.getByTestId("incident-panel")).toBeVisible();
});

test("l'ingénieur qualité déclare un incident : chat, scène animée, frise", async ({ page }) => {
  await pick(page, "ing-qualite");
  await expect(page.getByTestId("live")).toHaveText("Flux connecté");
  await page.getByTestId("tab-scene").click();
  await expect(page.getByTestId("scene")).toBeVisible();
  // les 13 postes existent ; l'auditeur est exclu de l'attente « au repos » : sa routine cron le réveille chaque minute
  for (const id of ["coordinateur", "qualite", "ingenierie", "essais", "planification", "pont-kg", "interpreteur-bom", "ing-qualite", "comite-1", "comite-2", "comite-3", "chef-projet"])
    await expect(page.getByTestId(`avatar-${id}`)).toHaveAttribute("data-state", "idle");
  await expect(page.getByTestId("avatar-auditeur")).toBeVisible();
  await shot(page, "02-scene-repos");
  await page.getByTestId("tab-chat").click();
  await page.getByTestId("publish-incident").click();
  await expect(page.getByTestId("message").first()).toContainText("Défaillance prématurée");
  await expect(page.getByTestId("message").first()).toContainText("Incident");
  await page.getByTestId("tab-scene").click();
  // l'agent Qualité est réveillé (sursaut), sa boîte clignote, une enveloppe vole
  await expect(page.getByTestId("avatar-qualite")).toHaveAttribute("data-state", "woken", { timeout: 8000 });
  await shot(page, "03-scene-reveil");
  await expect(page.getByTestId("mailbox-qualite")).toBeVisible();
  await page.getByTestId("tab-frise").click();
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("mark-routine").first()).toBeVisible();
  await expect(page.getByTestId("mark-routine-next").first()).toBeVisible();
  await shot(page, "04-frise");
});

test("graphe NVL : topologie, flux, droits (chemin surligné), KG", async ({ page }) => {
  await pick(page, "chef-projet");
  await page.getByTestId("tab-graphe").click();
  const nvl = page.getByTestId("nvl");
  await expect(nvl).toBeVisible();
  expect(Number(await nvl.getAttribute("data-nodes"))).toBeGreaterThanOrEqual(13 + 3 + 2);   // 13 agents/humains + topics + KG
  await expect(nvl.locator("canvas").first()).toBeVisible();
  await page.waitForTimeout(2500);
  await shot(page, "05-graphe-topologie");
  await page.getByTestId("mode-flux").click();
  await page.waitForTimeout(1500);
  await shot(page, "06-graphe-flux");
  await page.getByTestId("mode-droits").click();
  await page.getByTestId("rights-agent").selectOption("coordinateur");
  await expect.poll(() => page.getByTestId("memory-path").count()).toBeGreaterThanOrEqual(4);   // soi-même + subordonnés
  await page.getByTestId("memory-path").nth(2).click();
  await page.waitForTimeout(2500);
  await shot(page, "07-graphe-droits");
  await page.getByTestId("mode-kg").click();
  await expect(page.getByTestId("kg")).toBeVisible();
  await expect.poll(async () => Number(await page.getByTestId("nvl").getAttribute("data-nodes"))).toBeGreaterThan(3);
  await page.waitForTimeout(2500);
  await shot(page, "08-graphe-kg");
});

test("le chef de projet voit le KG Projet, l'ingénieur qualité non (droits CAN_QUERY)", async ({ page }) => {
  await pick(page, "ing-qualite");
  await page.getByTestId("tab-graphe").click();
  await page.getByTestId("mode-kg").click();
  await page.getByTestId("kg-select").selectOption("projet");
  await page.getByRole("button", { name: "Explorer" }).click();
  await expect(page.locator(".error")).toContainText("403");
});

test("le comité vote jusqu'au quorum ; l'avatar affiche le vote", async ({ page }) => {
  const id = execSync("docker compose --profile app exec -T cdc python scripts/demo_approval.py", { cwd: "..", encoding: "utf8" }).trim();
  expect(id).toMatch(/^[0-9a-f]{32}$/);
  await pick(page, "comite-1");
  await expect(page.getByTestId("approval")).toHaveCount(1);
  await expect(page.getByTestId("approval")).toContainText("PRT-0045");
  await expect(page.getByTestId("approval")).toContainText("0/2 voix");
  await shot(page, "09-chat-validation");
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("approvals")).toHaveCount(0);                    // déjà voté : plus listée
  await page.getByTestId("tab-scene").click();
  await expect(page.getByTestId("avatar-comite-1")).toHaveAttribute("data-state", "thinking", { timeout: 8000 });
  await expect(page.getByTestId("avatar-comite-1").getByTestId("bubble")).toContainText("J'approuve");
  await shot(page, "10-scene-vote");
  await page.getByTestId("logout").click();
  await page.getByTestId("user-comite-2").click();
  await expect(page.getByTestId("approval")).toContainText("1/2 voix");
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("approvals")).toHaveCount(0);
  await page.getByTestId("logout").click();
  await page.getByTestId("user-comite-3").click();
  await page.waitForTimeout(800);
  await expect(page.getByTestId("approvals")).toHaveCount(0);                    // quorum atteint : plus de demande en attente
});

test("relecture : le même flux reconstruit depuis le graphe, avec chapitres, vitesse, barre de temps et suivi", async ({ page }) => {
  await adminApi(`/replay/runs/${runId}/end`, {});
  await pick(page, "admin");
  await page.getByTestId("tab-relecture").click();
  await page.getByTestId("replay-source").selectOption({ label: "Enregistrement · Enregistrement e2e" });
  await page.getByTestId("replay-load").click();
  await expect(page.getByTestId("replay-controls")).toBeVisible();
  await expect(page.getByTestId("replay-title")).toContainText("Enregistrement e2e");
  // chapitres repérés dans le flux : l'incident publié et la demande de validation du comité
  await expect(page.getByTestId("chapter-incident")).toBeVisible();
  await expect(page.getByTestId("chapter-vote")).toBeVisible();
  await expect(page.getByTestId("replay-time")).toContainText("00:00 /");
  for (const id of ["qualite", "comite-1", "coordinateur"]) await expect(page.getByTestId(`avatar-${id}`)).toHaveAttribute("data-state", "idle");
  // vitesses ×1 à ×20
  for (const sp of [1, 2, 5, 10, 20]) { await page.getByTestId(`replay-speed-${sp}`).click(); await expect(page.getByTestId(`replay-speed-${sp}`)).toHaveClass(/on/); }
  // lecture à ×2 (l'enregistrement ne dure que ~20 s) : Qualité est réveillée comme en direct
  await page.getByTestId("replay-speed-2").click();
  await page.getByTestId("replay-play").click();
  await expect(page.getByTestId("avatar-qualite")).toHaveAttribute("data-state", "woken", { timeout: 15000 });
  await shot(page, "12-relecture-lecture");
  // pause : le temps ne bouge plus
  await page.getByTestId("replay-play").click();
  const t1 = await page.getByTestId("replay-time").innerText();
  await page.waitForTimeout(700);
  expect(await page.getByTestId("replay-time").innerText()).toBe(t1);
  // barre de temps : retour au début = tout le monde au repos ; positionner plus loin recalcule l'état
  const setSlider = (frac: number) => page.getByTestId("replay-slider").evaluate((el: HTMLInputElement, f: number) => {
    const v = Number(el.min) + (Number(el.max) - Number(el.min)) * f;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(el, String(v));   // contourne le suivi de valeur de React
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, frac);
  await setSlider(0);
  await expect(page.getByTestId("replay-time")).toContainText("00:00 /");
  await expect(page.getByTestId("avatar-qualite")).toHaveAttribute("data-state", "idle");
  // suivi d'un agent : anneau sur son poste, les autres s'estompent
  await page.getByTestId("replay-follow").selectOption("qualite");
  await expect(page.getByTestId("scene")).toHaveAttribute("data-follow", "qualite");
  await expect(page.getByTestId("station-qualite")).toHaveAttribute("data-followed", "true");
  await expect(page.getByTestId("station-essais")).toHaveAttribute("data-followed", "false");
  await page.getByTestId("replay-follow").selectOption("");
  // chapitre « Vote du comité » : on saute à la demande de validation puis le vote du premier membre s'affiche
  await page.getByTestId("chapter-vote").click();
  await expect(page.getByTestId("avatar-comite-1").getByTestId("bubble")).toContainText("J'approuve", { timeout: 20000 });
  await expect(page.getByTestId("replay-time")).not.toContainText("00:00 /");
  await shot(page, "13-relecture-chapitre-vote");
  // le journal garde la même description que le direct
  await page.getByTestId("replay-view-journal").click();
  await expect(page.getByTestId("replay-journal")).toContainText("Membre du comité 1 approuve");
  // le graphe lit les mêmes événements
  await page.getByTestId("replay-view-graphe").click();
  await expect(page.getByTestId("nvl")).toBeVisible();
});

/** Valeur réelle de la clé Gemini de l'environnement (jamais affichée : seuls des booléens sortent des assertions). */
const realKey = (): string | null => {
  if (!existsSync("../.env")) return null;
  const m = readFileSync("../.env", "utf8").match(/^GEMINI_API_KEY=(.+)$/m);
  return m ? m[1].trim() : null;
};

test("Paramètres → Modèles : clé en écriture seule, jamais réaffichée", async ({ page }) => {
  const key = realKey();
  const seen: string[] = [];
  page.on("response", async (r) => { if (r.url().includes("/api/settings")) seen.push(await r.text().catch(() => "")); });
  await pick(page, "admin");
  await page.getByTestId("tab-parametres").click();
  const status = page.getByTestId("key-status");
  await expect(status).toContainText("Clé configurée");
  const last4 = (await status.locator("code").innerText()).replace("…", "");
  expect(last4).toHaveLength(4);
  await expect(page.getByTestId("key-input")).toHaveValue("");
  await expect(page.getByTestId("key-input")).toHaveAttribute("type", "password");
  await page.getByTestId("key-test").click();                                    // teste la clé enregistrée (environnement)
  await expect(page.getByTestId("key-message")).toContainText("Clé valide", { timeout: 20000 });
  expect(await page.getByTestId("model-select").locator("option").count()).toBeGreaterThan(10);
  await page.getByTestId("model-select").selectOption("gemini-2.5-flash");
  await shot(page, "11-parametres");
  // une clé invalide est refusée par le fournisseur et n'est pas enregistrée
  await page.getByTestId("key-input").fill("cle-invalide-pour-test-1234");
  await page.getByTestId("key-test").click();
  await expect(page.getByTestId("key-message")).toContainText("Clé refusée", { timeout: 20000 });
  await expect(page.getByTestId("key-status")).toContainText(last4);
  await expect(page.getByTestId("key-status")).toContainText("environnement");
  // la clé réellement configurée n'est ni dans le DOM, ni dans les stockages du navigateur, ni dans les réponses de la passerelle
  if (key) {
    expect((await page.content()).includes(key)).toBe(false);
    const stores = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }]));
    expect(stores.includes(key)).toBe(false);
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.some((t) => t.includes(key))).toBe(false);
  }
  // un non-administrateur n'a pas accès
  await page.getByTestId("logout").click();
  await page.getByTestId("user-chef-projet").click();
  await page.getByTestId("tab-parametres").click();
  await expect(page.getByTestId("settings")).toContainText("Réservé à l'administrateur");
});
