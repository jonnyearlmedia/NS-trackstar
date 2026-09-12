# Regression fixtures

The JSON documents in `regression/` are executable regression fixtures loaded by the
ingestion test suite. They preserve the minimum identity, relationship, geometry, status,
and confidence invariants for five real Napa/Solano projects.

Required fixtures:

1. `scotts-valley-vallejo-casino` — overlapping parcels, CEQA, BIA, NIGC, federal litigation, interested-party statements.
2. `sr37-sears-point-mare-island` — linear geometry, Caltrans identifiers, environmental lineage, funding, work-zone transitions.
3. `napa-pipe` — master development and child phases.
4. `one-lake-canon-station` — aliases, developer organization, subdivisions and related infrastructure.
5. `dutch-bros-suisun` — business identity, permitting narrative, construction transition and unknown opening date.

Fixtures test relationship creation before merge behavior. Sources and identifiers in a
fixture are evidence anchors, not a claim that every project fact is current.
