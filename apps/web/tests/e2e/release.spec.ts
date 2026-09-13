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
