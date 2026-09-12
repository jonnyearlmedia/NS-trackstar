#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

env_file=.env.production
mode=${1:-deploy}
api_domain_override=${NS_TRACKSTAR_API_DOMAIN:-}
web_origin_override=${NS_TRACKSTAR_WEB_ORIGIN:-}
cert_email_override=${NS_TRACKSTAR_CERT_EMAIL:-}

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

read_setting() {
  key=$1
  if [ -f "$env_file" ]; then
    sed -n "s/^${key}=//p" "$env_file" | head -n 1
  fi
}

prompt_keep_existing() {
  label=$1
  current=$2
  if [ -n "$current" ]; then
    printf "%s [%s]: " "$label" "$current" >&2
  else
    printf "%s: " "$label" >&2
  fi
  read -r value
  if [ -z "$value" ]; then
    value=$current
  fi
  printf "%s" "$value"
}

pick_setting() {
  override=$1
  label=$2
  current=$3
  if [ -n "$override" ]; then
    printf "%s" "$override"
  else
    prompt_keep_existing "$label" "$current"
  fi
}

validate_runtime_settings() {
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
}

configure_runtime() {
  current_api_domain=$(read_setting API_DOMAIN || true)
  current_cors_origins=$(read_setting CORS_ORIGINS || true)
  current_caddy_email=$(read_setting CADDY_ACME_EMAIL || true)
  db_name=$(read_setting POSTGRES_DB || true)
  db_user=$(read_setting POSTGRES_USER || true)
  db_password=$(read_setting POSTGRES_PASSWORD || true)

  api_domain=$(pick_setting "$api_domain_override" "Public API hostname (example: api.trackstar.example)" "$current_api_domain")
  cors_origins=$(pick_setting "$web_origin_override" "Deployed web origin (example: https://trackstar.vercel.app)" "$current_cors_origins")
  caddy_email=$(pick_setting "$cert_email_override" "Email for automatic HTTPS certificate notices" "$current_caddy_email")

  validate_runtime_settings

  : "${db_name:=nstrackstar}"
  : "${db_user:=nstrackstar}"
  if [ -z "$db_password" ]; then
    db_password=$(openssl rand -hex 24)
  fi

  umask 077
  temp_file=$(mktemp "${env_file}.tmp.XXXXXX")
  trap 'rm -f "$temp_file"' EXIT HUP INT TERM
  {
    echo "POSTGRES_DB=$db_name"
    echo "POSTGRES_USER=$db_user"
    echo "POSTGRES_PASSWORD=$db_password"
    echo "API_DOMAIN=$api_domain"
    echo "CORS_ORIGINS=$cors_origins"
    echo "CADDY_ACME_EMAIL=$caddy_email"
  } > "$temp_file"
  chmod 600 "$temp_file"
  mv "$temp_file" "$env_file"
  trap - EXIT HUP INT TERM

  echo "Saved deployment settings securely. You do not need to open $env_file."
}

show_status() {
  if [ ! -f "$env_file" ]; then
    echo "NS Trackstar backend is not configured yet."
    return 1
  fi
  echo "NS Trackstar deployment settings:"
  echo "  API hostname: $(read_setting API_DOMAIN)"
  echo "  Web origin: $(read_setting CORS_ORIGINS)"
  echo "  Certificate email: $(read_setting CADDY_ACME_EMAIL)"
  if [ -n "$(read_setting POSTGRES_PASSWORD)" ]; then
    echo "  Database password: configured (hidden)"
  else
    echo "  Database password: missing"
  fi
}

case "$mode" in
  configure)
    configure_runtime
    exit 0
    ;;
  status)
    show_status
    exit $?
    ;;
  deploy)
    ;;
  *)
    echo "Usage: ./scripts/deploy-oracle.sh [deploy|configure|status]" >&2
    exit 2
    ;;
esac

if [ ! -f "$env_file" ]; then
  echo "First-time NS Trackstar backend setup. No env-file editing is required."
  configure_runtime
elif [ -n "$api_domain_override$web_origin_override$cert_email_override" ]; then
  echo "Applying supplied deployment settings without env-file editing."
  configure_runtime
else
  echo "Using saved deployment settings. Run './scripts/deploy-oracle.sh configure' to change them without editing files."
fi

# Vercel owns apps/web. Do not tear down or rebuild the persistent backend when
# an autodeploy contains only frontend/docs changes; restarting the collector on
# every UI iteration can starve later sources in its sequential startup sweep.
backend_deploy=1
if git rev-parse 'HEAD@{1}' >/dev/null 2>&1; then
  backend_paths=$(git diff --name-only 'HEAD@{1}' HEAD -- \
    services config db infra docker-compose.production.yml Dockerfile scripts 2>/dev/null || true)
  if [ -z "$backend_paths" ]; then
    backend_deploy=0
  fi
fi

if [ "$backend_deploy" -eq 1 ]; then
  echo "Backend-impacting changes detected; rebuilding the Trackstar stack."
  docker compose --env-file "$env_file" -f docker-compose.production.yml up --detach --build
  docker compose --env-file "$env_file" -f docker-compose.production.yml ps
else
  echo "Frontend/docs-only update detected; leaving API, database, and collector containers running."
fi

api_domain=$(read_setting API_DOMAIN)
echo "Checking the public API at https://$api_domain/health"
if curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 5 \
  "https://$api_domain/health"; then
  echo
  if [ "$backend_deploy" -eq 1 ]; then
    echo "NS Trackstar backend is healthy."
  else
    echo "NS Trackstar backend stayed healthy without a collector restart."
  fi
else
  echo "The stack is running, but public HTTPS is not healthy yet." >&2
  echo "Confirm the API DNS A/AAAA record points to this VM and ports 80/443 are open." >&2
  exit 2
fi
