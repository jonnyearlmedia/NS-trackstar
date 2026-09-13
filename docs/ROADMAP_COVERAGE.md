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

Legend: `OK` production and verified · `~~` partial, usually a regional rollup rather
than a local source · `--` not built · `XX` blocked, reason below

This grid is now **generated** from `config/coverage/napa-solano.json` by
`scripts/coverage-grid.py`, not typed. It used to be typed while the totals beneath it
were computed, which is how it came to show CEQA as `OK` everywhere when the scorecard
had always derived it as partial: statewide clearinghouse filings are a regional
rollup, not a local source, and the table had been quietly flattering itself.

```
                        dev  permit  meet   cip   gis  ceqa  biz  proc
Napa                    OK     OK     OK    OK    OK    ~~   OK   XX
American Canyon         OK     XX     OK    OK    OK    ~~   OK   XX
Yountville              --     --     OK    --    OK    ~~   OK   --
St. Helena              OK     --     OK    OK    OK    ~~   OK   --
Calistoga               OK     --     OK    ~~    OK    ~~   OK   --
Napa County (uninc)     OK     OK     OK    OK    OK    ~~   OK   XX
Vallejo                 OK     OK     OK    --    OK    ~~   OK   OK
Benicia                 OK     XX     OK    OK    OK    ~~   OK   XX
Fairfield               ~~     --     OK    OK    OK    ~~   OK   --
Suisun City             OK     OK     OK    --    OK    ~~   OK   XX
Vacaville               XX     XX     OK    OK    OK    ~~   OK   --
Dixon                   OK     OK     OK    OK    OK    ~~   OK   --
Rio Vista               --     OK     OK    --    OK    ~~   OK   --
Solano County (uninc)   OK     OK     OK    OK    OK    ~~   OK   XX
```

`~~` Fairfield development is one project-specific record set, not an inventory.
Calistoga CIP is private construction with traffic impact, not the city's own
capital programme, which is published as a fiscal-year PDF schedule.

Derived totals, September 13, 2026: **69 strong, 44 partial, 10 blocked,
17 missing** across 14 jurisdictions x 10 categories. These are computed from the
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

  The remaining thirteen were then swept, and the answer is not thirteen problems.
  **Six of the fourteen are on OpenGov Procurement**: Napa (`cityofnapa`), Solano
  County (`solanocounty`), American Canyon (`cityofamericancanyon`), Suisun City
  (`suisun`) and Benicia (`beniciaca`) are live tenants, and Napa County's own
  procurement page announces its transition to OpenGov as in progress. So this
  category turns on one vendor's bot policy rather than on fourteen separate
  investigations, which is worth knowing before anyone spends another week on it.

  That block was retested from an ordinary residential network on the same day ABC
  was reclassified, and it does not move: `cf-mitigated: challenge` for a
  self-identifying client and a browser user agent alike. It is a property of the
  site. It is also, deliberately, not defeated. The shape looked encouragingly like
  PlanetBids - every non-`/portal` path returns the same application shell, which is
  the fall-through that hid PlanetBids' real API host - so the shell's own bundles
  were read for an API base. There is none in them: the app builds its routes at
  runtime from chunks it loads by computed name, and the only path that would name
  them is the challenged one.

  Calistoga and Yountville publish bids on their own pages, which render client-side
  and carry no per-bid structure in the delivered HTML. St. Helena, Fairfield,
  Vacaville, Dixon and Rio Vista remain unexamined.

Blocked, with the specific reason:

- **Vacaville** — closed as far as it can be, rather than left as a to-do. Three
  routes were checked from an ordinary residential network and all three are shut:
  `www.cityofvacaville.gov` answers 403 from Akamai to a self-identifying client and
  to a browser user agent alike, so that block belongs to the site rather than to
  our egress; the city's eTRAKiT tenant has anonymous search switched off, unlike
  Vallejo's and Napa's on the same platform; and the city's own ArcGIS server at
  `covgis.cityofvacaville.com`, which answers fine while the website does not,
  publishes parcels, addresses, zoning, streets and boundaries and no project,
  permit or capital layer at all. Its meetings remain covered through eScribe. This
  is a city that does not publish its pipeline anonymously, which is a different and
  more useful thing to know than "the site is blocked".

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
- **Dixon permits were never blocked, and the entry that said so was mine.** The
  route guard really does answer `isEnable: false` for the new Civic Access UI, and
  that much still stands. The mistake was concluding from it that the tenant
  publishes nothing, which turned the legacy API's HTTP 500 into confirmation
  instead of a clue. That endpoint needs four headers a browser sends and a
  hand-built request does not — `tenantId`, `tenantName`, `Tyler-TenantUrl`,
  `Tyler-Tenant-Culture` — and without all four it answers 500 to every payload,
  which is indistinguishable from a dead route. With them, Dixon reports 92,405
  records including 17,192 permits. Suisun City runs the same product and reports
  12,637. Both cities had no permit source at all.

  Twice in one day a conclusion of "this agency publishes nothing" came from
  checking one of its surfaces: Vacaville's capital programme was the first. The
  rule that follows is not "check harder", it is narrower and more useful — a
  finding about one surface is a finding about that surface, and the sentence
  written down has to say which one.
- **American Canyon and Benicia OpenGov** — storefronts answer 200, record
  retrieval never verified anonymously.
- **Business openings** is no longer on this list. It was never an adapter
  problem. Run from an ordinary residential network rather than a datacentre,
  `www.abc.ca.gov` answers normally and the existing collector returned 171
  service-area records at parser yield 1.0 in a seven-day window. The lesson is
  worth more than the source: "blocked" had been recorded about a site, when the
  evidence only ever supported recording it about a network. Re-test a Cloudflare
  or Akamai block from somewhere else before believing it.
- **Fairfield and Rio Vista city sites** — retested from an ordinary residential
  network and still 403, Akamai for Fairfield and Cloudflare for Rio Vista, to a
  self-identifying client and a browser user agent alike. Both blocks belong to the
  sites. Neither city is dark because of it: Fairfield now has meetings on eScribe
  and 87 capital projects from its own ArcGIS org, and Rio Vista has meetings on
  Granicus. The website was never the only door.
- **511 live traffic** is done, and the key was never missing. It was in the
  operator's own Keychain under `com.ns-trackstar.secrets`, where
  `scripts/with-secrets` has always looked for it, and unreachable only from a
  remote container. The run that settled it also caught a defect that would have
  shipped: the endpoint accepts the `bbox` parameter the config was passing and
  ignores it, so the first run returned 18 "service area" events of which one was in
  Napa and the rest were in Sonoma, San Mateo, Santa Cruz, Marin, Alameda and Santa
  Clara. Events are now kept by 511's own county label. The WZDx work-zone feed
  stays unpromoted: it carries no county label, and no rectangle separates these two
  counties from Sonoma without also excluding Calistoga.

## The projects people actually search for

Coverage counts cells. A resident counts one thing: whether the project they asked
about is right. Those are not the same measurement, and until today only the first
one was being taken.

Eighty high-interest projects - ten in each of the eight jurisdictions where the
service area's attention concentrates - were probed against the live API on
September 13, 2026. **Thirty are findable. Fifteen of those are placed on the map.**
Fifty cannot be found at all. That set lives in
`fixtures/high-interest/portfolio.json`, with each entry's tier measured
rather than asserted, and `scripts/probe-high-interest.py` re-measures it and exits
non-zero when a project falls out of the guaranteed tier.

Three things about that number are worth stating plainly.

It is not a search ranking. There is no government list of top projects and Trackstar
has no query log yet, so the set is an editorial judgement from scale, construction
impact, recency, controversy and name recognition. It should be replaced by real
query logs the moment there are any.

Fifteen of the thirty are found but unmapped - Trackstar knows Fairview at Northgate,
the Costco project, exists and cannot defensibly place it. That is the gap a resident
sees first, and it is a different problem from the fifty that are missing entirely.

And the fifty are the honest headline. Broad source coverage is at 66 strong cells and
climbing; the projects a person would actually type into the box are at 30 of 80. More
sources will not close that on their own, because the gap is entity resolution and
naming as much as ingestion: the pipeline holds "Minor Amendment to the Watson Ranch
Specific Plan" where a resident types "Watson Ranch".

## Order of work

1. Everything reachable from wherever you are, before anything blocked. The
   meeting sweep and St. Helena are finished for every jurisdiction this container
   can reach.
2. ~~511~~ done. What it cost: the key was on the operator's machine all along.
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
