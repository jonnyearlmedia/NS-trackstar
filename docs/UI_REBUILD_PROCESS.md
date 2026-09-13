# Trackstar UI rebuild

How the consumer UI gets fixed, and why it was not fixable before.

The executable process lives in `.claude/skills/ui-rebuild/SKILL.md` with agent
definitions in `.claude/agents/`. This document is the diagnosis behind it.

## What is actually wrong

Measured on `build/phase-0-foundation` at commit `1ffdb04`:

| metric | value |
| --- | --- |
| global stylesheets imported by `app/layout.tsx` | 11 |
| `!important` declarations | 903 |
| total CSS lines | 4,280 |
| files declaring design tokens | 4 |
| modules unreachable from any entry point | 10 (5,850 lines) |
| live component code | ~1,844 lines |

The live UI is small. The styling around it is more than twice its size and
almost entirely override.

## The mechanism

`app/layout.tsx` imports eleven global stylesheets in sequence:

```
globals → ux-polish → final-device → visual-refresh → editorial-polish →
interaction-polish → content-polish → map-hierarchy-polish →
release-ui-pass → release-state-fixes → launch-closure
```

Read those names in order and the history is plain. Each pass could not safely
edit the stylesheet that already owned a rule, so it appended a new file and
used `!important` to win. `.projectIdentity` and its children are each defined
in three separate layers. `visual-refresh.css` alone carries 223 `!important`
declarations, `release-ui-pass.css` 171, `content-polish.css` 165.

The consequence is that the outcome of any edit depends on import order rather
than intent. That is why the UI resists being fixed: there is no edit anyone can
make and predict the result of.

The same pattern shows in components. `map-explorer.tsx` through
`map-explorer-v6.tsx` and `map-canvas.tsx` through `map-canvas-v3.tsx` are all
still present and all unreachable. Only `trackstar-final.tsx` and
`map-canvas-final.tsx` actually render. Every search for a component returns
mostly dead files.

## Why the spec did not save it

`docs/VISUAL_SYSTEM_V1.md` is specific and good. It gives exact hex values, a
type scale, and touch target minimums.

Its "explicitly rejected direction" list is the tell. It rules out a near-black
shell, a lime accent, 7 to 9px consumer copy, and a map of tiny anonymous dots.
That list describes a build that existed. So the spec was written as a
correction, and then the correction was applied as another override layer
instead of as a change to the thing underneath. The spec never became the source
of truth, because four different files kept declaring tokens and they did not
agree.

Prose direction with no enforced tokens loses to 903 `!important` declarations
every time.

## The fix

`scripts/ui-debt-gate.mjs` makes the failure mode fail the build. It enforces a
one-way ratchet over the five metrics above, with the committed ceiling in
`docs/ui-debt-budget.json`:

- a metric above its ceiling fails, so no change can add a layer;
- a metric below its ceiling also fails, until you lower the ceiling with
  `node scripts/ui-debt-gate.mjs --write` and commit it, so progress cannot
  silently erode.

It runs in CI next to `pnpm typecheck`.

Then the rebuild runs in phases: delete the dead generations, consolidate tokens
into one file, flatten the eleven layers into per-surface CSS modules, and only
then change how anything looks. Phases 1 through 3 are verified by screenshot
diff as pixel-identical, so the redesign starts from a cascade that behaves the
way it reads.

Sequencing matters more than effort here. Redesigning before flattening is what
produced layers 2 through 11.

## Running it

```
node scripts/ui-debt-gate.mjs    # where things stand
```

Then invoke the `ui-rebuild` skill, which dispatches the phases. The eight-way
flatten and six-way redesign run in parallel; measure, delete, tokenize, the
shell/map pair and the final verify are serial.
