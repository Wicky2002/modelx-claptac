import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("incident, route, shelter and evidence stay on the map", async ({ page, request }) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await request.post("/play/scenarios/stop");
  expect((await request.post("/play/scenarios/start", { data: { scenario: "flood", speed: 60 } })).ok()).toBeTruthy();
  // A previous browser case may leave mission tickets behind. Wait for this
  // scenario's observations, not merely for any existing route.
  await expect.poll(async () => (await (await request.get("/play/scenarios/status")).json()).state).toBe("finished");
  await expect.poll(async () => (await (await request.get("/dev/map")).json()).routes.length).toBeGreaterThan(0);
  await request.post("/play/scenarios/stop");
  await page.goto("/manager/#/overview");
  await expect(page.locator(".replay-banner")).toBeVisible();
  const shellStyle = () => page.locator(".nav, .brand, .brand small, .replay-banner").evaluateAll(els => els.map(el => {
    const style = getComputedStyle(el);
    return { width: el.getBoundingClientRect().width, background: style.backgroundColor, color: style.color, font: style.fontSize, display: style.display };
  }));
  const originalShell = await shellStyle();
  await page.locator(".nav a").filter({ hasText: "Map" }).click();
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-projection", "globe");
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-scale", "globe");
  expect(await shellStyle()).toEqual(originalShell);
  await expect(page.locator(".nav")).toHaveCSS("width", "224px");
  const screenshots = process.env.ATLAS_SCREENSHOT_DIR;
  if (screenshots) { mkdirSync(screenshots, { recursive: true }); await page.waitForTimeout(3500); await page.screenshot({ path: `${screenshots}/u2-globe.png` }); }
  // Orbit the actual globe, then return to the operating area in the same renderer.
  const telemetry = await page.locator(".map-telemetry").textContent();
  const box = (await page.locator(".scene-canvas").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 70);
  await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 + 100, box.y + box.height / 2 + 90, { steps: 12 }); await page.mouse.up();
  await expect(page.locator(".map-telemetry")).not.toHaveText(telemetry!);
  await page.getByRole("button", { name: "Zoom to ratnapura", exact: true }).click();
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-scale", "local");
  await expect(page.locator(".marker-shelter").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Flood extent", exact: true })).toBeDisabled();
  for (const name of ["Road uncertainty", "Mission routes", "Shelter occupancy", "Sensors"]) {
    const control = page.getByRole("button", { name, exact: true });
    await control.click(); await expect(control).toHaveAttribute("aria-pressed", "false");
    if (name === "Shelter occupancy") await expect(page.locator(".marker-shelter").first()).toBeHidden();
    await control.click(); await expect(control).toHaveAttribute("aria-pressed", "true");
  }
  await page.locator(".command-left").evaluate(el => el.scrollTop = 0);
  if (screenshots) { mkdirSync(screenshots, { recursive: true }); await page.waitForTimeout(1500); await page.screenshot({ path: `${screenshots}/u2-command-map.png` }); }
  await expect(page.getByRole("button", { name: "Satellite", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "◇ Tilt terrain", exact: true }).click();
  await expect(page.getByRole("button", { name: "◈ 3D terrain", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-pitch", "50");
  if (screenshots) { await expect(page.locator(".scene-canvas")).toHaveAttribute("data-loaded", "true", { timeout: 20000 }); await page.screenshot({ path: `${screenshots}/u2-terrain.png` }); }
  await page.getByRole("button", { name: "◎ Globe", exact: true }).click();
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-scale", "globe");
  await expect(page.getByRole("button", { name: "◇ Tilt terrain", exact: true })).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".map-telemetry")).toContainText("ZOOM 1.8");
  await page.getByRole("button", { name: "↗ Share", exact: true }).click();
  await page.reload();
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-scale", "globe");
  // Shared globe coordinates must not be clamped back to city zoom.
  await expect(page.locator(".map-telemetry")).toContainText("ZOOM 1.8");
  await page.getByRole("button", { name: "Open ratnapura on the map", exact: true }).click();
  await expect(page.locator(".scene-canvas")).toHaveAttribute("data-scale", "local");
  await page.locator(".roster-group").filter({ has: page.getByRole("heading", { name: /Incidents & areas/ }) }).getByRole("button").filter({ hasText: "Ratnapura riverside settlements" }).click();
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
  await page.route(/server\.arcgisonline\.com/, route => route.abort());
  await page.reload();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Zoom to ratnapura", exact: true }).click();
  await expect(page.locator(".marker-shelter").first()).toBeVisible();
  await expect(page.locator(".nearby-roster")).toContainText("Roads");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 430, height: 932 });
  await page.getByRole("button", { name: "Nearby & details", exact: true }).click();
  await expect(page.locator(".command-right")).toBeVisible();
  expect(await page.locator(".command-right").evaluate(el => el.clientHeight)).toBeGreaterThan(200);
  await expect(page.locator(".nav a").filter({ hasText: "Overview" })).toBeVisible();
  await expect(page.locator(".nearby-roster")).toContainText("Shelters");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  if (screenshots) await page.screenshot({ path: `${screenshots}/u2-mobile-offline.png` });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.locator(".nav a").filter({ hasText: "Overview" }).click();
  await expect(page.locator(".command-map")).toHaveCount(0);
  expect(await shellStyle()).toEqual(originalShell);
  expect(errors).toEqual([]);
});
