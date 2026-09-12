#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Engine with the Compose plugin, then rerun this script." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "The Docker Compose plugin is required." >&2
  exit 1
fi
for required_command in curl openssl; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "$required_command is required." >&2
    exit 1
  fi
done

env_file=.env.production
if [ ! -f "$env_file" ]; then
  printf "Public API hostname (example: api.trackstar.example): "
  read -r api_domain
  printf "Deployed web origin (example: https://trackstar.example): "
  read -r cors_origins
  printf "Email for automatic HTTPS certificate notices: "
  read -r caddy_email

  case "$api_domain" in
    ""|*[!A-Za-z0-9.-]*|.*|*.) echo "Enter a valid hostname only, without https://, a path, or a port." >&2; exit 1 ;;
  esac
  case "$api_domain" in
    *.*) ;;
    *) echo "The public API hostname must contain a domain suffix." >&2; exit 1 ;;
  esac
  case "$cors_origins" in
    https://*) ;;
    *) echo "The deployed web origin must start with https://." >&2; exit 1 ;;
  esac
  case "$caddy_email" in
    *@*.*) ;;
    *) echo "Enter a valid certificate-notice email address." >&2; exit 1 ;;
  esac
  case "$caddy_email" in
    *" "*) echo "The certificate-notice email cannot contain spaces." >&2; exit 1 ;;
  esac

  db_password=$(openssl rand -hex 24)
  umask 077
  {
    echo "POSTGRES_DB=nstrackstar"
    echo "POSTGRES_USER=nstrackstar"
    echo "POSTGRES_PASSWORD=$db_password"
    echo "API_DOMAIN=$api_domain"
    echo "CORS_ORIGINS=$cors_origins"
    echo "CADDY_ACME_EMAIL=$caddy_email"
  } > "$env_file"
  echo "Created $env_file with mode 600 and a generated database password."
else
  echo "Using existing $env_file."
fi

docker compose --env-file "$env_file" -f docker-compose.production.yml up --detach --build
docker compose --env-file "$env_file" -f docker-compose.production.yml ps

api_domain=$(sed -n 's/^API_DOMAIN=//p' "$env_file")
echo "Waiting for the public API health check at https://$api_domain/health"
if curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 5 \
  "https://$api_domain/health"; then
  echo
  echo "NS Trackstar backend is healthy."
else
  echo "The stack is running, but public HTTPS is not healthy yet." >&2
  echo "Confirm the API DNS A/AAAA record points to this VM and ports 80/443 are open." >&2
  exit 2
fi
