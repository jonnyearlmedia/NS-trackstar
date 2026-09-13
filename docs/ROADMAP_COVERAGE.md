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
Napa                    OK     OK     OK    OK    OK    OK   XX    --
American Canyon         OK     XX     OK    OK    OK    OK   XX    --
Napa County (uninc)     OK     XX     OK    --    OK    OK   XX    --
Yountville              --     --     OK    --    OK    OK   XX    --
St. Helena              OK     --     OK    --    OK    OK   XX    --
Calistoga               OK     --     OK    ~~    OK    OK   XX    --
Vallejo                 OK     OK     OK    --    OK    OK   XX    --
Benicia                 OK     XX     OK    --    OK    OK   XX    --
Fairfield               ~~     --     --    --    OK    OK   XX    --
Suisun City             OK     --     OK    --    OK    OK   XX    --
Vacaville               --     --     OK    --    OK    OK   XX    --
Dixon                   --     XX     OK    --    OK    OK   XX    --
Rio Vista               --     --     OK    --    OK    OK   XX    --
Solano County (uninc)   --     XX     OK    --    OK    OK   XX    --
```

`~~` Fairfield development is one project-specific record set, not an inventory.
Calistoga CIP is private construction with traffic impact, not the city's own
capital programme, which is published as a fiscal-year PDF schedule.

Derived totals, September 13, 2026: **39 strong, 44 partial, 19 blocked,
38 missing** across 14 jurisdictions x 10 categories. These are computed from the
evidence in `config/coverage/napa-solano.json`, not typed in, so a source that
stops returning records takes the number down with it.

## Named targets, not categories

Verified reachable and unbuilt, so no excuse exists:

- **St. Helena permits and CIP.** Meetings and development are now built. The
  city publishes finaled permits as a page per year rather than a feed, and no
  CIP page has been found yet.
- **One jurisdiction still has no meeting feed: Fairfield.** Thirteen of fourteen
  are covered. None of them was found by guessing a hostname. Napa County is on
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

- **Twelve jurisdictions have no CIP source.** Most cities publish a capital
  improvement program as a page or a PDF, and both adapters already exist.
- **Fourteen have no procurement source.** Untouched entirely.

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
- **Napa County and Solano County Accela** — both tenants answer 200; the public
  search needs a browser session bootstrap the container cannot run.
- **Dixon permits (Tyler EnerGov)** — host, route, field names and both module
  enums recorded in `SOURCE_STATUS.md`. Six guessed payloads returned 500; needs a
  Playwright capture of the app's own request.
- **American Canyon and Benicia OpenGov** — storefronts answer 200, record
  retrieval never verified anonymously.
- **Business openings, all fourteen** — California ABC challenges automated
  clients. The state open data portal was checked and only carries COVID era ABC
  datasets, so there is no sanctioned bulk route.
- **Fairfield and Rio Vista city sites** — challenged 403. Retest from another
  network before concluding anything.
- **Fairfield meetings (NovusAGENDA)** — the portal is reachable at
  `fairfield.novusagenda.com/agendapublic/`, unlike the city site. Its meeting list
  renders empty until an ASP.NET search postback runs, and a plain form post with
  the page's own `__VIEWSTATE` returns the same empty grid, so the grid is loaded
  by an async partial postback whose exact request has not been captured. Same
  class of blocker as Dixon's Tyler portal: it needs one Playwright capture of the
  portal's own request, not more guessing. The form contract found so far is
  recorded in `SOURCE_STATUS.md`.
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
