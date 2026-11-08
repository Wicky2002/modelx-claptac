import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("incident, route, shelter and evidence stay on the map", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await request.post("/play/scenarios/stop");
  expect((await request.post("/play/scenarios/start", { data: { scenario: "flood", speed: 60 } })).ok()).toBeTruthy();
  // A previous browser case may leave mission tickets behind. Wait for this
  // scenario's observations, not merely for any existing route.
  await expect.poll(async () => (await (await request.get("/play/scenarios/status")).json()).state).toBe("finished");
  await expect.poll(async () => (await (await request.get("/dev/map")).json()).routes.length).toBeGreaterThan(0);
  await request.post("/play/scenarios/stop");
  await page.goto("/manager/#/map");
  await expect(page.locator(".marker-shelter").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Flood extent", exact: true })).toBeDisabled();
  for (const name of ["Road uncertainty", "Mission routes", "Shelter occupancy", "Sensors"]) {
    const control = page.getByRole("button", { name, exact: true });
    await control.click(); await expect(control).toHaveAttribute("aria-pressed", "false");
    if (name === "Shelter occupancy") await expect(page.locator(".marker-shelter").first()).toBeHidden();
    await control.click(); await expect(control).toHaveAttribute("aria-pressed", "true");
  }
  const screenshots = process.env.ATLAS_SCREENSHOT_DIR;
  await page.locator(".command-left").evaluate(el => el.scrollTop = 0);
  if (screenshots) { mkdirSync(screenshots, { recursive: true }); await page.waitForTimeout(1500); await page.screenshot({ path: `${screenshots}/u2-command-map.png` }); }
  await page.locator(".roster-group").filter({ has: page.getByRole("heading", { name: /Incidents & areas/ }) }).getByRole("button").first().click();
  await expect(page.locator(".map-inspector")).toContainText("Response routes");
  await page.locator(".map-inspector .detail-link").first().click();
  await expect(page.locator(".map-inspector")).toContainText("Team acknowledgement");
  await page.getByRole("button", { name: /Inspect Shelter/ }).click();
  await expect(page.locator(".map-inspector")).toContainText("reported occupancy / synthetic capacity");
  await page.locator(".map-evidence").getByRole("button").first().click();
  await expect(page.getByRole("region", { name: "Observation evidence" })).toContainText("Source");
  expect(page.url()).toContain("#/map");
  if (screenshots) await page.screenshot({ path: `${screenshots}/u2-shelter-evidence.png` });
  await page.getByRole("button", { name: "Proximity roster" }).click();
  await expect(page.locator(".roster-anchor")).toContainText("Shelter");
  // A lost tile service must not remove the operational picture or the keyboard roster.
  await page.route(/tiles\.openfreemap\.org/, route => route.abort());
  await page.reload();
  await expect(page.locator(".marker-shelter").first()).toBeVisible();
  await expect(page.locator(".nearby-roster")).toContainText("Roads");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 430, height: 932 });
  await page.getByRole("button", { name: "Nearby & details", exact: true }).click();
  await expect(page.locator(".command-right")).toBeVisible();
  await expect(page.getByRole("link", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.locator(".nearby-roster")).toContainText("Shelters");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  if (screenshots) await page.screenshot({ path: `${screenshots}/u2-mobile-offline.png` });
  expect(errors).toEqual([]);
});
