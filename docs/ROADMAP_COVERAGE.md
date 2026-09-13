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
American Canyon         OK     XX     --    OK    OK    OK   XX    --
Napa County (uninc)     OK     XX     --    --    OK    OK   XX    --
Yountville              --     --     --    --    OK    OK   XX    --
St. Helena              --     --     --    --    OK    OK   XX    --
Calistoga               --     --     --    --    OK    OK   XX    --
Vallejo                 OK     OK     OK    --    OK    OK   XX    --
Benicia                 OK     XX     OK    --    OK    OK   XX    --
Fairfield               ~~     --     --    --    OK    OK   XX    --
Suisun City             OK     --     --    --    OK    OK   XX    --
Vacaville               --     --     --    --    OK    OK   XX    --
Dixon                   --     XX     OK    --    OK    OK   XX    --
Rio Vista               --     --     OK    --    OK    OK   XX    --
Solano County (uninc)   --     XX     OK    --    OK    OK   XX    --
```

`~~` Fairfield development is one project-specific record set, not an inventory.

## Named targets, not categories

Verified reachable and unbuilt, so no excuse exists:

- **St. Helena** `cityofsthelena.org` answers 200. Development, permits, meetings,
  CIP all unbuilt.
- **Eight jurisdictions have no meeting feed.** Three Granicus tenants were found
  in ten minutes by reading a city's own navigation. Napa, American Canyon,
  Napa County, Yountville, St. Helena, Calistoga, Fairfield, Suisun and Vacaville
  have not been checked for Granicus, eScribe, Legistar, CivicClerk or PrimeGov.
- **Twelve jurisdictions have no CIP source.** Most cities publish a capital
  improvement program as a page or a PDF, and both adapters already exist.
- **Fourteen have no procurement source.** Untouched entirely.
- **Vacaville eScribe** `vacaville.escribemeetings.com` answers 200. No adapter yet.

Blocked, with the specific reason:

- **Vacaville, Yountville, Calistoga city sites** — the remote container's egress
  refuses CONNECT. Not a fact about those cities. Retest locally.
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
- **511 live traffic** — collectors written and tested, never run with a key. The
  collector container could not even receive the key until this session; that is
  fixed, so one run settles it.

## Order of work

1. Everything reachable from wherever you are, before anything blocked. St. Helena
   and the meeting feed sweep are pure undone work.
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
