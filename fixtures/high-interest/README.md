# The projects people actually search for

`fixtures/regression/` holds entity-resolution fixtures: they test whether Trackstar
can tell two records apart, or knows they are the same thing. This directory holds
something different, so it lives apart from them.

`portfolio.json` is the set of projects a resident of Napa or Solano is most likely to
type into the box. Coverage counts cells; a resident counts one thing, which is whether
the project they asked about is right. Every entry's tier was **measured against the
live API**, not asserted, and `scripts/probe-high-interest.py` re-measures it.

- `guaranteed` — found and placed today. Losing one is a regression.
- `found_unmapped` — Trackstar knows it exists and cannot defensibly place it. The gap
  a resident sees first.
- `watchlist` — high-interest and not found at all. A target, and deliberately not a
  build failure: a gate that is always red is a gate nobody reads.

The set is an editorial judgement, not a search ranking — there is no government list
of top projects and no query log yet. Replace it with real query logs when there are any.
