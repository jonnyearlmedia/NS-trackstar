# Trackstar final UI acceptance pass

This file marks the send-ready consumer UI checkpoint. It does not add scope.

`docs/VISUAL_SYSTEM_V1.md` is the canonical visual-language contract for this release. The previous dark / neon-lime / ultra-compact styling is not an approved fallback.

The active app must satisfy these locked behaviors before merge/launch approval:

- First open frames Napa + Solano and immediately shows real project clusters/markers.
- Areas outside Trackstar coverage are visibly dimmed/masked and an outside-coverage state offers a return action.
- First-use Orientation Peek shows geographic context, mapped count, Development / Roads / Utilities / Places with counts, Browse projects, and Filters.
- Normal returning/map-interaction state is Free Explore with stable All / Development / Roads / Utilities / Places controls.
- Default Explore is current work; completed/inactive projects remain searchable/filterable without dominating the default map.
- Active stage/activity filters are visible and removable.
- Search uses the canonical classified search contract, not client-side category/stage guesses.
- Near Me requests location once, remains non-blocking if denied, and handles outside coverage honestly.
- Project selection uses canonical category/stage, plain-language summary, meaningful current activity, truthful approximate/unmapped location messaging, freshness, details, official sources, and share.
- Closing a project restores the prior map viewport and prior Browse/Updates context.
- Overlapping mapped projects use a chooser rather than silently selecting one.
- Browse does not dump a huge regional flat list.
- Updates are scoped to the current map area, grouped by project, and use the public changes feed that suppresses known noisy CivicClerk changes.
- Play Briefing remains secondary, local, explicit, and restores the pre-briefing viewport on exit.
- Play Briefing uses the viewport-scoped `/area/briefing` ranking and intersects it with the current visible/filtered project set; it must not repeatedly jump to an unrelated global project.
- Navigation remains Explore / Updates with Search available from the map.
- Desktop preserves the same map-first information architecture rather than becoming a dashboard.
- Mobile browser scaling is locked so Trackstar behaves like an app shell rather than a pinch-zoomable webpage.
- Focused mobile search controls remain at iOS-safe input sizing so Safari does not auto-zoom the interface.
- Phone UI density preserves map space without solving space pressure by shrinking consumer text or controls below the visual-system baseline.
- Ordinary mobile controls target roughly 44–48px interaction size; map points keep an invisible touch halo of roughly 44px or larger.
- Consumer-facing metadata should generally remain at least 10px and ordinary body/action text 12–15px; avoid the previous 7–9px compact UI.
- Critical categories and actions use the coherent SVG icon system rather than placeholder typographic glyphs.
- The default basemap is the light OpenFreeMap Positron style so Trackstar project data remains visually dominant.
- Napa + Solano coverage uses the detailed county-union outline with a restrained blue edge rather than the earlier coarse polygon shadow or neon glow.
- A regional viewport is labeled Napa + Solano; a single city label appears only after the viewport is genuinely local.
- Loading, empty, error, stale/freshness, coverage, search, filter, overlap, and installed-PWA launch states remain in the approved light/coastal visual system.

Anything outside this list is post-launch unless it blocks these behaviors.
