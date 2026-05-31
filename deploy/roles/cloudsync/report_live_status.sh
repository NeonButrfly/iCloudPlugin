#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/.env.live}"
CLASSIFIER_ENV_FILE="${CLASSIFIER_ENV_FILE:-${REPO_ROOT}/deploy/roles/classifier/.env.live}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-icloudplugin}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/docker-compose.yml}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-icloud}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-change-me}"
POSTGRES_DB="${POSTGRES_DB:-icloud_index}"
SERVICE_URL="${SERVICE_URL:-}"
CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL:-}"
VAULT_ROOT="${VAULT_ROOT:-/mnt/cloud-vault/document-vault}"
SUMMARY_JSON_PATH="${SUMMARY_JSON_PATH:-}"
JSON_PYTHON="${JSON_PYTHON:-python3}"
SUDO_PASSWORD="${SUDO_PASSWORD:-}"

PLUGIN_API_TOKEN="${PLUGIN_API_TOKEN:-}"
CLASSIFIER_API_TOKEN="${CLASSIFIER_API_TOKEN:-}"
SERVICE_HEALTH_JSON='{}'
REFRESH_STATUS_JSON='{}'
CLASSIFIER_HEALTH_JSON='{}'
CLASSIFICATION_JOB_COUNTS_JSON='{}'
CLASSIFICATION_STATE_COUNTS_JSON='{}'
PROVIDER_COUNTS_JSON='{}'
VAULT_COUNTS_JSON='{}'

usage() {
  cat <<'EOF'
Usage: report_live_status.sh [options]

Print one unified cloud-vault live status report for the current compute host.

Options:
  --summary-json PATH         Write the machine-readable JSON report to PATH.
  --service-url URL          Override the cloudsync service base URL.
  --classifier-health-url URL Override the classifier health URL.
  --vault-root PATH          Override the vault root used for note counts.
  --help                     Show this help text.

Environment:
  ENV_FILE                   Cloudsync env file. Default: deploy/roles/cloudsync/.env.live
  CLASSIFIER_ENV_FILE        Classifier env file. Default: deploy/roles/classifier/.env.live
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

docker_compose() {
  docker_command compose \
    -p "${COMPOSE_PROJECT}" \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    "$@"
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

psql_json() {
  local sql="$1"
  psql_base_command -t -A -c "${sql}"
}

json_or_error() {
  local label="$1"
  shift
  set +e
  local output
  output="$("$@" 2>&1)"
  local status=$?
  set -e
  if [[ ${status} -eq 0 ]]; then
    printf '%s' "${output}"
    return 0
  fi
  "${JSON_PYTHON}" - <<PY
import json
print(json.dumps({"ok": False, "error": ${label@Q}, "detail": ${output@Q}}))
PY
}

capture_http_json() {
  local url="$1"
  shift
  json_or_error "http-request-failed" curl -fsS "$@" "${url}"
}

capture_service_json() {
  local path="$1"
  shift
  capture_http_json "${SERVICE_URL%/}${path}" "$@"
}

count_vault_files() {
  local target="$1"
  if [[ ! -d "${target}" ]]; then
    printf '0'
    return 0
  fi
  find "${target}" -type f | wc -l | tr -d ' '
}

collect_vault_counts_json() {
  local classified_count needs_review_count attachments_count extracted_markdown_count
  local classification_index_present home_present
  classified_count="$(count_vault_files "${VAULT_ROOT}/01 Classified")"
  needs_review_count="$(count_vault_files "${VAULT_ROOT}/02 Needs Review")"
  attachments_count="$(count_vault_files "${VAULT_ROOT}/90 Attachments")"
  extracted_markdown_count="$(count_vault_files "${VAULT_ROOT}/_system/extracted-markdown")"
  classification_index_present=0
  home_present=0
  [[ -f "${VAULT_ROOT}/Classification Index.md" ]] && classification_index_present=1
  [[ -f "${VAULT_ROOT}/Home.md" ]] && home_present=1

  "${JSON_PYTHON}" - <<PY
import json
print(json.dumps({
    "vault_root": ${VAULT_ROOT@Q},
    "classified_files": int(${classified_count@Q}),
    "needs_review_files": int(${needs_review_count@Q}),
    "attachments_files": int(${attachments_count@Q}),
    "extracted_markdown_files": int(${extracted_markdown_count@Q}),
    "classification_index_present": ${classification_index_present@Q} == "1",
    "home_note_present": ${home_present@Q} == "1",
}))
PY
}

capture_db_json() {
  local sql="$1"
  json_or_error "db-query-failed" psql_json "${sql}"
}

classification_job_counts_sql() {
  cat <<'EOF'
select coalesce(
  json_object_agg(status, item_count order by status),
  '{}'::json
)
from (
  select status, count(*) as item_count
  from classification_jobs
  group by status
) counts;
EOF
}

classification_state_counts_sql() {
  cat <<'EOF'
select coalesce(
  json_object_agg(submission_status, item_count order by submission_status),
  '{}'::json
)
from (
  select submission_status, count(*) as item_count
  from classification_states
  group by submission_status
) counts;
EOF
}

provider_counts_sql() {
  cat <<'EOF'
select coalesce(
  json_object_agg(provider_name, item_count order by provider_name),
  '{}'::json
)
from (
  select split_part(trim(leading '/' from path), '/', 1) as provider_name,
         count(*) as item_count
  from files
  where is_deleted is false
  group by 1
) providers;
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --summary-json)
        SUMMARY_JSON_PATH="$2"
        shift 2
        ;;
      --service-url)
        SERVICE_URL="$2"
        shift 2
        ;;
      --classifier-health-url)
        CLASSIFIER_HEALTH_URL="$2"
        shift 2
        ;;
      --vault-root)
        VAULT_ROOT="$2"
        shift 2
        ;;
      --help)
        usage
        exit 0
        ;;
      *)
        usage >&2
        fail "Unknown argument: $1"
        ;;
    esac
  done
}

main() {
  parse_args "$@"
  require_command curl
  require_command docker
  require_command "${JSON_PYTHON}"

  load_env_file "${ENV_FILE}"
  load_env_file "${CLASSIFIER_ENV_FILE}"

  SERVICE_URL="${SERVICE_URL:-http://127.0.0.1:${SERVICE_PORT:-8080}}"
  CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL:-${CLASSIFIER_API_URL:-http://127.0.0.1:4319}/health}"

  SERVICE_HEALTH_JSON="$(capture_service_json "/health")"
  REFRESH_STATUS_JSON="$(capture_service_json "/refresh/status")"

  if [[ -n "${CLASSIFIER_API_TOKEN}" ]]; then
    CLASSIFIER_HEALTH_JSON="$(capture_http_json "${CLASSIFIER_HEALTH_URL}" -H "X-API-Key: ${CLASSIFIER_API_TOKEN}")"
  else
    CLASSIFIER_HEALTH_JSON="$("${JSON_PYTHON}" - <<'PY'
import json
print(json.dumps({"ok": False, "error": "classifier-api-token-missing"}))
PY
)"
  fi

  CLASSIFICATION_JOB_COUNTS_JSON="$(capture_db_json "$(classification_job_counts_sql)")"
  CLASSIFICATION_STATE_COUNTS_JSON="$(capture_db_json "$(classification_state_counts_sql)")"
  PROVIDER_COUNTS_JSON="$(capture_db_json "$(provider_counts_sql)")"
  VAULT_COUNTS_JSON="$(collect_vault_counts_json)"

  export SERVICE_URL CLASSIFIER_HEALTH_URL VAULT_ROOT SUMMARY_JSON_PATH
  export SERVICE_HEALTH_JSON REFRESH_STATUS_JSON CLASSIFIER_HEALTH_JSON
  export CLASSIFICATION_JOB_COUNTS_JSON CLASSIFICATION_STATE_COUNTS_JSON
  export PROVIDER_COUNTS_JSON VAULT_COUNTS_JSON

  "${JSON_PYTHON}" - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def parse_json_env(name: str):
    raw = os.environ.get(name, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid-json", "raw": raw}


summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "service_url": os.environ["SERVICE_URL"],
    "classifier_health_url": os.environ["CLASSIFIER_HEALTH_URL"],
    "service_health": parse_json_env("SERVICE_HEALTH_JSON"),
    "refresh_status": parse_json_env("REFRESH_STATUS_JSON"),
    "classifier_health": parse_json_env("CLASSIFIER_HEALTH_JSON"),
    "classification_job_counts": parse_json_env("CLASSIFICATION_JOB_COUNTS_JSON"),
    "classification_state_counts": parse_json_env("CLASSIFICATION_STATE_COUNTS_JSON"),
    "provider_counts": parse_json_env("PROVIDER_COUNTS_JSON"),
    "vault_counts": parse_json_env("VAULT_COUNTS_JSON"),
}

summary_path = os.environ.get("SUMMARY_JSON_PATH", "").strip()
if summary_path:
    target = Path(summary_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(json.dumps(summary, indent=2, ensure_ascii=False))
PY

  if [[ -n "${SUMMARY_JSON_PATH}" ]]; then
    log_line "Wrote summary JSON to ${SUMMARY_JSON_PATH}"
  fi
}

main "$@"
