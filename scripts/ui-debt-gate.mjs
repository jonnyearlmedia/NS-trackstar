#!/usr/bin/env node
/**
 * UI debt ratchet.
 *
 * The Trackstar UI got into its current state because nothing ever stopped a
 * pass from appending one more override layer. Each round added a stylesheet
 * instead of editing the one that already owned the rule, so the cascade turned
 * into an `!important` fight that nobody could reason about.
 *
 * This gate exists so that can never happen again. It measures the debt, and
 * compares it against a committed budget:
 *
 *   - metric ABOVE budget  -> fail. You added debt. Fix it.
 *   - metric BELOW budget  -> fail, and print the new budget to commit.
 *     Paying debt down is only real once the floor moves with it.
 *   - metric EQUAL budget  -> pass.
 *
 * Run: node scripts/ui-debt-gate.mjs [--write]
 *   --write updates the budget file for you after a genuine improvement.
 */

import { readFileSync, writeFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative, dirname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const webSrc = join(repoRoot, "apps/web/src");
const layoutPath = join(webSrc, "app/layout.tsx");
const budgetPath = join(repoRoot, "docs/ui-debt-budget.json");

function walk(dir, exts) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full, exts));
    else if (exts.some((e) => entry.endsWith(e))) out.push(full);
  }
  return out;
}

const lines = (file) => readFileSync(file, "utf8").split("\n").length;

/** Global stylesheets side-effect imported by the root layout. */
function globalCssLayers() {
  const source = readFileSync(layoutPath, "utf8");
  return [...source.matchAll(/^\s*import\s+"(\.\/[^"]+\.css)"/gm)].map((m) => m[1]);
}

/** Every project stylesheet, global layers and CSS modules alike. */
function allStylesheets() {
  return walk(webSrc, [".css"]);
}

/** Files that declare custom properties. One source of truth is the goal. */
function tokenSources(sheets) {
  return sheets.filter((f) => /^\s*--[a-z][\w-]*\s*:/m.test(readFileSync(f, "utf8")));
}

function importantCount(sheets) {
  return sheets.reduce(
    (total, f) => total + (readFileSync(f, "utf8").match(/!important/g) ?? []).length,
    0,
  );
}

/**
 * Modules unreachable from any Next.js entry point. Abandoned `-v2`/`-v3`
 * component generations are the signature of a pass that rewrote instead of
 * replacing, and they make every later search return the wrong file.
 */
function orphanModules() {
  const entryNames = new Set([
    "page.tsx", "layout.tsx", "route.ts", "manifest.ts",
    "template.tsx", "error.tsx", "loading.tsx", "not-found.tsx",
  ]);
  const roots = walk(join(webSrc, "app"), [".tsx", ".ts"]).filter((f) =>
    entryNames.has(f.split("/").pop()),
  );

  const resolve = (spec, from) => {
    const base = spec.startsWith("@/")
      ? join(webSrc, spec.slice(2))
      : normalize(join(dirname(from), spec));
    for (const ext of [".tsx", ".ts", ".css", "/index.tsx", "/index.ts", ""]) {
      const candidate = base + ext;
      if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
    }
    return null;
  };

  const live = new Set();
  const stack = [...roots];
  while (stack.length) {
    const file = stack.pop();
    if (!file || live.has(file)) continue;
    live.add(file);
    const source = readFileSync(file, "utf8");
    const specs = [
      ...[...source.matchAll(/from\s+"((?:@\/|\.)[^"]+)"/g)].map((m) => m[1]),
      ...[...source.matchAll(/^\s*import\s+"(\.[^"]+)"/gm)].map((m) => m[1]),
    ];
    for (const spec of specs) {
      const target = resolve(spec, file);
      if (target && !live.has(target)) stack.push(target);
    }
  }

  return walk(webSrc, [".tsx", ".ts", ".css"])
    .filter((f) => !live.has(f))
    .map((f) => relative(repoRoot, f))
    .sort();
}

const sheets = allStylesheets();
const layers = globalCssLayers();
const orphans = orphanModules();

const actual = {
  globalCssLayers: layers.length,
  importantDeclarations: importantCount(sheets),
  tokenSourceFiles: tokenSources(sheets).length,
  orphanedModules: orphans.length,
  totalCssLines: sheets.reduce((total, f) => total + lines(f), 0),
};

const budget = JSON.parse(readFileSync(budgetPath, "utf8"));
const limits = budget.limits;

// Lower is better for every metric, so the budget is a ceiling that ratchets down.
const regressions = [];
const improvements = [];
for (const [metric, value] of Object.entries(actual)) {
  const limit = limits[metric];
  if (limit === undefined) continue;
  if (value > limit) regressions.push({ metric, value, limit });
  else if (value < limit) improvements.push({ metric, value, limit });
}

const pad = (s) => String(s).padEnd(24);
console.log("\nUI debt gate\n");
for (const [metric, value] of Object.entries(actual)) {
  const limit = limits[metric];
  const mark = value > limit ? "FAIL" : value < limit ? "DOWN" : "ok  ";
  console.log(`  ${mark}  ${pad(metric)} ${String(value).padStart(5)}  (budget ${limit})`);
}

if (regressions.length) {
  console.error("\nBudget exceeded. This is the failure mode that produced the current UI:");
  for (const { metric, value, limit } of regressions) {
    console.error(`  ${metric}: ${value} > ${limit}`);
  }
  if (actual.globalCssLayers > limits.globalCssLayers) {
    console.error("\n  Global layers imported by app/layout.tsx:");
    for (const layer of layers) console.error(`    ${layer}`);
    console.error("  Edit the stylesheet that already owns the rule. Do not add a new one.");
  }
  if (orphans.length > limits.orphanedModules) {
    console.error("\n  Unreachable modules:");
    for (const file of orphans) console.error(`    ${file}`);
    console.error("  Replace components in place. Do not leave a -v2 behind.");
  }
  process.exit(1);
}

if (improvements.length) {
  const next = { ...budget, limits: { ...limits } };
  for (const { metric, value } of improvements) next.limits[metric] = value;

  if (process.argv.includes("--write")) {
    writeFileSync(budgetPath, `${JSON.stringify(next, null, 2)}\n`);
    console.log(`\nDebt paid down. Budget lowered in ${relative(repoRoot, budgetPath)}. Commit it.`);
    process.exit(0);
  }

  console.error("\nDebt went down. Lower the budget so it cannot creep back:");
  for (const { metric, value, limit } of improvements) {
    console.error(`  ${metric}: ${limit} -> ${value}`);
  }
  console.error("\n  node scripts/ui-debt-gate.mjs --write\n");
  process.exit(1);
}

console.log("\nAll metrics at budget.\n");
