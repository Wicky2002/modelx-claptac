import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

const screenshots = process.env.ATLAS_SCREENSHOT_DIR;
async function shot(page: import("@playwright/test").Page, name: string) {
  if (screenshots) {
    mkdirSync(screenshots, { recursive: true });
    const viewport = page.viewportSize()!;
    const height = await page.locator(".main > .page").evaluate(el => el.scrollHeight);
    await page.setViewportSize({ width: viewport.width, height: Math.max(viewport.height, Math.min(3200, height + 150)) });
    await page.locator(".main > .page").evaluate(el => { el.scrollTop = 0; });
    await page.screenshot({ path: `${screenshots}/${name}.png`, fullPage: true });
    await page.setViewportSize(viewport);
  }
}

test("dataset exploration labels samples, preserves denominators and keeps history", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto("/manager/#/data");
  await expect(page.getByText("Recorded data only.", { exact: false })).toBeVisible();
  await expect(page.getByText("No dataset cards or profiling reports available.", { exact: false })).toBeVisible();
  await shot(page, "data-recorded-empty");
  await page.getByLabel("Show illustrative sample data").check();
  await expect(page.getByText("SAMPLE DATA", { exact: true })).toBeVisible();
  await expect(page.getByText("3.00%", { exact: false })).toBeVisible();
  await expect(page.getByRole("cell", { name: "2,500", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Flood-model evaluation" })).toBeVisible();
  await shot(page, "data-flood-sample");
  await page.getByRole("combobox", { name: "Dataset", exact: true }).selectOption("disaster-news");
  await expect(page.getByRole("heading", { name: "Label distribution" })).toBeVisible();
  await shot(page, "data-labels-sample");
  await page.getByRole("combobox", { name: "Dataset", exact: true }).selectOption("mawiongrim");
  await expect(page.getByRole("heading", { name: "Rain and soil moisture" })).toBeVisible();
  await expect(page.getByText("units not supplied", { exact: false }).first()).toBeVisible();
  await shot(page, "data-soil-sample");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await shot(page, "data-mobile-sample");
  await page.getByRole("button", { name: "Hazard history", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Hazard history/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("model review is read-only with explicit sample and unavailable states", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto("/manager/#/model-review");
  await expect(page.getByText("Model registry unavailable.", { exact: false })).toBeVisible();
  await shot(page, "models-recorded-empty");
  const before = await (await request.get("/dev/model-review")).json();
  await page.getByLabel("Show illustrative sample data").check();
  await expect(page.getByText("SAMPLE DATA", { exact: true })).toBeVisible();
  await expect(page.getByText("Review suggested", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Shadow results" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "0.07", exact: true })).toBeVisible();
  await shot(page, "models-sample");
  await page.getByRole("combobox", { name: "Version", exact: true }).selectOption("sample-v3");
  await expect(page.getByRole("cell", { name: "0.69", exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await shot(page, "models-mobile-sample");
  const after = await (await request.get("/dev/model-review")).json();
  expect(after.models).toEqual(before.models);
  expect(after.history).toEqual(before.history);
  await page.route("**/dev/model-review?sample=false", route => route.fulfill({ status: 503, body: "temporarily unavailable" }));
  await page.getByLabel("Show illustrative sample data").uncheck();
  await expect(page.getByRole("alert")).toContainText("Refresh failed");
  await expect(page.getByText("sample-v3", { exact: true })).toHaveCount(0);
  await expect(page.getByText("SAMPLE DATA", { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("recorded profiles and reports render missing and zero measurements honestly", async ({ page, request }) => {
  const fixture = await (await request.get("/dev/data-exploration?sample=true")).json();
  fixture.mode = "recorded";
  fixture.profiles[0].dataset_version = null;
  fixture.profiles[0].seed = null;
  fixture.profiles[0].flood_pixels = { flood: 0, non_flood: 0, ignored: 10 };
  fixture.evaluations[0].variants[0].metrics.iou = null;
  fixture.evaluations[0].variants[0].metrics.f1 = 0;
  await page.route("**/dev/data-exploration?sample=false", route => route.fulfill({ json: fixture }));
  await page.goto("/manager/#/data");
  await expect(page.getByText("No valid pixels recorded; a percentage cannot be calculated.")).toBeVisible();
  await expect(page.locator(".review-provenance").first()).toContainText("Version Not recorded");
  await expect(page.locator(".review-provenance").first()).toContainText("Seed Not recorded");
  const baseline = page.getByRole("row").filter({ has: page.getByRole("cell", { name: "baseline", exact: true }) });
  await expect(baseline.getByRole("cell").nth(1)).toHaveText("Not recorded");
  await expect(baseline.getByRole("cell").nth(2)).toHaveText("0");
  await page.route("**/dev/data-exploration?sample=false", route => route.fulfill({ status: 503, body: "offline" }));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Showing the last loaded snapshot");
  await expect(baseline).toBeVisible();
});
