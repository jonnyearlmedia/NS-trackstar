# NS Trackstar source implementation status

This file separates production-ready source engines from tenant-specific smoke tests.

| Family | Jurisdictions | State | Notes |
|---|---|---|---|
| ArcGIS REST | Napa/Solano + cities | implemented | Used by Napa Public Works CIP, Water CIP, parcels; add layers by config. |
| CivicClerk | Vallejo | production ready | Public structured API; meetings + agenda items. |
| eTRAKiT | City of Napa | tenant verified | Live permit/project forms, exact searches, Telerik result parsing/pagination, historical PL23-0135 and 2026 permit/project details verified September 11, 2026. Safe recurring discovery partitioning still required before production promotion. |
| eTRAKiT | Vallejo | tenant verified | Live permit/project forms, exact searches, Telerik result parsing/pagination, AP26-0001 and BP26-00001 details verified September 11, 2026. Safe recurring discovery partitioning still required before production promotion. |
| Legistar | City of Napa | production ready | Public Web API client `napacity` verified September 11, 2026 with current-window meetings and agenda items; production config promoted. |
| Legistar | Solano County | production ready | Public Web API client `solano` verified September 11, 2026 with current-window meetings and agenda items; production config promoted. |
| PDF project tracker | Suisun City | production ready | Official 22-page Development Calendar canary and all 16 configured project pages verified September 11, 2026; exact status text and tracker grouping are preserved separately. |
| OpenGov public | American Canyon + Benicia | not started | Network-capture discovery before direct HTTP. |
| Tyler Civic Access | Fairfield | not started | Live request-contract capture required. |
| Accela ACA | Napa + Solano Counties | not started | Browser/session bootstrap first. |

## Promotion rule

A smoke config is not promoted into `config/sources/` until the tenant passes its canary and returns expected live records. Adapter code can be production-ready while a tenant configuration remains unverified.
