# NS Trackstar — UX Architecture v1

Status: working implementation spec, approved enough to build. Pixel polish may change after device testing; the information architecture and interaction model should not be reinterpreted around implementation convenience.

## Product principle

Trackstar is a geographic public-record intelligence/exploration map. Its default job is not to tell everyone which projects are most important. The user defines intent by place, direct map exploration, broad category, search, lifecycle/activity filters, or an explicit intelligence mode such as Updates or Briefing.

Primary real-world jobs:

1. See a construction site and identify it.
2. Open Trackstar and casually explore what is happening in an area.
3. Browse a broad category such as development or roads.
4. Search a known address, road, project, business, neighborhood, or place.
5. Check meaningful recent/upcoming changes in a chosen area.

Importance/relevance scores may manage clutter or rank content after the user establishes context. They are not the default definition of what the user should care about.

## Personas / design gate

Every major flow must work for:

- a 12-year-old curious about something being built nearby;
- a normal nontechnical adult casually exploring;
- an older nontechnical resident who needs obvious labels, touch targets, and visible actions;
- a power user who wants filters, timelines, evidence, status, Updates, and Briefing after choosing context.

Gestures may accelerate interactions, but no essential workflow may depend on discovering a hidden gesture.

## Primary IA

- **Explore** — default, map-first mode.
- **Updates** — secondary chronological mode for meaningful changes.
- **Search** — always available from Explore/Updates.
- **Near Me** — Explore utility, not a separate destination.
- **Filters** — secondary narrowing controls.
- **Briefing** — temporary optional intelligence mode entered by explicit user request.

No default recommendation feed and no default global "top projects" surface.

## Consumer taxonomy

Primary categories describe the physical thing / user intent, not government process or ownership.

### Development
Housing, apartments, subdivisions, mixed-use, retail/commercial buildings, restaurants when represented as development projects, hotels, offices, industrial/warehouse, major redevelopment/site development.

### Roads & Transit
Road construction, paving, intersections, bridges, highways, transit infrastructure, bike/pedestrian transportation improvements, corridors.

### Utilities
Water, sewer, drainage/stormwater/flood-control, power/energy, other utility-system work when coverage supports it.

### Public Places
Parks, trails, schools, libraries, civic buildings, recreation/community facilities, other place-based public facilities where the place/facility is the main user meaning.

### Businesses & Openings
Do not expose as a first-class category until coverage can support the promise consistently.

### Not categories
Reviews/approvals, CEQA/environmental review, permits, hearings, source systems, public/private ownership, importance, nearby, changed recently, completed.

Those are process, evidence, attributes, geography, activity, ranking, or lifecycle dimensions.

### Lifecycle lens
- Planned / proposed
- Under review
- Approved / permitted
- Under construction
- Completed

Stalled/canceled/superseded remain available but should not dominate ordinary Explore.

### Activity lens
- Any time
- Changed recently
- Upcoming

Detailed history belongs in Updates and project detail.

## Explore state model

### 1. Orientation Peek

Used on first-ever launch and when the user explicitly chooses **Browse this area**.

Hierarchy:

- compact Search at top;
- map owns most of the screen;
- current geographic context name and mapped count;
- four lightweight equal category cells (icon + short label, optional small count);
- Browse projects;
- Filters;
- quiet Explore / Updates navigation.

This surface teaches what can be explored. It is not permanent chrome.

Do not show arbitrary ranked projects in this state.

Do not show a large Play Briefing CTA in this state.

### 2. Free Explore

This is the normal returning-user map state.

The map owns nearly the whole screen. Search stays at top, Near Me remains available, Explore/Updates remains available, and the richer category surface is collapsed into lightweight stable controls.

Compact category controls:

- All
- Development
- Roads
- Utilities
- Places
- Filters where space allows

**All** means a genuine free-for-all map: no category restriction. The user can simply pan, zoom, and tap mapped projects.

Category order must remain stable as the viewport changes. Zero-count categories may become visually quiet/disabled rather than disappearing/reordering.

Counts may update relative to the viewport when useful but must remain secondary.

### Orientation → Free Explore transition

The richer Orientation Peek should naturally collapse when the user begins active map exploration, such as panning/zooming, dragging the sheet down, or tapping an explicit collapse control.

Do not force the user to dismiss it repeatedly.

A visible **Browse this area** / chevron affordance must restore the richer orientation surface. Do not rely only on a swipe gesture.

Returning app sessions should generally reopen in Free Explore at the last reasonable map area, not show Orientation Peek every session.

### 3. Filtered Explore

Same map-first state, but one or more category/stage/activity filters are active.

- category selection filters the map in place;
- switching categories is one tap;
- All clears the category restriction;
- additional stage/activity filters appear as compact removable pills;
- active filters remain visible after the Filter sheet is dismissed.

No separate category page.

### 4. Browse List

Entered only by explicit user action.

List organization follows user intent instead of one hidden global importance ranking:

- broad regional scope: group geographically first (city/area);
- local scope with All: group by category or another plainly understandable local structure;
- selected category: show only matching projects;
- Near Me: distance;
- Search: query relevance;
- Updates: chronology.

Rows should stay restrained: project name, human category, understandable stage, optional small location cue. Technical provenance does not belong in ordinary list rows.

### 5. Project Peek

Tapping a marker/geometry or list row temporarily replaces browse/category chrome with the human project answer.

The map remains visible.

Peek priority:

1. project name;
2. human category + current understandable stage;
3. plain-language answer to "what is this?";
4. latest meaningful current activity if one exists;
5. Details and Share.

Do not require a "Latest" section when there is no meaningful recent activity.

Do not place source counts, confidence score, technical record types, full timeline, related projects, or six status pills in the peek.

Closing restores the exact previous viewport, category/filter state, and browse state.

If multiple projects overlap the tapped point, present a human chooser instead of silently selecting one.

### 6. Project Detail

Expanded detail progressively reveals:

- What is this?
- What's happening now?
- contextual key facts appropriate to project type;
- What's next? when actually known;
- recent activity/timeline;
- multidimensional status/history;
- official sources/provenance;
- confidence/location truth details where relevant;
- report incorrect information.

Avoid fake linear progress bars that imply every project follows one clean sequence.

Project facts are contextual: housing facts differ from road facts, utilities, public facilities, etc.

Unmapped projects found through Search open honestly with **Location not mapped yet**. Never invent geometry.

Approximate mapped locations should be clearly but calmly labeled.

### 7. Search Focus

Dedicated focused search state.

Accept ordinary user intent for project names, addresses, roads/intersections, businesses, and place names when supported.

Group results in human terms rather than backend record types.

Selection behavior:

- project → return to map, center/focus project, open peek/detail;
- place → frame that area in Explore;
- address → frame location and show nearby Trackstar records.

No-result copy must say Trackstar found no match, not claim nothing exists.

### 8. Near Me

Near Me is explicit user action. Do not request OS location permission on launch.

First explain why location is useful, then request permission.

If denied, keep the app fully usable and offer Search/browse.

If the user is outside Napa/Solano coverage, say so explicitly rather than showing "0 projects nearby".

Using Near Me should keep Free Explore active rather than force-opening the large category surface.

### 9. Filter Sheet

Ordinary-user dimensions only:

- Category
- Stage
- Activity/time

Internal source types and record-system jargon stay out of normal filter UI.

Show current result count where useful and provide an obvious Clear action.

### 10. Updates

Explicit secondary destination for meaningful chronological changes.

Updates inherits the user's geographic context where possible and makes scope visible/changeable.

The change itself is the headline. Do not make the project name the headline and bury what changed.

Prefer a Recent default over an artificially empty Today feed unless evidence shows Today is consistently useful.

Duplicate/coincident records for one project should be grouped into a human update rather than spammed as separate government-log cards.

Empty state: honestly say no meaningful changes were found and offer View current projects / change area. Do not substitute an importance feed.

### 11. Briefing

Optional temporary intelligence mode.

Do not advertise a large briefing CTA on regional first open.

Expose a compact **Brief this area** action only once there is a meaningful local context (zoomed local area, Near Me, selected city/neighborhood, etc.) or through a secondary action.

Briefing scope is:

- current viewport;
- active user filters.

Then curate 3–6 worthwhile stops using meaningful recent changes, current physical activity, significance, duplication avoidance, and geographic spread.

The user explicitly asked to be briefed, so curation is appropriate here.

Controls: pause, next, exit. Exit restores the exact prior Explore state.

No automatic narration unless explicitly enabled by the user.

## Map behavior

### First open

Frame Napa + Solano intentionally, not Northern California / the world. Visually communicate the service area.

Show known project presence immediately through progressive disclosure.

### Progressive disclosure

- regional: clusters / aggregate presence;
- city: clusters plus some individual projects;
- neighborhood: mostly individual projects;
- street/site: full geometry/markers/labels where available.

Importance/relevance may control collision and visual density. It must not become the user's assumed interest.

Avoid a cliff where one zoom level looks empty and the next shows hundreds of projects.

### Pan/zoom

Normal Explore automatically refreshes visible project context after movement settles. Do not require a permanent Search this area button for basic map inventory.

### Free Explore

Map manipulation should collapse the Orientation Peek to compact Free Explore when appropriate. Project selection temporarily replaces the compact category strip with Project Peek.

### Coverage edge

Panning outside coverage shows a small understandable message and an easy return action; it must not look like an empty but supported region.

## Screen-space hierarchy

Persistent prime space earns a high bar.

Deserves persistent space:

- Search
- Map
- Near Me/location control
- compact current-context / Free Explore controls
- quiet Explore/Updates navigation

Does not deserve large persistent default space:

- Play Briefing
- ranked top-project recommendations
- heat/tilt controls
- source health
- technical status detail
- long onboarding copy
- giant category cards

Specialized map modes may live under Map options if they solve a real task; otherwise remove them.

## Back / restoration rules

Back/close reverses one interaction layer at a time and restores exact state.

Examples:

- Project Detail → Project Peek
- Project Peek → previous Free Explore / Browse List state
- Search → previous Explore state
- Filter sheet → previous Explore state with filters applied
- Briefing → exact pre-briefing map state
- shared project link → close to map centered on that project, not an arbitrary regional reset

Do not reset the map unless the user explicitly asks.

## Empty/error states

Distinguish the cause and provide the correct next action:

- no mapped projects in viewport;
- zero results due to active filters;
- Search no match;
- location denied;
- outside coverage;
- offline/load failure;
- stale source affecting displayed information;
- uncertain/approximate project location.

Never overstate certainty.

## Accessibility baseline

- large touch targets;
- readable labels;
- icon + text for critical controls;
- no color-only meaning;
- gestures never required for essential actions;
- plain language;
- list/search alternatives to pure map interaction;
- text zoom should not destroy essential controls.

## Desktop

Preserve the same mental model. Do not invent a dashboard product just because there is more room.

Use a collapsible/persistent side panel for orientation/list/detail while the map stays visible. Collapsed state may mirror mobile Free Explore with compact controls over the map.

## Implementation order

1. Explore state machine + category/filter behavior.
2. First-open framing + map density/progressive disclosure.
3. Project Peek + exact restoration/back behavior.
4. Browse list + Search + Near Me + edge states.
5. Updates scope/copy/empty-state cleanup.
6. Viewport-scoped Briefing + compact entry.
7. Desktop adaptation.
8. Final visual/accessibility/device QA.

## Validation journeys

After each implementation slice, test:

1. **Identify a site** — user sees construction, opens Trackstar, finds/taps it, understands it quickly.
2. **Casual exploration** — open app, pan/zoom, tap projects without being forced through a feed.
3. **Category browse** — choose Roads/Development/etc., browse and switch/clear naturally.
4. **What changed?** — choose area, open Updates, understand meaningful recent/upcoming changes.

A slice is not done just because the code works; it must survive these journeys across the four personas.