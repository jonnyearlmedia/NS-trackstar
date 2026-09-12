# The official postgis/postgis image used for local development is amd64-only.
# Building on the official multi-architecture Postgres base keeps the Oracle
# deployment compatible with both Ampere ARM and x86 Free Tier instances.
FROM postgres:16-bullseye

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        postgresql-${PG_MAJOR}-postgis-3 \
        postgresql-${PG_MAJOR}-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*
