# Moving this work to a local session

Everything that needs a real network, a real browser, or SSH has to run from a
machine that has them. This remote container has none of the three, and that is
the single reason coverage stalled where it did.

Verified from inside the container, not assumed:

```
ssh binary          MISSING
~/.ssh/             empty
15.204.82.184:22    timed out
github.com:22       timed out
15.204.82.184:443   OPEN
```

Only port 443 gets out, and Playwright's browser has no outbound network at all,
so any page navigation dies with `ERR_CONNECTION_RESET`. That blocks three city
websites, both Accela permit tenants, and the Dixon permit capture. Nothing about
those sources is broken; the box cannot reach them.

## Start a local session

On the Mac that already has SSH access to the server:

```sh
git clone https://github.com/jonnyearlmedia/NS-trackstar.git
cd NS-trackstar
git checkout claude/napa-solano-coverage-expansion-b9z66i
claude
```

Then say: "read docs/ROADMAP_COVERAGE.md and keep going".

## What a local session needs working

```sh
# Python side
python3.12 -m venv .venv
.venv/bin/pip install -e "services/ingest[dev]" -e "services/api[dev]"
.venv/bin/python -m pytest services/ingest services/api -q     # expect 404 passing

# Browser, for the Accela and Tyler work that this container could not do
.venv/bin/pip install playwright && .venv/bin/playwright install chromium

# Web side
pnpm install && pnpm typecheck && pnpm ui:gate

# Database, only needed for a real ingest run rather than a dry run
docker compose up -d
export DATABASE_URL=postgresql://nstrackstar:nstrackstar@localhost:5432/nstrackstar
for m in db/migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$m"; done
```

## The first three things to run

```sh
# 1. What can this network actually reach? Stdlib only, no setup.
python3 scripts/probe-sources.py --json /tmp/reach.json

# 2. Does 511 work with the key the server holds?
BAYAREA_511_API_KEY=... .venv/bin/ns-trackstar-ingest collect \
  config/smoke/bayarea-511.traffic-events.json
# If it returns records, move both 511 configs to config/sources/ and add a
# freshness policy. That is the promotion rule, not a formality.

# 3. Anything the container could not see
.venv/bin/ns-trackstar-ingest collect config/sources/<new>.json
```

## On the server

```sh
ssh <you>@15.204.82.184
cd ~/NS-trackstar
git fetch origin && git checkout build/phase-0-foundation && git pull

# The tokens now reach the collector, which they did not before. Set once:
./scripts/deploy-production.sh configure     # preserves tokens across runs
./scripts/deploy-production.sh status        # says which tokens are configured
./scripts/deploy-production.sh

# If this server ran install-autodeploy before the deploy script was renamed,
# re-run it once so the generated runner points at the new path:
./scripts/install-autodeploy
```

## What not to repeat

- Do not promote a collector that has not returned records against live data.
  Three production sources were found this session that could have returned zero
  rows forever while reporting healthy.
- Do not defeat a bot challenge. ABC and Fairfield are recorded as blocked on
  purpose.
- Do not invent an endpoint. Six guessed payloads at Dixon's permit server
  returned 500 and that is where the guessing stopped.
