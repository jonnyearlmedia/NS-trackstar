# Coverage roadmap

Real residents of these fourteen jurisdictions will open this app. Someone in
Calistoga will open it and find out whether Trackstar knows anything about
Calistoga. That is the bar, and this document fixes it in place so it stops
moving.

## The standard, which does not change

A jurisdiction is **done** when all six of these exist as production sources that
have returned records against live data:

1. **Development and planning.** What is proposed, under review and approved.
2. **Permits.** What is actually being built, including tenant improvements.
3. **Meetings.** What is about to be decided, with agendas.
4. **CIP and construction.** Public works: roads, water, parks, facilities.
5. **Spatial truth.** Parcels, addresses, boundaries. Done in all fourteen.
6. **CEQA.** Statewide clearinghouse. Done in all fourteen.

Three more apply wherever the jurisdiction produces them, and are not optional
just because they are harder:

7. **Business openings.** Licences, tenant improvements, ABC, health permits.
8. **Procurement.** Bids and awards, the earliest signal that work starts soon.
9. **Transportation.** State projects, live traffic, work zones.

"The city is small" is not an exemption. Yountville has roughly 3,000 people and
a handful of live projects; covering it properly is a small job, not an excused
one. A resident there gets the same answer quality as one in Vallejo.

## Where each jurisdiction stands

Legend: `OK` production and verified · `--` not built · `XX` blocked, reason below

```
                        dev  permit  meet   cip   gis  ceqa  biz  proc
Napa                    OK     OK     OK    OK    OK    OK   OK    --
American Canyon         OK     XX     OK    OK    OK    OK   OK    --
Napa County (uninc)     OK     OK     OK    OK    OK    OK   OK    --
Yountville              --     --     OK    --    OK    OK   OK    --
St. Helena              OK     --     OK    --    OK    OK   OK    --
Calistoga               OK     --     OK    ~~    OK    OK   OK    --
Vallejo                 OK     OK     OK    --    OK    OK   OK    OK
Benicia                 OK     XX     OK    OK    OK    OK   OK    --
Fairfield               ~~     --     OK    OK    OK    OK   OK    --
Suisun City             OK     --     OK    --    OK    OK   OK    --
Vacaville               --     --     OK    --    OK    OK   OK    --
Dixon                   --     XX     OK    OK    OK    OK   OK    --
Rio Vista               --     --     OK    --    OK    OK   OK    --
Solano County (uninc)   OK     OK     OK    OK    OK    OK   OK    --
```

`~~` Fairfield development is one project-specific record set, not an inventory.
Calistoga CIP is private construction with traffic impact, not the city's own
capital programme, which is published as a fiscal-year PDF schedule.

Derived totals, September 13, 2026: **63 strong, 44 partial, 3 blocked,
30 missing** across 14 jurisdictions x 10 categories. These are computed from the
evidence in `config/coverage/napa-solano.json`, not typed in, so a source that
stops returning records takes the number down with it.

## Named targets, not categories

Verified reachable and unbuilt, so no excuse exists:

- **St. Helena permits and CIP.** Meetings and development are now built. The
  city publishes finaled permits as a page per year rather than a feed, and no
  CIP page has been found yet.
- **Every one of the fourteen now has a meeting feed.** Fairfield was the last,
  and it closed the same way the other hard ones did: the platform is a host of
  its own, `pub-fairfield.escribemeetings.com`, while the city's website still
  answers 403. Its NovusAGENDA portal was a migrated-away tenant, not a broken
  request: sent correctly the search is genuinely empty, though 2019 agendas
  still resolve by id. None of them was found by guessing a hostname. Napa County is on
  Legistar (`napa.legistar.com`, client `napa`); Suisun City on Granicus
  (`suisuncityca.granicus.com`, view 1); American Canyon on Granicus
  (`americancanyon.granicus.com`, views 16 and 18); St. Helena on CivicClerk
  (tenant `STHELENACA`); Vacaville on eScribe's public portal
  (`pub-vacaville.escribemeetings.com`); Yountville on PrimeGov
  (`townofyountville.primegov.com`); Calistoga on CivicWeb
  (`calistoga.civicweb.net`).

  Three of those were found despite the city's own website being unreachable from
  this container, which is the point worth keeping: a meeting platform is a
  separate host from the city site, and "the city site is blocked" was never a
  reason to record the city as uncovered. American Canyon is the other lesson: its
  tenant hostname sat in an iframe `src`, so a link sweep that only reads `href`
  reports "no meeting platform" about a city that has had one for years.

- **Seven jurisdictions have no CIP source.** Fairfield and unincorporated Napa
  County were closed by reading each agency's own ArcGIS organisation rather than
  its website: Fairfield publishes 87 capital projects with budget, phase, funding
  and a written status outlook, and the county publishes 24 road and facility
  construction projects. Both were reachable while both agencies' websites were
  not. Check the agency's GIS org before calling a CIP unreachable.
- **Thirteen have no procurement source.** Vallejo is done and it broke the
  category open: 239 bids with stage, due date, NAICS codes, address, contact and a
  written scope. The entry this replaces said PlanetBids "serves its own index page
  in place of every asset and API path ... so its real request contract cannot be
  read here", which was a true observation and a wrong conclusion. The app host
  answers unknown paths with the app; the API is a different host entirely, and the
  portal publishes its name in a runtime config file it serves to every visitor.
  When a single-page app appears to have no API, read the config it ships before
  concluding it cannot be read.

  American Canyon and Suisun City remain blocked on OpenGov Procurement, and that
  one was retested from an ordinary residential network on the same day ABC was
  reclassified: it does not move. `cf-mitigated: challenge` comes back for a
  self-identifying client and a browser user agent alike, so this challenge is a
  property of the site rather than of our egress, and it is settled rather than
  something to retry from yet another network. Calistoga and Yountville publish bids
  as prose on their own pages, reachable but carrying no per-bid structure. Ten
  remain unexamined, and the Vallejo result says to check each one for a vendor
  portal before assuming a city publishes nothing structured.

Blocked, with the specific reason:

- **Vacaville city site** — `www.cityofvacaville.gov` answers a challenged 403.
  Its meetings are covered through eScribe; development, permits and CIP are not.

  Yountville and Calistoga were on this list and should not have been. They were
  recorded as unreachable on the strength of `www.yountville.gov` and
  `www.ci.calistoga.ca.us`, neither of which is the city's current domain.
  `www.townofyountville.com` and `www.calistogaca.gov` both answer 200 from this
  same container. Calistoga's development coverage was built as soon as that was
  checked. Before recording a jurisdiction as unreachable, confirm the hostname is
  the one the city actually uses.
- **Napa County and Solano County Accela** are done, and the entry that had been
  sitting here was wrong in an instructive way. No browser bootstrap was needed.
  ACA answers a rejected postback with HTTP 200 and a redirect to its own error
  page, so a refusal was read as an ordinary page and written down as "the
  unchanged search surface". The portal had been stating the problem in that page
  the whole time: the POST was missing the `Referer` and `Origin` headers that any
  same-origin form post carries. When a source says zero rows, read the page it
  actually returned before writing down why.
- **Dixon permits (Tyler Civic Access)** — no longer waiting on a capture; the
  capture was done and answered the question. Dixon has anonymous public record
  search switched off. The portal's own route guard answers `isEnable: false` for
  `/public-records`, `/search` and `/records`, and the legacy EnerGov search route
  is retired for this tenant, which is why six guessed payloads all returned 500.
  There was never a payload that would have worked. Re-checking costs one request
  to the route guard if the city turns it back on.
- **American Canyon and Benicia OpenGov** — storefronts answer 200, record
  retrieval never verified anonymously.
- **Business openings** is no longer on this list. It was never an adapter
  problem. Run from an ordinary residential network rather than a datacentre,
  `www.abc.ca.gov` answers normally and the existing collector returned 171
  service-area records at parser yield 1.0 in a seven-day window. The lesson is
  worth more than the source: "blocked" had been recorded about a site, when the
  evidence only ever supported recording it about a network. Re-test a Cloudflare
  or Akamai block from somewhere else before believing it.
- **Fairfield and Rio Vista city sites** — challenged 403. Retest from another
  network before concluding anything.
- **511 live traffic** — collectors written and tested, never run with a key. The
  collector container could not even receive the key until this session; that is
  fixed, so one run settles it.

## Order of work

1. Everything reachable from wherever you are, before anything blocked. The
   meeting sweep and St. Helena are finished for every jurisdiction this container
   can reach.
2. 511, because it is one run with a key that already exists.
3. The browser bootstrap tier: Accela for both counties, then Dixon Tyler. Permits
   is the weakest category and this is most of the fix.
4. CIP across twelve jurisdictions.
5. Procurement across fourteen.
6. The small Napa towns end to end.

## Rules that hold regardless of schedule pressure

- A collector is not production until it returns records against live data.
- Zero new records is only a good run if the request succeeded, the structure is
  intact, and the canary passed.
- No bot challenge is ever defeated. Blocked is recorded, not worked around.
- No invented endpoints and no fabricated coordinates.
- Collector run time is never presented as project activity.
