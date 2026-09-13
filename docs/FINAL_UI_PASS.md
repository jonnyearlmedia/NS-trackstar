# Trackstar final UI acceptance pass

This file marks the send-ready consumer UI checkpoint. It does not add scope.

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
- Navigation remains Explore / Updates with Search available from the map.
- Desktop preserves the same map-first information architecture rather than becoming a dashboard.
- Mobile browser scaling is locked so Trackstar behaves like an app shell rather than a pinch-zoomable webpage.
- Focused mobile search controls remain at iOS-safe input sizing so Safari does not auto-zoom the interface.
- Phone UI density preserves map space instead of scaling desktop-sized controls across the screen.
- Napa + Solano coverage uses the detailed county-union outline with a feathered edge rather than the earlier coarse polygon shadow.
- A regional viewport is labeled Napa + Solano; a single city label appears only after the viewport is genuinely local.

Anything outside this list is post-launch unless it blocks these behaviors.
