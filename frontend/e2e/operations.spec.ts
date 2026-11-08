import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("operator can audit sources, incidents, previews and field acknowledgements", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await request.post("/play/scenarios/stop");
  expect((await request.post("/play/scenarios/start", { data: { scenario: "flood", speed: 60 } })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get("/play/scenarios/status")).json()).state).toBe("finished");
  const screenshots = process.env.ATLAS_SCREENSHOT_DIR;
  if (screenshots) mkdirSync(screenshots, { recursive: true });
  await page.goto("/manager/#/overview");
  const sources = page.getByRole("region", { name: "Source health", exact: true });
  await expect(sources).toContainText("sensor:");
  for (const name of ["Observation time", "Arrival time", "Last successful refresh", "Source age"]) await expect(sources.getByRole("columnheader", { name, exact: true })).toBeVisible();
  await expect(sources).toContainText("Not recorded");
  if (screenshots) await page.screenshot({ path: `${screenshots}/u3-source-health.png` });
  const refreshed = await sources.locator(".audit-section-head").textContent();
  await page.route("**/dev/sources", route => route.abort());
  await expect(sources.getByRole("alert")).toContainText("Source updates unavailable", { timeout: 10000 });
  await expect(sources).toContainText("sensor:");
  expect(await sources.locator(".audit-section-head").textContent()).toBe(refreshed);
  await page.unroute("**/dev/sources");

  await page.getByRole("link", { name: "Incidents", exact: true }).click();
  await expect(page.getByRole("region", { name: "What changed", exact: true })).toContainText("incident commander proposes");
  await expect(page.getByRole("region", { name: "Why approval is needed", exact: true })).toContainText("Proposed");
  await expect(page.getByRole("region", { name: "Route alternatives", exact: true })).toContainText("Passes model threshold");
  await expect(page.getByRole("region", { name: "Shortages and response gaps", exact: true })).toContainText("synthetic reference data");
  await expect(page.getByRole("region", { name: "Conflicting reports", exact: true })).toContainText("water level");
  if (screenshots) await page.screenshot({ path: `${screenshots}/u3-incident-assessment.png` });
  await page.getByRole("region", { name: "Shortages and response gaps", exact: true }).scrollIntoViewIfNeeded();
  if (screenshots) await page.screenshot({ path: `${screenshots}/u3-response-gaps.png` });

  const alertsBefore = (await (await request.get("/alerts")).json()).length;
  await page.getByRole("link", { name: "Decisions", exact: true }).click();
  const preview = page.getByRole("region", { name: "Communication preview", exact: true }).first();
  await expect(preview).toContainText("Estimated expiry");
  for (const lang of ["si", "ta", "en"]) await expect(preview.locator(`article[lang=${lang}] .preview-instruction`)).toBeVisible();
  await expect(preview).toContainText("Proposed · not sent");
  expect((await (await request.get("/alerts")).json()).length).toBe(alertsBefore);
  await preview.scrollIntoViewIfNeeded();
  if (screenshots) await page.screenshot({ path: `${screenshots}/u3-communication-preview.png` });

  await page.getByRole("link", { name: "Teams & missions", exact: true }).click();
  await page.locator(".mission-ticket-button").filter({ hasText: "No acknowledgement recorded" }).first().click();
  const ticket = page.getByRole("region", { name: "Field mission ticket", exact: true });
  await expect(ticket.getByRole("button", { name: "Record progress", exact: true })).toBeDisabled();
  await ticket.getByLabel("Reporter / callsign").fill("QA replay / Rescue 02");
  await ticket.getByRole("button", { name: "Record team acknowledgement", exact: true }).click();
  await expect(ticket.getByRole("table")).toContainText("QA replay / Rescue 02");
  await ticket.getByLabel("Reported progress (%)").fill("35");
  await ticket.getByLabel("Field note").fill("Training report: first pickup complete");
  await ticket.getByRole("button", { name: "Record progress", exact: true }).click();
  await expect(ticket.getByRole("table")).toContainText("Training report: first pickup complete");
  if (screenshots) {
    await ticket.getByRole("table").scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${screenshots}/u3-field-ticket.png` });
  }
  await page.setViewportSize({ width: 430, height: 932 });
  await ticket.getByLabel("Reporter / callsign").scrollIntoViewIfNeeded();
  await expect(ticket.getByLabel("Reporter / callsign")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  if (screenshots) await page.screenshot({ path: `${screenshots}/u3-mobile-ticket.png` });
  expect(errors).toEqual([]);
});
