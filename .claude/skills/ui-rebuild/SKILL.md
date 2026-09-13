---
name: ui-rebuild
description: Run the phased multi-agent rebuild of the Trackstar consumer UI, taking it from eleven stacked CSS override layers to one token system plus per-surface modules, then conforming it to the visual spec. Use when asked to fix, redesign, clean up or rebuild how the Trackstar web app looks.
---

# Trackstar UI rebuild

## Why the previous attempts failed

The app is not ugly because nobody tried. It is ugly because of how they tried.

Each pass could not safely edit the stylesheet that already owned a rule, so it
appended a new global layer and reached for `!important` to win the cascade.
Eleven layers and 903 `!important` declarations later, the effect of any edit
depends on import order rather than intent, so no further edit can be made with
confidence. Six abandoned generations of `map-explorer` sit alongside the live
one, so even finding the right file is a coin flip.

`docs/VISUAL_SYSTEM_V1.md` is not the problem. It is specific and it is good.
Its "explicitly rejected direction" list reads as a correction of an earlier
build, which means the spec was written and then implemented as yet another
override layer rather than as a change to the thing underneath.

So the sequencing below is not bureaucracy. Redesigning before flattening is
what produced layers 2 through 11.

## The rule that makes this different

`scripts/ui-debt-gate.mjs` enforces a one-way ratchet over five metrics, with
the committed ceiling in `docs/ui-debt-budget.json`. Adding a layer fails the
build. Paying debt down also fails the build until you lower the ceiling with
`--write` and commit it, so progress cannot silently erode.

Wire it into CI alongside `pnpm typecheck`. No phase is finished while it is
red.

Baseline at the time this process was written:

| metric | baseline | target |
| --- | --- | --- |
| global CSS layers | 11 | 1 |
| `!important` declarations | 903 | 0 |
| token source files | 4 | 1 |
| orphaned modules | 10 | 0 |
| total CSS lines | 4,280 | materially lower |

## Surfaces

Phases 3 and 4 are partitioned by surface. The partition is what makes them
parallel, and the boundaries are real because each surface already has its own
live component.

| surface | owns |
| --- | --- |
| `shell` | `trackstar-final.tsx`, `trackstar-final-chrome.tsx` |
| `map` | `map-canvas-final.tsx`, `map-final-layers.ts`, `map-final-model.ts` |
| `explore` | `trackstar-final-explore.tsx` |
| `project` | `trackstar-final-project.tsx` |
| `search` | `trackstar-final-search.tsx` |
| `updates` | `trackstar-final-updates.tsx` |
| `briefing` | `trackstar-final-briefing.tsx` |
| `modals` | `trackstar-final-modals.tsx` |

## Phases

Run `ui-qa-gate` after every mutating phase. Do not start the next phase on a
red gate; a phase built on unverified work is how a two-day cleanup becomes a
two-week one.

### Phase 0 — Measure (1 agent, serial)

`ui-auditor`. Read-only. Produces `docs/UI_DEBT_BASELINE.md`.

Cheap, and every later phase is graded against it. Do not skip it because the
table above already exists; those numbers age.

### Phase 1 — Delete (1 agent, serial)

`dead-code-remover`. Removes the ten unreachable modules, roughly 5,850 lines.

Zero visual risk by construction, since nothing imports them. Run it first
anyway, because until it lands every search in later phases can return a dead
file, and an agent reasoning about `map-explorer-v4` is wasted work.

### Phase 2 — Tokenize (1 agent, serial)

`design-tokenizer`. Collapses four token sources into `tokens.css`.

This one must be serial and must be single. Tokens are global by definition, so
two agents editing them in parallel produce exactly the conflicting duplicate
declarations this phase exists to remove.

Pure refactor. Screenshots must be identical before and after.

### Phase 3 — Flatten (8 agents, parallel)

`css-flattener`, one per surface, dispatched together.

This is where the wall-clock saving lives, and the parallelism is safe rather
than optimistic: each agent writes only its own CSS module and deletes only the
global rules it absorbed. Conflicts are confined to deletions from the eleven
shared layers, which resolve cleanly because no two agents claim the same
selector.

Pure refactor again. Per-surface screenshots must be identical before and after.

Once all eight land, the global layers should be empty enough to delete, leaving
`tokens.css` plus one small base stylesheet. Delete them and lower the budget.

### Phase 4 — Redesign (8 agents, in waves)

`visual-designer`, one per surface. This is the only phase that changes
appearance, and it is only safe now because the cascade finally does what it
looks like it does.

Run `shell` and `map` first and alone. They set the spatial and colour ground
everything else sits on, and the remaining six read those decisions rather than
guess at them. Then run the other six in parallel.

### Phase 5 — Verify (1 agent, serial)

`ui-qa-gate`, full run, plus a human look at the screenshots. A person has to
say it looks right. No gate in this repo can tell you that.

## Efficiency

Twenty-one agent runs, but only five serial steps: measure, delete, tokenize,
the shell/map pair, then the final verify. The eight-way flatten and the
six-way redesign each collapse into roughly one step of wall clock.

The real saving is not parallelism though. It is that phases 1 through 3 are
provably non-visual, so when Phase 4 changes a colour and something looks wrong,
the cause is that colour. Under the current cascade the same change could be
defeated by any of eleven layers, which is why the previous attempts kept adding
a twelfth.

## If a phase wants to break the rules

An agent will eventually propose adding a global layer or an `!important` to
ship something faster. That proposal is the failure mode itself, arriving on
schedule. The answer is no. Fix the module that owns the rule.
