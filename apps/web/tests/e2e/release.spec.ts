import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

for (const label of ["shell"] as const) {
  test(`${label} renders core Trackstar controls`, async ({ page }, testInfo) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("button", { name: "Reset to Napa and Solano" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Search address, road or project/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Near me/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Filters/i }).first()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Trackstar sections" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Explore" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Updates" })).toBeVisible();
    if (!testInfo.project.name.includes("firefox")) {
      await expect(page.locator(".maplibregl-canvas")).toHaveCount(1);
    }
  });
}

/**
 * The canvas element exists even when the map never loads and no project data
 * is ever requested, so asserting it alone let a completely broken first open
 * ship green. These assertions are the ones that actually fail in that case.
 */
test("first open reaches a ready map and real project coverage with no interaction", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes("firefox"), "map readiness is verified on engines with headless WebGL");
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator('[data-map-state="ready"]')).toBeAttached({ timeout: 30_000 });
  await expect(page.getByText("Map could not load")).toHaveCount(0);

  // Deliberately no pan, zoom, tap or filter change before this assertion.
  // Trackstar previously dropped its only startup data load when the style was
  // still settling, leaving first open stuck on "Loading project coverage…"
  // until the user happened to move the map.
  await expect(page.getByText(/current mapped projects in view/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Loading project coverage/i)).toHaveCount(0);

  const browse = page.getByRole("button", { name: /Browse [\d,]+ projects/i });
  await expect(browse).toBeVisible({ timeout: 30_000 });
  const count = Number((await browse.innerText()).replace(/[^0-9]/g, ""));
  expect(count, "first open must prove real regional inventory exists").toBeGreaterThan(100);
});

test("small-phone layout has no horizontal overflow and keeps core targets tappable", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("webkit"), "mobile gate runs on iPhone/WebKit");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);

  for (const target of [
    page.getByRole("button", { name: /Search address, road or project/i }),
    page.getByRole("button", { name: /Near me/i }),
    page.getByRole("button", { name: /Filters/i }).first(),
    page.getByRole("button", { name: "Explore" }),
    page.getByRole("button", { name: "Updates" }),
  ]) {
    const box = await target.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(40);
    expect(box!.width).toBeGreaterThanOrEqual(40);
  }
});

test("initial shell has no serious or critical structural accessibility violations", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes("chromium"), "axe gate runs once on Chromium");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /Search address, road or project/i })).toBeVisible();
  const results = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
  const blocking = results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""));
  expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join("\n")).toEqual([]);
});
