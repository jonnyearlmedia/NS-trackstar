#!/usr/bin/env node
/**
 * Capture real screenshots of every Trackstar surface.
 *
 * This exists because the roadmap marked the entire UI done on the strength of
 * green CI, and green CI says nothing about whether a screen looks right. Every
 * visual claim in this project has to come from one of these images.
 *
 * Usage:
 *   node scripts/ui-screenshots.mjs [--out DIR] [--only NAME] [--url URL]
 *
 * Requires a server already running at --url (default http://127.0.0.1:3000):
 *   NEXT_PUBLIC_API_BASE_URL=<backend> pnpm --filter @ns-trackstar/web start
 */

import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { chromium, webkit, devices } from "@playwright/test";

const args = process.argv.slice(2);
const argOf = (flag, fallback) => {
  const i = args.indexOf(flag);
  return i === -1 ? fallback : args[i + 1];
};

const OUT = argOf("--out", "/tmp/claude-0/shots");
const ONLY = argOf("--only", null);
const BASE = argOf("--url", "http://127.0.0.1:3000");

/**
 * Bridge external requests through Node.
 *
 * In some sandboxes the browser process has no outbound network while Node
 * does. Without this the basemap cannot load at all, and every screenshot shows
 * Trackstar's own "Map could not load" state rather than the product. That
 * makes visual review impossible and, worse, invites a fake bug report about
 * the map being broken when the real cause is the harness.
 *
 * Only same-origin app traffic is left alone; everything else is fetched by
 * Node and handed back verbatim.
 */
async function bridgeExternalNetwork(context) {
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = request.url();
    if (url.startsWith(BASE) || url.startsWith("data:") || url.startsWith("blob:")) {
      return route.continue();
    }
    try {
      const headers = { ...request.headers() };
      // Node sets these itself; forwarding the browser's copies corrupts the body.
      delete headers.host;
      delete headers["accept-encoding"];
      const response = await fetch(url, {
        method: request.method(),
        headers,
        body: ["GET", "HEAD"].includes(request.method()) ? undefined : request.postDataBuffer(),
        redirect: "follow",
      });
      const body = Buffer.from(await response.arrayBuffer());
      const out = {};
      response.headers.forEach((value, key) => {
        // fetch already decoded the payload, so these would misdescribe it.
        if (!["content-encoding", "content-length"].includes(key.toLowerCase())) out[key] = value;
      });
      out["access-control-allow-origin"] = "*";
      await route.fulfill({ status: response.status, headers: out, body });
    } catch {
      await route.abort();
    }
  });
}

/** Wait for the map to actually paint, not merely for the DOM to exist. */
async function settle(page, { map = true } = {}) {
  await page
    .getByRole("button", { name: /Search address, road or project/i })
    .waitFor({ state: "visible", timeout: 30_000 });
  if (map) {
    await page.locator(".maplibregl-canvas").first().waitFor({ state: "visible", timeout: 30_000 });
    // Coverage text is the app's own signal that project data has landed.
    await page
      .getByText(/current mapped projects in view/i)
      .waitFor({ state: "visible", timeout: 30_000 })
      .catch(() => {});
  }
  await page.waitForTimeout(3500); // tile raster + marker settle
}

const shot = (page, name) =>
  page.screenshot({ path: join(OUT, `${name}.png`), fullPage: false });

/**
 * Each scene is one reviewable state from the locked UX checklist.
 * Scenes are deliberately tolerant: a scene that cannot reach its state still
 * captures what it got, because a screenshot of the wrong screen is itself a
 * finding. Never let a scene silently report success.
 */
const scenes = {
  "first-open": async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
  },

  "browse-list": async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.getByRole("button", { name: /Browse [\d,]+ projects/i }).first().click();
    await page.waitForTimeout(2000);
  },

  "search-results": async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.getByRole("button", { name: /Search address, road or project/i }).click();
    await page.getByRole("searchbox").fill("Napa Pipe");
    await page.locator("button.contentResultRow").first().waitFor({ timeout: 25_000 });
    await page.waitForTimeout(1200);
  },

  "project-peek": async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.getByRole("button", { name: /Search address, road or project/i }).click();
    await page.getByRole("searchbox").fill("Napa Pipe");
    await page.locator("button.contentResultRow").first().waitFor({ timeout: 25_000 });
    await page.locator("button.contentResultRow").first().click();
    await page.getByRole("button", { name: /Share project/i }).waitFor({ timeout: 25_000 });
    await page.waitForTimeout(1800);
  },

  "project-detail": async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.getByRole("button", { name: /Search address, road or project/i }).click();
    await page.getByRole("searchbox").fill("Napa Pipe");
    await page.locator("button.contentResultRow").first().waitFor({ timeout: 25_000 });
    await page.locator("button.contentResultRow").first().click();
    await page.getByRole("button", { name: /Details & official sources/i }).click();
    await page.waitForTimeout(2000);
  },

  filters: async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.getByRole("button", { name: /Filters/i }).first().click();
    await page.waitForTimeout(1500);
  },

  updates: async (page) => {
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.getByRole("button", { name: "Updates" }).click();
    await page.waitForTimeout(3000);
  },

  "map-zoomed": async (page) => {
    // City zoom is where category pins and labels are supposed to appear.
    await page.goto(`${BASE}/?lng=-122.2869&lat=38.2975&zoom=13`, { waitUntil: "domcontentloaded" });
    await settle(page);
    const canvas = await page.locator(".maplibregl-canvas").first().boundingBox();
    if (canvas) {
      await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2);
      for (let i = 0; i < 4; i += 1) {
        await page.mouse.wheel(0, -260);
        await page.waitForTimeout(900);
      }
    }
    await page.waitForTimeout(3500);
  },
};

async function run() {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });

  const names = ONLY ? [ONLY] : Object.keys(scenes);
  const results = [];

  // Prefer real WebKit for the phone pass, since that is what iPhone users get.
  // Fall back to Chromium at iPhone geometry when WebKit is not installed: layout,
  // colour and spacing review still holds, engine-specific rendering does not.
  let phoneBrowser = webkit;
  try {
    const probe = await webkit.launch();
    await probe.close();
  } catch {
    console.warn("WebKit unavailable, using Chromium at iPhone 13 geometry for the phone pass.\n");
    phoneBrowser = chromium;
  }

  const viewports = [
    { tag: "phone", browserType: phoneBrowser, opts: devices["iPhone 13"] },
    { tag: "desktop", browserType: chromium, opts: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ];

  for (const { tag, browserType, opts } of viewports) {
    const browser = await browserType.launch();
    const context = await browser.newContext({ ...opts, serviceWorkers: "block" });
    await bridgeExternalNetwork(context);
    for (const name of names) {
      const page = await context.newPage();
      const errors = [];
      page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
      page.on("pageerror", (e) => errors.push(String(e)));
      try {
        await scenes[name](page);
        await shot(page, `${tag}-${name}`);
        results.push({ scene: `${tag}-${name}`, ok: true, errors });
      } catch (error) {
        // Capture whatever is on screen; a failed scene is a finding, not a crash.
        await shot(page, `${tag}-${name}-FAILED`).catch(() => {});
        results.push({ scene: `${tag}-${name}`, ok: false, why: String(error).split("\n")[0], errors });
      }
      await page.close();
    }
    await context.close();
    await browser.close();
  }

  console.log(`\nScreenshots in ${OUT}\n`);
  for (const r of results) {
    console.log(`  ${r.ok ? "ok  " : "FAIL"}  ${r.scene}${r.ok ? "" : `  ${r.why}`}`);
    for (const e of [...new Set(r.errors)].slice(0, 3)) console.log(`          console: ${e.slice(0, 160)}`);
  }
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed}/${results.length} scenes captured\n`);
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
