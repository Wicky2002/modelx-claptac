import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("replay stays marked across map, evidence and navigation", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const started = await request.post("/play/scenarios/start", {
    data: { scenario: "ratnapura_ditwah_2025", speed: 60 },
  });
  expect(started.ok()).toBeTruthy();
  await page.goto("/manager/#/map");
  await expect(page.getByText("REPLAY / TRAINING", { exact: true })).toBeVisible();
  await expect(page.getByText("SIMULATED CLOCK", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Search the map" }).fill("Shelter 01");
  await page.getByRole("textbox", { name: "Search the map" }).press("Enter");
  await expect(page.locator(".map-inspector")).toContainText("synthetic");
  await expect(page.locator(".map-inspector")).toContainText("Unknown until occupancy is reported");
  const screenshots = process.env.ATLAS_SCREENSHOT_DIR;
  if (screenshots) {
    mkdirSync(screenshots, { recursive: true });
    await page.waitForTimeout(2500); // Let the selected-target camera transition finish.
    await page.screenshot({ path: `${screenshots}/u1-replay-map.png`, fullPage: true });
  }
  await request.post("/play/scenarios/stop");
  await page.reload();
  await expect(page.locator(".replay-banner")).toContainText("stopped");
  await page.goto("/manager/#/timeline");
  await expect(page.locator(".tl-feed")).toContainText("water_level");
  await page.locator(".tl-feed button").filter({ hasText: "water_level" }).first().click();
  await expect(page.locator(".tl-inspector .info-replay").first()).toBeVisible();
  if (screenshots) await page.screenshot({ path: `${screenshots}/u1-evidence.png`, fullPage: true });
  await page.goto("/manager/#/decisions");
  await expect(page.locator(".replay-banner")).toBeVisible();
  expect(errors).toEqual([]);
});
