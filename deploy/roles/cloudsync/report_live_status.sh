#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/.env.live}"
CLASSIFIER_ENV_FILE="${CLASSIFIER_ENV_FILE:-${REPO_ROOT}/deploy/roles/classifier/.env.live}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-cloudsync}"
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
MIRROR_ROOT="${MIRROR_ROOT:-}"
CLOUD_VAULT_SYNC_STATUS_PATH="${CLOUD_VAULT_SYNC_STATUS_PATH:-/mnt/cloud-vault/logs/cloud-vault-sync-status.json}"
SUMMARY_JSON_PATH="${SUMMARY_JSON_PATH:-}"
JSON_PYTHON="${JSON_PYTHON:-python3}"
SUDO_PASSWORD="${SUDO_PASSWORD:-}"

PLUGIN_API_TOKEN="${PLUGIN_API_TOKEN:-}"
CLASSIFIER_API_TOKEN="${CLASSIFIER_API_TOKEN:-}"
ENV_FILE_CLASSIFIER_API_TOKEN="${ENV_FILE_CLASSIFIER_API_TOKEN:-}"
CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN="${CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN:-}"
EFFECTIVE_CLASSIFIER_API_TOKEN="${EFFECTIVE_CLASSIFIER_API_TOKEN:-}"
SERVICE_HEALTH_JSON='{}'
REFRESH_STATUS_JSON='{}'
CLASSIFIER_HEALTH_JSON='{}'
CLASSIFICATION_JOB_COUNTS_JSON='{}'
CLASSIFICATION_STATE_COUNTS_JSON='{}'
CLASSIFICATION_STATE_PATH_STATUS_JSON='[]'
PROVIDER_COUNTS_JSON='{}'
VAULT_COUNTS_JSON='{}'
GENERATED_NOTE_CONTEXT_JSON='{}'
CLOUD_VAULT_SYNC_STATUS_JSON='{}'
TOKEN_CONFIG_JSON='{}'

usage() {
  cat <<'EOF'
Usage: report_live_status.sh [options]

Print one unified cloud-vault live status report for the current compute host.

Options:
  --summary-json PATH         Write the machine-readable JSON report to PATH.
  --service-url URL          Override the cloudsync service base URL.
  --classifier-health-url URL Override the classifier health URL.
  --vault-root PATH          Override the vault root used for note counts.
  --mirror-root PATH         Override the mirror root used for generated-note context checks.
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

read_env_value() {
  local path="$1"
  local key="$2"
  if [[ ! -f "${path}" ]]; then
    return 0
  fi

  "${JSON_PYTHON}" - <<PY
from pathlib import Path

path = Path(${path@Q})
key = ${key@Q}
value = ""
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, raw_value = line.split("=", 1)
    if name.strip() != key:
        continue
    value = raw_value.strip().strip("'\"")
    break
print(value)
PY
}

collect_token_config_json() {
  local service_token_present=0
  local classifier_env_token_present=0
  local classifier_container_token_present=0
  local service_container_token_present=0
  local env_tokens_match=0
  local container_tokens_match=0
  local classifier_container_token=""
  local service_container_token=""

  [[ -n "${ENV_FILE_CLASSIFIER_API_TOKEN}" ]] && service_token_present=1
  [[ -n "${CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN}" ]] && classifier_env_token_present=1

  service_container_token="$(
    docker_command inspect cloudsync-service-1 --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null |
      awk -F= '/^CLASSIFIER_API_TOKEN=/{sub(/^CLASSIFIER_API_TOKEN=/,""); print; exit}'
  )"
  classifier_container_token="$(
    docker_command inspect cloud-vault-classifier-api --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null |
      awk -F= '/^CLASSIFIER_API_TOKEN=/{sub(/^CLASSIFIER_API_TOKEN=/,""); print; exit}'
  )"

  [[ -n "${service_container_token}" ]] && service_container_token_present=1
  [[ -n "${classifier_container_token}" ]] && classifier_container_token_present=1

  if [[ -n "${ENV_FILE_CLASSIFIER_API_TOKEN}" && -n "${CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN}" && "${ENV_FILE_CLASSIFIER_API_TOKEN}" == "${CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN}" ]]; then
    env_tokens_match=1
  fi
  if [[ -n "${service_container_token}" && -n "${classifier_container_token}" && "${service_container_token}" == "${classifier_container_token}" ]]; then
    container_tokens_match=1
  fi

  "${JSON_PYTHON}" - <<PY
import json
print(json.dumps({
    "cloudsync_env_token_present": ${service_token_present@Q} == "1",
    "classifier_env_token_present": ${classifier_env_token_present@Q} == "1",
    "service_container_token_present": ${service_container_token_present@Q} == "1",
    "classifier_container_token_present": ${classifier_container_token_present@Q} == "1",
    "env_tokens_match": ${env_tokens_match@Q} == "1",
    "container_tokens_match": ${container_tokens_match@Q} == "1",
    "effective_token_present": bool(${EFFECTIVE_CLASSIFIER_API_TOKEN@Q}),
}))
PY
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

collect_sync_status_json() {
  if [[ ! -f "${CLOUD_VAULT_SYNC_STATUS_PATH}" ]]; then
    "${JSON_PYTHON}" - <<PY
import json
print(json.dumps({
    "status_file": ${CLOUD_VAULT_SYNC_STATUS_PATH@Q},
    "status_file_present": False,
    "overall_status": "unknown",
}))
PY
    return 0
  fi

  "${JSON_PYTHON}" - <<PY
import json
from pathlib import Path

path = Path(${CLOUD_VAULT_SYNC_STATUS_PATH@Q})
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sync status payload is not a JSON object")
    payload = {
        "status_file": str(path),
        "status_file_present": True,
        **payload,
    }
except Exception as exc:
    payload = {
        "status_file": str(path),
        "status_file_present": True,
        "overall_status": "unknown",
        "error": "sync-status-invalid",
        "detail": str(exc),
    }

print(json.dumps(payload))
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

classification_state_status_by_path_sql() {
  cat <<'EOF'
select coalesce(
  json_agg(
    json_build_object(
      'path', f.path,
      'submission_status', cs.submission_status
    )
    order by f.path, cs.id
  ),
  '[]'::json
)
from classification_states cs
join files f on f.id = cs.file_id;
EOF
}

collect_generated_note_context_json() {
  export CLASSIFICATION_STATE_PATH_STATUS_JSON_PAYLOAD="${CLASSIFICATION_STATE_PATH_STATUS_JSON}"
  "${JSON_PYTHON}" - <<PY
import json
import os
from collections import defaultdict
from pathlib import Path, PurePosixPath

vault_root = Path(${VAULT_ROOT@Q}).resolve()
mirror_root = Path(${MIRROR_ROOT@Q}).resolve()
state_rows = json.loads(os.environ.get("CLASSIFICATION_STATE_PATH_STATUS_JSON_PAYLOAD", "[]") or "[]")

statuses_by_path = defaultdict(list)
if isinstance(state_rows, list):
    for row in state_rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path", "")).strip()
        status = str(row.get("submission_status", "")).strip()
        if path and status:
            statuses_by_path[path].append(status)

def iter_generated_notes():
    for root_name in ("01 Classified", "02 Needs Review"):
        note_root = vault_root / root_name
        if not note_root.exists():
            continue
        for note_path in note_root.rglob("*.md"):
            try:
                text = note_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            if not lines or lines[0].strip() != "---":
                continue
            end_index = None
            for index in range(1, len(lines)):
                if lines[index].strip() == "---":
                    end_index = index
                    break
            if end_index is None:
                continue
            metadata = {}
            for line in lines[1:end_index]:
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                key = key.strip()
                raw_value = raw_value.strip()
                try:
                    parsed = json.loads(raw_value)
                except json.JSONDecodeError:
                    parsed = raw_value.strip("'\"")
                if isinstance(parsed, str):
                    metadata[key] = parsed
            if metadata.get("type") != "classified-document":
                continue
            yield note_path, metadata

def candidate_roots():
    values = []
    for raw in (
        os.environ.get("ICLOUD_MIRROR_ROOT", ""),
        str(mirror_root),
        "/srv/cloud-vault/mirrors",
        "/mnt/cloud-vault/mirrors",
    ):
        cleaned = str(raw).strip().replace("\\\\", "/").rstrip("/")
        if not cleaned:
            continue
        path = PurePosixPath(cleaned)
        if path not in values:
            values.append(path)
    return values

def canonical_to_file_path(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    try:
        relative_path = Path(cleaned).resolve().relative_to(mirror_root.resolve())
    except Exception:
        normalized = cleaned.replace("\\\\", "/")
        source_posix = PurePosixPath(normalized)
        for root in candidate_roots():
            try:
                relative_posix = source_posix.relative_to(root)
            except ValueError:
                continue
            parts = [part for part in relative_posix.parts if part]
            if parts:
                return "/" + "/".join(parts)
        return ""
    parts = [part for part in relative_path.parts if part]
    return "/" + "/".join(parts) if parts else ""

def source_exists(value: str) -> bool:
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    candidate = Path(cleaned)
    if candidate.exists() and candidate.is_file():
        return True
    file_path = canonical_to_file_path(cleaned)
    if not file_path:
        return False
    candidate = (mirror_root / file_path.lstrip("/")).resolve()
    return candidate.exists() and candidate.is_file()

summary = {
    "vault_root": str(vault_root),
    "mirror_root": str(mirror_root),
    "total_generated_notes": 0,
    "notes_missing_any_context": 0,
    "notes_missing_source_parser": 0,
    "notes_missing_heuristic_primary_hint": 0,
    "notes_missing_hybrid_live_source": 0,
    "missing_context_with_matching_completed_state": 0,
    "missing_context_with_matching_queued_state": 0,
    "missing_context_with_matching_other_state": 0,
    "missing_context_without_matching_state": 0,
    "missing_context_source_file_present": 0,
    "missing_context_source_file_missing": 0,
}

if vault_root.exists() and vault_root.is_dir():
    for _, metadata in iter_generated_notes():
        summary["total_generated_notes"] += 1
        missing_parser = not str(metadata.get("source_parser", "")).strip()
        missing_heuristic = not str(metadata.get("heuristic_primary_hint", "")).strip()
        missing_live_source = not str(metadata.get("hybrid_live_source", "")).strip()
        if not (missing_parser or missing_heuristic or missing_live_source):
            continue
        summary["notes_missing_any_context"] += 1
        if missing_parser:
            summary["notes_missing_source_parser"] += 1
        if missing_heuristic:
            summary["notes_missing_heuristic_primary_hint"] += 1
        if missing_live_source:
            summary["notes_missing_hybrid_live_source"] += 1
        canonical_source_path = str(metadata.get("canonical_source_path", "")).strip()
        if source_exists(canonical_source_path):
            summary["missing_context_source_file_present"] += 1
        else:
            summary["missing_context_source_file_missing"] += 1
        file_path = canonical_to_file_path(canonical_source_path)
        matching_statuses = statuses_by_path.get(file_path, [])
        if any(status == "completed" for status in matching_statuses):
            summary["missing_context_with_matching_completed_state"] += 1
        elif any(status == "queued" for status in matching_statuses):
            summary["missing_context_with_matching_queued_state"] += 1
        elif matching_statuses:
            summary["missing_context_with_matching_other_state"] += 1
        else:
            summary["missing_context_without_matching_state"] += 1

print(json.dumps(summary))
PY
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
      --mirror-root)
        MIRROR_ROOT="$2"
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

  ENV_FILE_CLASSIFIER_API_TOKEN="$(read_env_value "${ENV_FILE}" "CLASSIFIER_API_TOKEN")"
  CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN="$(read_env_value "${CLASSIFIER_ENV_FILE}" "CLASSIFIER_API_TOKEN")"

  load_env_file "${ENV_FILE}"
  load_env_file "${CLASSIFIER_ENV_FILE}"

  SERVICE_URL="${SERVICE_URL:-http://127.0.0.1:${SERVICE_PORT:-8080}}"
  CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL:-${CLASSIFIER_API_URL:-http://127.0.0.1:4319}/health}"
  MIRROR_ROOT="${MIRROR_ROOT:-${ICLOUD_MIRROR_MOUNT_SOURCE:-/mnt/cloud-vault}/mirrors}"
  EFFECTIVE_CLASSIFIER_API_TOKEN="${CLASSIFIER_ENV_FILE_CLASSIFIER_API_TOKEN:-${ENV_FILE_CLASSIFIER_API_TOKEN:-${CLASSIFIER_API_TOKEN:-}}}"

  SERVICE_HEALTH_JSON="$(capture_service_json "/health")"
  REFRESH_STATUS_JSON="$(capture_service_json "/refresh/status")"

  if [[ -n "${EFFECTIVE_CLASSIFIER_API_TOKEN}" ]]; then
    CLASSIFIER_HEALTH_JSON="$(capture_http_json "${CLASSIFIER_HEALTH_URL}" -H "X-API-Key: ${EFFECTIVE_CLASSIFIER_API_TOKEN}")"
  else
    CLASSIFIER_HEALTH_JSON="$("${JSON_PYTHON}" - <<'PY'
import json
print(json.dumps({"ok": False, "error": "classifier-api-token-missing"}))
PY
)"
  fi
  TOKEN_CONFIG_JSON="$(collect_token_config_json)"

  CLASSIFICATION_JOB_COUNTS_JSON="$(capture_db_json "$(classification_job_counts_sql)")"
  CLASSIFICATION_STATE_COUNTS_JSON="$(capture_db_json "$(classification_state_counts_sql)")"
  CLASSIFICATION_STATE_PATH_STATUS_JSON="$(capture_db_json "$(classification_state_status_by_path_sql)")"
  PROVIDER_COUNTS_JSON="$(capture_db_json "$(provider_counts_sql)")"
  VAULT_COUNTS_JSON="$(collect_vault_counts_json)"
  GENERATED_NOTE_CONTEXT_JSON="$(collect_generated_note_context_json)"
  CLOUD_VAULT_SYNC_STATUS_JSON="$(collect_sync_status_json)"

  export SERVICE_URL CLASSIFIER_HEALTH_URL VAULT_ROOT MIRROR_ROOT SUMMARY_JSON_PATH
  export SERVICE_HEALTH_JSON REFRESH_STATUS_JSON CLASSIFIER_HEALTH_JSON
  export CLASSIFICATION_JOB_COUNTS_JSON CLASSIFICATION_STATE_COUNTS_JSON
  export PROVIDER_COUNTS_JSON VAULT_COUNTS_JSON GENERATED_NOTE_CONTEXT_JSON CLOUD_VAULT_SYNC_STATUS_JSON TOKEN_CONFIG_JSON

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
    "token_config": parse_json_env("TOKEN_CONFIG_JSON"),
    "classification_job_counts": parse_json_env("CLASSIFICATION_JOB_COUNTS_JSON"),
    "classification_state_counts": parse_json_env("CLASSIFICATION_STATE_COUNTS_JSON"),
    "provider_counts": parse_json_env("PROVIDER_COUNTS_JSON"),
    "vault_counts": parse_json_env("VAULT_COUNTS_JSON"),
    "generated_note_context_gaps": parse_json_env("GENERATED_NOTE_CONTEXT_JSON"),
    "cloud_vault_sync": parse_json_env("CLOUD_VAULT_SYNC_STATUS_JSON"),
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
