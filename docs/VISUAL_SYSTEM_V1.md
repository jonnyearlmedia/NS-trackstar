# Trackstar Visual System v1

Status: canonical visual direction for the current consumer app. This document governs visual and interaction polish unless Jonny explicitly approves a new direction.

## Direction

Trackstar combines three ideas deliberately:

1. **Clean & Modern** is the interaction foundation. The map and controls should feel clear, fast, familiar, and web/iOS-like rather than dashboard-heavy.
2. **Editorial / Magazine** supplies personality only where hierarchy benefits from it, especially Briefing and selected storytelling moments. It must not turn normal map exploration or ordinary project cards into a magazine layout.
3. **Coastal / Northern California atmosphere** supplies lightness and regional character through restrained sky blue, cool white, sage, and warm neutral accents. Do not make the product literally beach-themed.

The intended shorthand is: **Apple-like utility + local-news editorial sophistication + subtle Northern California atmosphere.**

## Explicitly rejected direction

Do not return to the previous visual system:

- no near-black default app shell;
- no radioactive lime / chartreuse primary accent;
- no Material/Android-looking tiny segmented controls;
- no 7–9px consumer-facing UI copy;
- no map dominated by tiny anonymous dots;
- no generic symbol characters standing in for a coherent icon system;
- no dense dashboard treatment just because desktop has more room;
- no pill shape applied indiscriminately to every control;
- no giant serif project titles with compressed line-height in the normal map flow.

Dark mode may be explored later as a deliberate second theme. It is not the default visual identity.

## Palette

Primary shell:

- app background: `#eef5f7`
- surface: white / near-white, usually `rgba(255,255,255,.94–.97)`
- primary text: `#17232a`
- muted text: roughly `#657780`
- primary action / selected state: `#0b67c7`
- coastal atmosphere: `#dff3fb`
- sage support: `#e7f1e9`
- warm neutral support: `#f6f1e8`

Map project categories remain differentiated but restrained:

- Development: green/sage (`#2f7f65`)
- Roads & Transit: warm orange (`#e58a2b`)
- Utilities: teal (`#238ca4`)
- Public Places: indigo (`#5d70d8`)

Category color is an aid, never the only meaning cue. The same category color must follow a project through browse controls, map marker, overlap chooser, project card, and other consumer surfaces.

## Typography

Use the system sans stack for normal UI, project cards, and reading. Reserve the system serif stack for Briefing and other explicitly editorial storytelling moments.

Consumer-facing sizing baseline:

- ordinary body/copy: generally 13–15px;
- important descriptive copy: around 15px;
- navigation/buttons/chips: generally 12–14px;
- metadata/eyebrows: generally 10–12px;
- focused mobile form inputs: at least 16px to avoid iOS Safari auto-zoom;
- normal project title: roughly 27–36px, sans, comfortable `~1.07` line-height;
- Briefing editorial headline: roughly 33–48px depending on viewport.

Avoid consumer-facing text below 10px. Small metadata should remain secondary without becoming illegible. Large headlines must still have enough line-height to scan comfortably on a phone.

## Touch and click targets

- ordinary mobile controls: target 44–48px minimum interactive height/width;
- icon-only actions: 44px square where practical;
- map project markers use an invisible interactive halo roughly 44px or larger even when the visible mark is smaller;
- do not require exact marker taps;
- overlapping project hit areas should use the existing chooser rather than silently picking one.

Hover, focus-visible, selected, disabled, loading, empty, error, and stale states must all be intentional.

## Surfaces and shape language

Prefer clear white or lightly translucent surfaces over dark glass.

- major floating sheets/cards: generally 20–26px radius;
- standard buttons/fields: generally 12–16px radius;
- icon badges: generally 10–14px radius;
- true pills are reserved for chips/tags where the pill metaphor is useful.

Use soft cool shadows. Avoid heavy black drop shadows and excessive glow.

## Icon system

Use one coherent line-icon language. Critical actions should pair icons with text when space allows.

Canonical category icons:

- Development: building
- Roads & Transit: roadway
- Utilities: energy/utility bolt
- Public Places: civic/place building
- All: target/overview

Navigation uses map/explore and updates/list icons. Briefing uses play, pause, next, and arrow controls. Do not substitute typographic glyphs such as `▦`, `↔`, `⌁`, or `◇` in the consumer UI.

Category icons must be visibly meaningful, not decorative. They use the category color system in browse controls and are embedded directly in local-scale map pins.

## Map

The map remains the product, not a backdrop for cards.

- default basemap: OpenFreeMap **Positron** for a quiet light canvas;
- regional zoom may use clusters and restrained colored overview points to avoid noise;
- city/neighborhood zoom transitions to **notification/location-pointer style category pins**, not anonymous circles;
- each local-scale pin contains the category pictogram and category color;
- closer zoom adds project names progressively while keeping the pin visible;
- selected point projects enlarge their actual category pin and receive a clear Trackstar-blue selection halo;
- clusters are white with blue outline and readable count;
- uncertain geometry remains visibly differentiated;
- coverage edge uses a restrained blue treatment;
- project names appear progressively at useful local zooms, not everywhere.

Do not visually overload the map with POIs or competing colors that diminish Trackstar project data. The user should be able to glance at a local map and understand what *kind* of activity each marker represents before opening a card.

## Explore

Normal Explore follows the Clean & Modern foundation:

- map-first;
- clear search;
- obvious Near Me / Filters utilities;
- category controls that are readable and easy to hit;
- white/coastal floating surfaces;
- category icons whose colors match the map markers;
- icon-led Explore / Updates navigation;
- large enough text and controls for a nontechnical resident.

Orientation Peek may be richer, but it should never become a permanent dashboard.

## Project sheet

Project Peek should answer the human question quickly and should feel like a calm map/product sheet, not an editorial article.

Hierarchy:

1. category icon + understandable lifecycle cue, carrying the same category color as the map pin;
2. strong **sans-serif** project name with comfortable line-height;
3. plain-language Overview copy;
4. current meaningful activity when available;
5. freshness/trust cue;
6. Details & official sources.

The ordinary project title should not use the Briefing serif treatment. Use whitespace and subtle rules for hierarchy instead of stacking multiple boxed cards. Expanded technical information uses readable cards/rows and preserves the light visual system.

## Briefing

Briefing is the main place where the Editorial direction can become more expressive.

Use:

- editorial serif headline;
- visible progress;
- category identity;
- a distinct “What changed” story block;
- clear Pause / Next / Exit controls;
- full-project action.

Briefing must be scoped to the current viewport and active filters. The backend `/area/briefing` ranking should be intersected with the current visible/filtered project set. Do not substitute a global favorite/top-project list.

## Search, Updates, Filters, and modal states

These should look like intentional product surfaces rather than raw text lists:

- content rows include category icon, readable hierarchy, and arrow affordance;
- Filter choices use category iconography and a clear selected state;
- Search is a light focused utility surface;
- loading/error/empty/freshness/outside-coverage states stay inside the same light system;
- no technical source jargon in ordinary consumer rows.

## Desktop

Desktop keeps the same mental model. It is not a separate analytics dashboard.

Use the extra width for a clean side panel / floating sheet while preserving a large map. Controls can move to desktop-appropriate locations but should not shrink below the readability/touch/click baseline merely because a mouse is available.

## PWA / installed app

Browser theme, standalone launch background, and app icon must match the light Trackstar system. Avoid a dark launch flash that contradicts the actual UI.

## QA gate

A visual pass is not accepted merely because the layout compiles. Check at minimum:

- no accidental sub-10px consumer text;
- no important action below the intended hit-target baseline;
- map projects are easy to tap;
- local zoom visibly communicates category through colored icon pins rather than tiny anonymous dots;
- category colors/icons stay consistent from browse to map to project card;
- project-card title/summary line-height remains comfortable on multi-line mobile titles;
- selection and focus states are visible;
- no old black/lime surface appears in loading, empty, error, freshness, coverage, or PWA launch states;
- Briefing follows the visible map area rather than a repeated global project;
- mobile and desktop both retain the same map-first product identity.
