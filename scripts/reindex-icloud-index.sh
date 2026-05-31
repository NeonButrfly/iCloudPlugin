#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/.env.live}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-icloudplugin}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/docker-compose.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-icloud}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-change-me}"
POSTGRES_DB="${POSTGRES_DB:-icloud_index}"
SERVICE_PORT="${SERVICE_PORT:-8080}"
SERVICE_URL="${SERVICE_URL:-}"
PLUGIN_SERVICE_URL="${PLUGIN_SERVICE_URL:-}"
PLUGIN_API_TOKEN="${PLUGIN_API_TOKEN:-}"
SUDO_PASSWORD="${SUDO_PASSWORD:-}"
SERVICE_START_TIMEOUT_SECONDS="${SERVICE_START_TIMEOUT_SECONDS:-60}"
DRY_RUN=0
FORCE=0

usage() {
  cat <<'EOF'
Usage: reindex-icloud-index.sh [options]

Destroy the current cloud-vault index tables, then queue a fresh refresh run.

Options:
  --yes                     Confirm the destructive reset.
  --dry-run                 Print the planned operations without executing them.
  --service-url URL         Override the local cloudsync service URL.
  --env-file PATH           Override the cloudsync env file.
  --compose-file PATH       Override the compose file.
  --compose-project NAME    Override the compose project name.
  --help                    Show this help text.

Environment:
  ENV_FILE                  Cloudsync env file. Default: deploy/roles/cloudsync/.env.live
  COMPOSE_FILE              Cloudsync compose file. Default: deploy/roles/cloudsync/docker-compose.yml
  COMPOSE_PROJECT           Compose project name. Default: icloudplugin
  POSTGRES_HOST             PostgreSQL host. Default: postgres
  POSTGRES_PORT             PostgreSQL port. Default: 5432
  POSTGRES_USER             PostgreSQL user. Default: icloud
  POSTGRES_PASSWORD         PostgreSQL password. Default: change-me
  POSTGRES_DB               PostgreSQL database. Default: icloud_index
  PLUGIN_API_TOKEN          Bearer token for POST /refresh when enabled
  SUDO_PASSWORD             Optional sudo password for Docker access on Linux hosts
EOF
}

log_line() {
  printf '%s %s\n' "$(date -Is)" "$*"
}

fail() {
  log_line "ERROR: $*" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 || fail "Missing required command: ${command_name}"
}

mask_sensitive_arg() {
  local value="$1"
  if [[ "${value}" == Authorization:\ Bearer\ * ]]; then
    printf 'Authorization: Bearer [redacted]'
    return 0
  fi
  printf '%s' "${value}"
}

docker_command() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return 0
  fi

  if sudo -n docker info >/dev/null 2>&1; then
    sudo -n docker "$@"
    return 0
  fi

  if [[ -n "${SUDO_PASSWORD}" ]]; then
    printf '%s\n' "${SUDO_PASSWORD}" | sudo -S docker "$@"
    return 0
  fi

  fail "Docker requires elevated access. Use a Docker-enabled account, passwordless sudo, or set SUDO_PASSWORD."
}

docker_compose() {
  docker_command compose \
    -p "${COMPOSE_PROJECT}" \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    "$@"
}

load_env_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    return 0
  fi
  set -a
  # shellcheck disable=SC1090
  source <(tr -d '\r' < "${path}")
  set +a
}

postgres_service_running() {
  docker_compose ps --status running --services 2>/dev/null | grep -qx "${POSTGRES_SERVICE}"
}

psql_base_command() {
  if postgres_service_running; then
    docker_compose exec -T "${POSTGRES_SERVICE}" \
      psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" "$@"
    return 0
  fi

  docker_command run --rm \
    --network host \
    -e "PGPASSWORD=${POSTGRES_PASSWORD}" \
    postgres:16 \
    psql \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    "$@"
}

run_step() {
  local description="$1"
  shift
  if [[ "${DRY_RUN}" == "1" ]]; then
    log_line "DRY RUN: ${description}"
    printf '  %q' "$@"
    printf '\n'
    return 0
  fi

  log_line "${description}"
  "$@"
}

wait_for_service() {
  local attempts=0
  local max_attempts=$(( SERVICE_START_TIMEOUT_SECONDS / 2 ))
  if (( max_attempts < 1 )); then
    max_attempts=1
  fi

  while (( attempts < max_attempts )); do
    if curl -fsS "${SERVICE_URL%/}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    attempts=$((attempts + 1))
  done

  fail "Service did not become healthy at ${SERVICE_URL%/}/health within ${SERVICE_START_TIMEOUT_SECONDS}s."
}

truncate_index_tables() {
  local sql
  sql="TRUNCATE TABLE classification_jobs, classification_states, extracted_contents, files, jobs, sync_runs RESTART IDENTITY CASCADE;"

  if [[ "${DRY_RUN}" == "1" ]]; then
    log_line "DRY RUN: truncate cloud-vault index tables"
    printf '  SQL: %s\n' "${sql}"
    return 0
  fi

  log_line "Truncating cloud-vault index tables"
  psql_base_command -v ON_ERROR_STOP=1 -c "${sql}"
}

queue_refresh_run() {
  local curl_args=(
    -fsS
    -X POST
  )
  if [[ -n "${PLUGIN_API_TOKEN}" ]]; then
    curl_args+=(-H "Authorization: Bearer ${PLUGIN_API_TOKEN}")
  fi
  curl_args+=("${SERVICE_URL%/}/refresh")

  if [[ "${DRY_RUN}" == "1" ]]; then
    log_line "DRY RUN: queue fresh refresh run"
    printf '  %q' curl
    for arg in "${curl_args[@]}"; do
      printf ' %q' "$(mask_sensitive_arg "${arg}")"
    done
    printf '\n'
    return 0
  fi

  log_line "Queueing fresh refresh run"
  curl "${curl_args[@]}"
  printf '\n'
}

print_refresh_status() {
  local curl_args=(-fsS "${SERVICE_URL%/}/refresh/status")
  if [[ "${DRY_RUN}" == "1" ]]; then
    log_line "DRY RUN: print refresh status"
    printf '  %q' curl
    for arg in "${curl_args[@]}"; do
      printf ' %q' "${arg}"
    done
    printf '\n'
    return 0
  fi

  log_line "Current refresh status"
  curl "${curl_args[@]}"
  printf '\n'
}

start_runtime_services() {
  if [[ "${POSTGRES_HOST}" == "${POSTGRES_SERVICE}" ]]; then
    run_step \
      "Starting local postgres plus cloudsync runtime services" \
      docker_compose up -d postgres migrate service worker classification-worker
    return 0
  fi

  run_step \
    "Starting cloudsync runtime services against remote postgres" \
    docker_compose up -d --no-deps service worker classification-worker
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --service-url)
      SERVICE_URL="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --compose-project)
      COMPOSE_PROJECT="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

require_command curl
require_command docker

cd "${REPO_ROOT}"
load_env_file "${ENV_FILE}"

POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-icloud}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-change-me}"
POSTGRES_DB="${POSTGRES_DB:-icloud_index}"
SERVICE_PORT="${SERVICE_PORT:-8080}"
PLUGIN_API_TOKEN="${PLUGIN_API_TOKEN:-}"

if [[ -z "${SERVICE_URL}" ]]; then
  if [[ -n "${PLUGIN_SERVICE_URL}" ]]; then
    SERVICE_URL="${PLUGIN_SERVICE_URL}"
  else
    SERVICE_URL="http://127.0.0.1:${SERVICE_PORT}"
  fi
fi

if [[ "${DRY_RUN}" != "1" && "${FORCE}" != "1" ]]; then
  fail "This action is destructive. Re-run with --yes to confirm, or use --dry-run first."
fi

start_runtime_services

if [[ "${DRY_RUN}" != "1" ]]; then
  wait_for_service
fi

truncate_index_tables
queue_refresh_run
print_refresh_status
