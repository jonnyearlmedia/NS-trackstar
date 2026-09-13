# The official postgis/postgis image used for local development is amd64-only.
# Building on the official multi-architecture Postgres base keeps the production
# deployment compatible with both ARM and x86 hosts, so the choice of instance
# architecture never becomes a reason the database cannot start.
# Bookworm avoids relying on expired Bullseye security repository metadata.
FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        postgresql-${PG_MAJOR}-postgis-3 \
        postgresql-${PG_MAJOR}-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*
