# NS Trackstar source implementation status

This file separates production-ready source engines from tenant-specific smoke tests.

| Family | Jurisdictions | State | Notes |
|---|---|---|---|
| ArcGIS REST | Napa/Solano + cities | implemented | Used by Napa Public Works CIP, Water CIP, parcels; add layers by config. |
| CivicClerk | Vallejo | implemented | Public structured API; meetings + agenda items. |
| eTRAKiT | Vallejo + City of Napa | engine implemented | Live tenant forms/detail pages confirmed; production discovery queries still require tenant smoke validation. |
| Legistar | City of Napa + Solano County | engine implemented | Generic public Web API adapter; candidate client names live in smoke configs until verified against each tenant. |
| OpenGov public | American Canyon + Benicia | not started | Network-capture discovery before direct HTTP. |
| Tyler Civic Access | Fairfield | not started | Live request-contract capture required. |
| Accela ACA | Napa + Solano Counties | not started | Browser/session bootstrap first. |

## Promotion rule

A smoke config is not promoted into `config/sources/` until the tenant passes its canary and returns expected live records. Adapter code can be production-ready while a tenant configuration remains unverified.
