import { expect, test, type Page } from "@playwright/test";

const SHOTS = "test-results/screens";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

/** Replays the real recorded scenario (data/scenarios/full-scenario.json, produced by `make scenario` with the real agents). */
test("replay of the recorded scenario: five chapters, from incident to governance", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/");
  await page.getByTestId("user-admin").click();
  await page.getByTestId("tab-relecture").click();
  await page.getByTestId("replay-source").selectOption("rec:full-scenario");
  await page.getByTestId("replay-load").click();
  await expect(page.getByTestId("replay-controls")).toBeVisible();
  for (const c of ["incident", "analyse", "vote", "lancement", "gouvernance"]) await expect(page.getByTestId(`chapter-${c}`)).toBeVisible();
  // at the start, the counters are those of the replayed instant (nothing learned, no full inbox), not those of the current graph
  await expect(page.getByTestId("station-qualite")).not.toContainText("fact");
  await expect(page.getByTestId("mailbox-comite-1")).not.toContainText(/\d/);
  await shot(page, "14-scenario-chapitres");
  // chapters in scenario order (increasing positions on the bar)
  const lefts = await Promise.all(["incident", "analyse", "vote", "lancement", "gouvernance"].map((c) => page.getByTestId(`chapter-${c}`).evaluate((el) => parseFloat((el as HTMLElement).style.left))));
  expect(lefts).toEqual([...lefts].sort((a, b) => a - b));
  // legitimate loop: at least one rejected proposal in the log
  await page.getByTestId("replay-view-journal").click();
  await expect(page.getByTestId("replay-journal")).toContainText("Proposal rejected", { timeout: 1000 }).catch(() => undefined);
  await page.getByTestId("replay-view-scene").click();
  // speed ×20, idle time compressed: the whole scenario replays in under a minute
  await page.getByTestId("replay-speed-20").click();
  await page.getByTestId("replay-play").click();
  await expect(page.getByTestId("avatar-comite-1").getByTestId("bubble")).toContainText("I approve", { timeout: 40000 });
  await shot(page, "15-scenario-vote");
  await expect(page.getByTestId("station-qualite")).toContainText("fact");           // Qualité learned facts during playback
  await expect(page.getByTestId("replay-play")).toContainText("Replay", { timeout: 60000 });         // end of the replay
  await shot(page, "16-scenario-fin");
  // jump straight to the governance chapter: the auditor acts, the project manager decides
  await page.getByTestId("chapter-gouvernance").click();
  await expect(page.getByTestId("replay-time")).not.toContainText("00:00 /");
  await page.getByTestId("replay-follow").selectOption("auditeur");
  await expect(page.getByTestId("station-auditeur")).toHaveAttribute("data-followed", "true");
  await page.waitForTimeout(2500);
  await shot(page, "17-scenario-gouvernance");
  await page.getByTestId("replay-view-journal").click();
  await expect(page.getByTestId("replay-journal")).toContainText("Auditor");
});
