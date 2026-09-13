# Napa + Solano coverage expansion, 2026-09-13

This records what changed, what is genuinely covered, and what is still missing.
It is deliberately unflattering, because the failure mode this project already
has a document about is marking work done on the strength of green CI.

## The product change

Trackstar used to answer "what is this?" with `A development project in
Napa–Solano.` whenever a project had no cached summary, and it only ever
displayed ten allowlisted assertion fields, so most of the evidence already in
the database never reached a reader.

`services/api/src/ns_trackstar_api/narrative.py` now composes the answer
deterministically from the structured assertions, status dimensions and events
Trackstar already holds. No model call is involved, and none is required for an
ordinary project. Every sentence traces to evidence; where the evidence does not
support a claim the composer says less rather than guessing.

Verified on a real screenshot of the running app: a project with a description,
unit count, building area, site size, cost and applicant renders as

> **What is this?** Costco plans to move into a larger new store here alongside
> new housing and other commercial development on the former mall site. It is
> going through official review right now.
>
> **What's happening** The updated housing plan was filed, expanding the project
> from 178 to 245 homes (May 2026).
>
> **Why you'd care** New homes 245 · Building space 160,000 sq ft · Site size
> 30.5 acres · Estimated cost $48 million · Applicant Northgate Partners LLC
>
> **What happens next?** Construction expected to start: April 1, 2027.

Identifiers did not disappear. Every assertion is grouped into a detail section,
including an "Other details" catch-all, so a field Trackstar has no opinion about
is still reachable instead of being silently dropped.

One ranking rule matters: a statewide or federal rollup describes the *filing*,
not the project. A CEQA amendment abstract once made Napa Pipe read as a bridge
project. Local agency prose now leads, and a rollup abstract follows the
structured identity sentence rather than replacing it.

## Coverage, measured honestly

Coverage is scored per jurisdiction per source category. It is never counted in
map dots. The manifest declares the evidence and the state is *derived* from it,
so the manifest cannot claim coverage that no production source supports.

At the start of this pass: **10 strong, 58 partial, 6 blocked, 66 missing.**

Totals: {'strong': 27, 'partial': 43, 'blocked': 18, 'missing': 52}

| Jurisdiction | current development | permits | government meetings | cip construction | gis spatial | ceqa environmental | business openings | transportation | procurement | specialized regulatory | Score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| City of Napa | strong | strong | strong | strong | strong | partial | blocked | partial | - | partial | 65% |
| American Canyon | strong | blocked | - | strong | strong | partial | blocked | partial | - | partial | 45% |
| Yountville | - | - | - | - | strong | partial | blocked | partial | - | partial | 25% |
| St. Helena | - | - | - | - | strong | partial | blocked | partial | - | partial | 25% |
| Calistoga | - | - | - | - | strong | partial | blocked | partial | - | partial | 25% |
| Unincorporated Napa County | strong | blocked | - | - | strong | partial | blocked | partial | - | partial | 35% |
| Vallejo | strong | strong | strong | - | strong | partial | blocked | partial | - | partial | 55% |
| Benicia | strong | blocked | - | - | strong | partial | blocked | partial | - | partial | 35% |
| Fairfield | partial | - | - | - | strong | partial | blocked | partial | - | partial | 30% |
| Suisun City | strong | - | - | - | strong | partial | blocked | partial | - | partial | 35% |
| Vacaville | - | - | - | - | strong | partial | blocked | partial | - | partial | 25% |
| Dixon | - | - | - | - | strong | partial | blocked | partial | - | partial | 25% |
| Rio Vista | - | - | - | - | strong | partial | blocked | partial | - | partial | 25% |
| Unincorporated Solano County | - | blocked | strong | - | strong | partial | blocked | partial | - | partial | 35% |

`strong` means a recurring production source actually inventories that
jurisdiction for that category. `partial` means real evidence from a wider
rollup, a single-project document set, or reference data. `blocked` means a
documented upstream access restriction. `missing` means work not done.

Statewide CEQA filings and county parcels never count as local development or
permit coverage. A test enforces that.

## What was added

**Spatial truth for every jurisdiction.** Parcels were the only reference layer,
which cannot resolve an address or say which city a record falls in. Six
official layers were promoted, each verified live: Napa address points (68,538),
road centrelines (11,844), zoning (193) and city boundaries (5); Solano city
boundaries (7) and street centrelines with address ranges (38,004). Two
enrichments use them: exact-address placement, which only accepts an exact
normalized match to a single address point, and a derived jurisdiction stamp,
recorded as a spatial derivation rather than an agency claim.

**Permits in the two largest cities.** Vallejo and Napa eTRAKiT were promoted
once recurring discovery became safe. eTRAKiT has no recently-changed feed, so
discovery walks the record-number space by prefix and year under a page cap and
a per-run candidate budget.

**Business-opening evidence.** The California ABC adapter parses all three daily
statewide reports and filters by ABC's own structured county column. Tenant
identity is only ever taken from a row ABC labelled `DBA:`, so a licence
holder's personal name is never promoted to a storefront brand, and a tenant
improvement permit carries no identity weight at all.

**Answerability as a test.** The ten named Vallejo projects and a representative
project in every other jurisdiction that has a production source each declare the
evidence needed to answer nine questions. Unit tests prove the composer answers
from that shape; a status route proves production actually holds it.

## What is still missing, and why

**Six jurisdictions have no local source at all.** Yountville, St. Helena,
Calistoga, Vacaville, Dixon and Rio Vista are covered only by statewide rollups
and county spatial layers. Vacaville was a P0 target and did not land: the
verification environment's egress policy refused `www.ci.vacaville.ca.gov`,
`www.yountville.gov` and `www.ci.calistoga.ca.us` at CONNECT, and
`www.riovistacity.com` returned 403. That is an environment limit, not a finding
about those sites. Vacaville's eScribe meeting portal *is* reachable and is the
next route in; an eScribe adapter would also serve Fairfield and Dixon.

**Business openings are blocked everywhere.** The ABC reports are public and the
parser is proven against real captured rows, but Cloudflare answers automated
clients with an interactive challenge. Trackstar reports that as blocked. It does
not spoof a client or solve the challenge.

**Live traffic is unpromoted.** The 511 traffic-event and WZDx collectors are
implemented and unit tested, but `api.511.org` answers 401 without a token and
the token is not in the repository, so neither could be verified against live
data. A collector that has not been proven to return records is not production.

**Procurement is untouched in all fourteen jurisdictions.**

**Fairfield, both county Accela tenants, and both OpenGov tenants remain
blocked** for the reasons already recorded in `docs/SOURCE_STATUS.md`. None of
those blockers were worked around.

## Known UI defect introduced by nothing here

In the basemap-failure state the "Map could not load" banner renders over the
project sheet and covers the title and a key-fact row. It is a stacking-order
problem inside the eleven-layer cascade and belongs to the `ui-rebuild` phases
rather than a twelfth override. Recorded in `docs/UI_FINDINGS_2026-09-13.md`.

## One process bug worth remembering

`coverage/` in `.gitignore`, written for test-coverage output, also matched
`config/coverage/`. The jurisdiction coverage manifest was never tracked, so
every coverage test passed locally against a file a clean checkout would not
have had. Anchored with an explicit exception that says why it exists.
