# Verified UI findings, 2026-09-13

Everything here came from screenshotting the running app against the live
backend and looking at the images, not from reading source. Reproduce with:

```
NEXT_PUBLIC_API_BASE_URL=<backend> pnpm --filter @ns-trackstar/web start
node apps/web/scripts/ui-screenshots.mjs --out /tmp/shots
```

## Why this document exists

`docs/MASTER_SPEC.md` and the Notion roadmap marked the consumer UX complete on
the strength of green CI. The release suite asserted that `.maplibregl-canvas`
exists, which stays true when the map never loads and no project data is ever
fetched. So the suite was green while first open was broken.

Treat "CI passed" as evidence about the code paths CI actually exercises, and
nothing more. The roadmap's own rule already says this: do not mark something
done merely because code exists.

## Fixed and verified

- **First open never loaded project data.** The map rendered, then made zero
  calls to `/api/backend/map`. Coverage stayed on "Loading project coverage…"
  indefinitely with no markers and no counts. One manual pan fired all four
  calls. `refresh()` returned early while the style was still settling and
  nothing rescheduled it. Fixed, plus a test that asserts real coverage with no
  interaction.
- Cluster counts sat on the bubble's lower edge; the text offset was a fixed em
  while icon size steps with `point_count`.
- The category pill row overflowed 144px at phone width with the scrollbar
  hidden, leaving Public Places off-screen and unhinted.
- Project peek was capped below its own content height with overflow clipped, so
  body copy was sliced mid-glyph and "Details & official sources" was
  unreachable on a phone.
- Regional dots drew three of four categories in lighter variants than the pins,
  so a project changed colour as you zoomed in.
- Greys failing WCAG AA at ~3.8:1; the empty-Updates action at 24px tall.

## Open, and mostly not frontend problems

These are data and content-truth issues. Adding sources makes each one worse,
not better, so they belong in the source-expansion work rather than after it.

### 1. `last_activity_at` is collector time, not project time

`/api/backend/map/projects` returned `last_activity_at: 2026-09-12T15:28Z` for
Napa Pipe while the project's newest real event is 7 May 2021. The field tracks
when the collector ran, so every project looks like it changed today.

This blocks any honest recency surface: "updated N ago" on a browse row, sorting
by recent activity, and the Updates feed's own premise. It was deliberately left
unused in list rows rather than shipping a false freshness claim on every
project.

**Constraint for new sources:** separate "when we observed it" from "when the
thing happened", and let the second be null. A source that cannot supply a real
event date should produce no date rather than its own fetch time.

### 2. "What is this?" leads with whatever text the source happened to carry

For Napa Pipe the first-tap explanation reads, in full:

> This major amendment includes changes to the project description, such as a
> reduced bridge width and length, reduced bridge abutment dimensions, and an
> increase in riparian habitat restoration from 6,100 square feet to 10,508
> square feet.

That is a CEQA notice-of-amendment abstract. It never says what Napa Pipe is, and
a reader comes away thinking the project is a bridge. The locked rule is that
first tap leads with a plain-language human explanation.

**Constraint for new sources:** more sources means more candidate summaries per
project, so summary selection becomes a ranking problem. Decide explicitly which
evidence types may become the consumer explanation, and prefer a description of
the project over a description of the latest filing about it.

### 3. "Details & official sources" shows crawler telemetry, not facts

The expanded state's only new section is SOURCE FRESHNESS: three rows of
"Checked 11 hrs ago". Address, homes/units, site size, building area and
developer/applicant appear nowhere, though the spec orders them explicitly.

For the flagship project in the region, a resident cannot learn the unit count.

**Constraint for new sources:** the value of more sources is more extracted
facts, not more freshness rows. Each new source should state which consumer key
facts it can populate; if it populates none, it adds provenance only, and the
detail view should not grow another freshness row for it.

### 4. Lifecycle is largely unknown, and "Status unclear" is the loudest thing on the card

`lifecycle_stage` came back null for every project sampled from
`/api/backend/map/projects`, and the card renders "Status unclear" in heavier,
darker type than the category it sits under. Keeping unknown as unknown is
correct. Making it the most prominent element is not.

**Constraint for new sources:** classification coverage per source is worth
measuring before adding more. A source that raises project count without raising
lifecycle coverage makes the map emptier of meaning.

### 5. A 2021 event sits under a present-tense heading beside a freshness line

The peek shows WHAT'S HAPPENING, then "New environmental review document filed",
then "May 7, 2021", then "Official source checks current · oldest 18 hrs ago".
Nothing marks the event as old. Read together, those lines imply recent activity
on a four-year-old filing.

### 6. Map attribution collides with the sheet on every screen

"OpenFreeMap © OpenMapTiles Data from OpenStreetMap" is sliced by the bottom
sheet on phone and fully covered by the panel on desktop. This is a licensing
obligation, not a nicety.

## Still-true structural debt

`app/layout.tsx` stacks eleven global stylesheets with 903 `!important`
declarations. Three separate layers declared the project card's max-height with
`!important`; only the last applied, so two edits to the others changed nothing.
Ten modules, roughly 5,850 lines, are unreachable from any entry point.

`scripts/ui-debt-gate.mjs` holds the line. `.claude/skills/ui-rebuild/SKILL.md`
is the phased way out.
