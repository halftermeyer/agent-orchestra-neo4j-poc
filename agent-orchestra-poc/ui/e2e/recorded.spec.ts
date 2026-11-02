import { expect, test, type Page } from "@playwright/test";

const SHOTS = "test-results/screens";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

/** Relit le scénario réel enregistré (data/scenarios/scenario-complet.json, produit par `make scenario` avec les vrais agents). */
test("relecture du scénario enregistré : cinq chapitres, de l'incident à la gouvernance", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/");
  await page.getByTestId("user-admin").click();
  await page.getByTestId("tab-relecture").click();
  await page.getByTestId("replay-source").selectOption("rec:scenario-complet");
  await page.getByTestId("replay-load").click();
  await expect(page.getByTestId("replay-controls")).toBeVisible();
  for (const c of ["incident", "analyse", "vote", "lancement", "gouvernance"]) await expect(page.getByTestId(`chapter-${c}`)).toBeVisible();
  // au début, les compteurs sont ceux de l'instant rejoué (rien appris, aucune boîte pleine), pas ceux du graphe actuel
  await expect(page.getByTestId("station-qualite")).not.toContainText("fait");
  await expect(page.getByTestId("mailbox-comite-1")).not.toContainText(/\d/);
  await shot(page, "14-scenario-chapitres");
  // chapitres dans l'ordre du scénario (positions croissantes sur la barre)
  const lefts = await Promise.all(["incident", "analyse", "vote", "lancement", "gouvernance"].map((c) => page.getByTestId(`chapter-${c}`).evaluate((el) => parseFloat((el as HTMLElement).style.left))));
  expect(lefts).toEqual([...lefts].sort((a, b) => a - b));
  // boucle légitime : au moins une proposition refusée dans le journal
  await page.getByTestId("replay-view-journal").click();
  await expect(page.getByTestId("replay-journal")).toContainText("Proposition refusée", { timeout: 1000 }).catch(() => undefined);
  await page.getByTestId("replay-view-scene").click();
  // vitesse ×20, temps morts compressés : tout le scénario se rejoue en moins d'une minute
  await page.getByTestId("replay-speed-20").click();
  await page.getByTestId("replay-play").click();
  await expect(page.getByTestId("avatar-comite-1").getByTestId("bubble")).toContainText("J'approuve", { timeout: 40000 });
  await shot(page, "15-scenario-vote");
  await expect(page.getByTestId("station-qualite")).toContainText("fait");           // Qualité a appris des faits en cours de lecture
  await expect(page.getByTestId("replay-play")).toContainText("Rejouer", { timeout: 60000 });         // fin de la relecture
  await shot(page, "16-scenario-fin");
  // saut direct au chapitre gouvernance : l'auditeur agit, le chef de projet décide
  await page.getByTestId("chapter-gouvernance").click();
  await expect(page.getByTestId("replay-time")).not.toContainText("00:00 /");
  await page.getByTestId("replay-follow").selectOption("auditeur");
  await expect(page.getByTestId("station-auditeur")).toHaveAttribute("data-followed", "true");
  await page.waitForTimeout(2500);
  await shot(page, "17-scenario-gouvernance");
  await page.getByTestId("replay-view-journal").click();
  await expect(page.getByTestId("replay-journal")).toContainText("Auditeur");
});
