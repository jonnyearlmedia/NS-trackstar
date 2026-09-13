import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function openTrackstar(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "Reset to Napa and Solano" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Search address, road or project/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Near me/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Filters/i }).first()).toBeVisible();
}

async function waitForProjectCoverage(page: Page) {
  await expect(page.getByText(/current mapped projects in view/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: /Browse [\d,]+ projects/i })).toBeVisible({ timeout: 30_000 });
}

test("core shell works across supported browsers", async ({ page }) => {
  await openTrackstar(page);
  await waitForProjectCoverage(page);
  await expect(page.getByRole("navigation", { name: "Trackstar sections" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Explore" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Updates" })).toBeVisible();
  await expect(page.locator(".maplibregl-canvas")).toHaveCount(1);
});

test("dense regional inventory remains browsable instead of becoming a GIS wall", async ({ page }) => {
  await openTrackstar(page);
  await waitForProjectCoverage(page);

  const browse = page.getByRole("button", { name: /Browse [\d,]+ projects/i });
  const label = await browse.innerText();
  const count = Number(label.replace(/[^0-9]/g, ""));
  expect(count).toBeGreaterThan(100);

  await browse.click();
  await expect(page.getByRole("heading", { name: "Napa + Solano" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Close project list/i })).toBeVisible();
  expect(await page.locator("ol button.contentResultRow").count()).toBeGreaterThan(50);
});

test("classified search survives normal human input and opens a real record", async ({ page }) => {
  await openTrackstar(page);
  await page.getByRole("button", { name: /Search address, road or project/i }).click();
  const input = page.getByRole("searchbox");
  await expect(input).toBeVisible();
  await input.fill("Napa Pipe");
  await expect(page.locator("button.contentResultRow").first()).toBeVisible({ timeout: 20_000 });
  await page.locator("button.contentResultRow").first().click();
  await expect(page.getByRole("button", { name: /Share project/i })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: /Details & official sources/i })).toBeVisible();
});

test("small-phone layout has no horizontal overflow and keeps core targets tappable", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("webkit"), "small-phone geometry is verified on the WebKit/iPhone project");
  await openTrackstar(page);
  await waitForProjectCoverage(page);

  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);

  const targets = [
    page.getByRole("button", { name: /Search address, road or project/i }),
    page.getByRole("button", { name: /Near me/i }),
    page.getByRole("button", { name: /Filters/i }).first(),
    page.getByRole("button", { name: "Explore" }),
    page.getByRole("button", { name: "Updates" }),
  ];
  for (const target of targets) {
    const box = await target.boundingBox();
    expect(box, "core touch target should have a box").not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(40);
    expect(box!.width).toBeGreaterThanOrEqual(40);
  }
});

test("slow backend responses keep the shell understandable and recover cleanly", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("chromium"), "network resilience only needs one browser engine");
  await page.route("**/api/backend/map/category-truth**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1800));
    await route.continue();
  });

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /Search address, road or project/i })).toBeVisible();
  await expect(page.getByText(/Loading project coverage/i)).toBeVisible();
  await waitForProjectCoverage(page);
});

test("initial consumer surface has no serious or critical accessibility violations", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("chromium"), "axe gate runs once on Chromium");
  await openTrackstar(page);
  await waitForProjectCoverage(page);

  const results = await new AxeBuilder({ page })
    .disableRules(["color-contrast"])
    .analyze();
  const blocking = results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""));
  expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join("\n")).toEqual([]);
});
