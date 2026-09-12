# Secrets without editing `.env`

NS Trackstar does not require the user to manually open or edit an environment file for local API tokens.

## First-time setup on macOS

Run:

```bash
./scripts/setup-secrets
```

Two native macOS dialogs appear with hidden text fields:

1. 511 Bay Area API token
2. CourtListener API token

The values are stored in macOS Keychain under the service `com.ns-trackstar.secrets`. The setup script never prints them.

Check status without revealing values:

```bash
./scripts/setup-secrets check
```

Replace a token by running setup again. Leave a dialog blank to keep an already-configured value.

Remove both stored tokens:

```bash
./scripts/setup-secrets clear
```

## Running token-gated local commands

Use the wrapper so the command receives configured Keychain values without creating an `.env` file:

```bash
./scripts/with-secrets .venv/bin/ns-trackstar-ingest collect config/smoke/bayarea-511.traffic-events.json
```

or:

```bash
./scripts/with-secrets .venv/bin/ns-trackstar-ingest collect config/smoke/napa-solano.courtlistener.json
```

Explicit environment variables still take precedence, which keeps Linux/CI/server deployments conventional. On non-macOS systems the wrapper simply runs the command with the existing environment.

## Rules

- Never paste API tokens into chat.
- Never commit tokens.
- Never print token values in logs.
- Local macOS development should use Keychain through these scripts.
- Production deployment may inject the same variable names (`BAYAREA_511_API_KEY` and `COURTLISTENER_API_TOKEN`) through the deployment runtime; the user should not manually edit a file to do so.
