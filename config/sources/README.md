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
- `caltrans`
- `bayarea_511`
- `abc_ca`
- `environmental_health`
- `courtlistener_recap`
- `federal_register`
- `bia_gaming`
- `nigc`

The adapter rule is strict: reuse transport and parsing infrastructure without throwing away fields that exist only in one jurisdiction.
