# Source configuration

Jurisdiction and tenant differences belong in configuration instead of duplicated adapter code.

Planned source families include:

- `arcgis_rest`
- `etrakit`
- `opengov_public`
- `tyler_civicaccess`
- `accela_aca`
- `hdl_business_license`
- `legistar`
- `civicclerk`
- `granicus`
- `escribe`
- `ceqanet`
- `pdf_project_tracker`
- `caltrans`
- `bayarea_511`
- `abc_ca`
- `environmental_health`
- `courtlistener_recap`
- `federal_register`
- `bia_gaming`
- `nigc`

The adapter rule is strict: reuse transport and parsing infrastructure without throwing away fields that exist only in one jurisdiction.

`pdf_project_tracker` is for official, slide- or page-based curated inventories where each
configured page describes one project. It preserves the source page text and document SHA-256;
stage groupings remain source-specific assertions rather than being flattened into planning or
construction status.

`ceqanet` reads the official CSV export and groups document history by SCH number. Any link to
an existing canonical project must be an explicit source-record anchor with typed relationship
and evidence signals; title similarity alone never merges identities.
