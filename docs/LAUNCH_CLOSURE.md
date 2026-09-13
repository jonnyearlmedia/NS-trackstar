# Trackstar pre-backend launch closure

This file closes the remaining v1 product-design questions that were still listed as open in the roadmap. These are launch decisions, not suggestions for another redesign cycle.

## Default map and filtering

- **Regional map:** show the mapped inventory through clusters. Do not draw the full line/polygon GIS inventory at regional or city scale.
- **City/neighborhood map:** clusters progressively separate into category pins. Project labels appear only at close local zoom.
- **Small local projects:** mapped projects remain in the marker inventory regardless of size. Clustering and label placement control clutter; a global importance score must not erase a small nearby project from an area the user explicitly chose.
- **Large distant projects:** they do not outrank nearby projects on the normal map. Geographic context wins. Significance ranking is allowed inside an explicit mode such as Briefing, and only after constraining candidates to the current viewport.
- **Planning/review records:** ordinary planning projects use the same category/lifecycle system. Raw environmental-review records are not shown as ordinary consumer projects unless the existing major-review threshold says the record is meaningful enough to represent directly.
- **Regional relevance threshold:** use relevance only for low-emphasis shape/label density, never to remove the representative marker inventory from a chosen viewport.
- **User location:** Near Me changes the camera and geographic context; it does not silently personalize project importance.
- **Noise:** raw collector discoveries, duplicate source records, technical source-health events and records without a consumer project identity never appear as standalone ordinary map projects.

## Visual map language

- Category is the persistent map legend: Development = green, Roads & transit = orange, Utilities = teal, Public places = indigo.
- No second permanent legend for lifecycle/activity. Those belong in filters, project cards and Updates.
- Recently changed projects do **not** get another always-on ring/badge. Updates and the activity filter are the explicit change-discovery modes. This avoids rebuilding visual noise after the Napa review.
- Approximate location is communicated on the project interaction/card, with lower-confidence visual treatment where already supported.
- No 3D buildings or terrain in v1. They are post-launch only if they materially improve a real user question.

## Project-card hierarchy

The first tap must answer in this order:

1. **What is this?** Human-readable official summary/description.
2. **What's happening?** Latest meaningful official activity when available; otherwise a conservative current lifecycle statement.
3. **Where/how certain?** Approximate/unmapped warning only when needed.
4. **Can I trust how current this is?** Project-specific freshness cue, with stale warning only when relevant.
5. **What are the facts and sources?** Expanded details.

Key facts are selected in a fixed consumer order: address/location, homes or units, site size, building area, developer/applicant. Unit labels are humanized. Source count is shown in expanded Official Sources, not as first-tap clutter. Location uncertainty belongs on first tap when it changes how the map should be interpreted. Source internals stay behind Details unless freshness is stale.

Multiple official status dimensions are preserved instead of forcing one misleading global status. When official systems disagree or describe different processes, Trackstar keeps the separate status/source evidence and avoids claiming false certainty.

## Search and discovery

- One unified search is the v1 interaction. Do not add project/place/road/business tabs before the query.
- Search covers project names, aliases, business names, roads, addresses, APNs, permits/cases/numbers and other project evidence.
- Typo tolerance is enabled as a fallback; exact/prefix/substring matches always outrank fuzzy matches.
- Business names are evidence that can resolve to a project; they are not a separate business directory.
- City/neighborhood terms may return projects whose names/evidence contain the place. Trackstar does not pretend to be a general geocoder in v1.
- A valid result without defensible geometry remains searchable and opens its record with **Location not mapped yet**. Trackstar never invents a pin.

## Updates and Briefing

- Updates is scoped to the current map area and meaningful public activity only.
- If no meaningful recent update exists, say so and offer current projects. Do not manufacture a news item.
- Briefing is scoped to the exact current viewport. Backend ranking is intersected with the visible/filtered project set; local fallback never jumps outside that viewport.
- A Briefing stop with no recent change is explicitly labeled **Current context**.
- A dated event in the future is labeled **Upcoming**.
- Camera choreography keeps the selected project clear of the project/briefing card and restores the prior map bounds on exit.

## Public trust

- Trackstar is a public-record organizer and summary layer, not an official government record, permit, approval or legal notice.
- Public systems can lag, disagree or publish incomplete information. Project-specific stale source messaging appears only when it affects the displayed project.
- Official source links remain available in expanded details.
- `/about` explains the model, limitations, geometry honesty and public-record lag.
- `/report` provides a project-aware wrong/outdated information workflow and asks for official evidence when available.
- Do not display internal collector/source-health diagnostics to ordinary users.

## Launch scope freeze

The following do not block the pre-backend v1 handoff: additional source expansion, 3D, terrain, historical time slider, before/after imagery, deeper analytics, perfect lifecycle normalization for ambiguous upstream language, exhaustive cadence tuning, or extra observability. They can return after the user's backend update or post-launch if they solve a real product need.
