# Deployment

The production split preserves the existing stack and has no required paid
service: the Next.js frontend runs on Vercel, while PostgreSQL/PostGIS, the API,
collectors, and HTTPS reverse proxy run on one Oracle Cloud Free Tier VM.

## One-time prerequisites

1. Create an Oracle Cloud Free Tier Ubuntu VM. An Ampere ARM instance is preferred
   for its memory allowance; the production PostGIS image builds for ARM or x86.
2. Reserve the VM's public IP. In both the Oracle network security list and the
   VM firewall, expose only SSH (22), HTTP (80), and HTTPS (443). PostgreSQL is
   intentionally not published.
3. Point a DNS hostname such as `api.example.com` at the VM's public IP. Caddy
   obtains and renews the TLS certificate automatically, so the API can be called
   safely from an HTTPS Vercel site.
4. Install Git and Docker Engine with the Compose plugin on the VM.

## Backend deploy

Clone this repository on the VM, check out `build/phase-0-foundation`, then run:

```sh
./scripts/deploy-oracle.sh
```

On first run, the script asks only for the public API hostname, deployed web
origin, and an email for certificate notices. It generates the database password
locally and stores runtime settings in an ignored `0600` file. **The user never
needs to open or manually edit that file.** The script builds the
architecture-compatible PostGIS/backend images, applies unapplied SQL migrations,
starts the API and sequential config-driven collector scheduler, and checks the
public HTTPS health endpoint.

To change the API hostname, web origin/CORS setting, or certificate email later,
run:

```sh
./scripts/deploy-oracle.sh configure
```

Press Enter to keep an existing value. The database password is preserved and
never printed. Check the non-secret deployment settings with:

```sh
./scripts/deploy-oracle.sh status
```

Then redeploy with:

```sh
./scripts/deploy-oracle.sh
```

Useful operations:

```sh
docker compose --env-file .env.production -f docker-compose.production.yml ps
docker compose --env-file .env.production -f docker-compose.production.yml logs -f api collector
git pull --ff-only
./scripts/deploy-oracle.sh
```

Those Docker commands are maintainer/debug operations; normal setup and
reconfiguration should go through the script so the user does not need to touch
environment files.

Before infrastructure maintenance, create a recoverable database backup:

```sh
mkdir -p backups
docker compose --env-file .env.production -f docker-compose.production.yml exec -T db \
  pg_dump -U nstrackstar -d nstrackstar -Fc > "backups/nstrackstar-$(date +%F).dump"
```

Do not commit `.env.production` or backups. Copy backups off the VM periodically;
Oracle Free Tier does not make application-level backups automatically.

## Frontend deploy

1. Import `jonnyearlmedia/NS-trackstar` into Vercel.
2. Set the project root directory to `apps/web` and production branch to the
   approved branch (normally `main` after PR review; do not merge PR #1 merely
   to deploy a preview).
3. Add `NEXT_PUBLIC_API_BASE_URL=https://<API_DOMAIN>` to Preview and Production
   using Vercel's project settings; no local env file is required.
4. Deploy. If the final Vercel/custom-domain origin differs from the backend's
   saved CORS value, run `./scripts/deploy-oracle.sh configure` on the VM, enter
   the final web origin, then rerun `./scripts/deploy-oracle.sh`.

Verify the real public path after both sides are deployed:

```sh
curl --fail https://<API_DOMAIN>/health
curl --fail "https://<API_DOMAIN>/map/projects?window=all"
```

In a browser, confirm the deployed map loads, selecting a real geometry opens
its project detail, search returns the project, timeline/source evidence loads,
and the browser console has no CORS or mixed-content error.

## Scope of the production compose file

The collector scheduler reads only promoted configurations in `config/sources`
and runs them one at a time at each configuration's `poll_minutes`. Smoke-only
eTRAKiT and Accela configurations are deliberately excluded until their safe
recurring discovery/session strategies are production-ready. Martin can be added
when the web app actually consumes its vector tiles; the current vertical slice
reads project GeoJSON from the API, so running an unused tile service would add
complexity without changing the deployed product.
