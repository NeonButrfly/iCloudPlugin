#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-icloudplugin}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/deploy/roles/cloudsync/docker-compose.yml}"
CLASSIFICATION_SERVICE="${CLASSIFICATION_SERVICE:-classification-worker}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-icloud}"
POSTGRES_DB="${POSTGRES_DB:-icloud_index}"

FOCUS_PREFIX="${FOCUS_PREFIX:-}"
DEFER_PREFIX="${DEFER_PREFIX:-}"
CONCURRENCY="${CONCURRENCY:-2}"
MAX_POLLS="${MAX_POLLS:-3}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-0.1}"
WORKER_TIMEOUT_SECONDS="${WORKER_TIMEOUT_SECONDS:-1200}"
QUEUE_LIMIT="${QUEUE_LIMIT:-15}"
RECENT_LIMIT="${RECENT_LIMIT:-12}"
LIVE_SUMMARY_LIMIT="${LIVE_SUMMARY_LIMIT:-10}"
DRY_RUN="${DRY_RUN:-0}"
RUN_LIVE_SUMMARY="${RUN_LIVE_SUMMARY:-0}"
TEMP_DEFER_ERROR="${TEMP_DEFER_ERROR:-Temporarily deferred to prioritize targeted bounded batch helper.}"

DEFER_APPLIED=0
WORKER_EXIT_STATUS=0

usage() {
  cat <<'EOF'
Usage: run_targeted_classification_batch.sh [options]

Runs one bounded classification-worker pass and optionally defers one queued
path prefix so another prefix claims first.

Options:
  --focus-prefix PATH         Prefix to highlight in queued/completed summaries.
  --defer-prefix PATH         Prefix to temporarily defer while the batch runs.
  --concurrency N             Worker submission concurrency. Default: 2
  --max-polls N               Worker max polls. Default: 3
  --poll-interval SECONDS     Worker poll interval seconds. Default: 0.1
  --worker-timeout SECONDS    Timeout for the one-shot worker command. Default: 1200
  --queue-limit N             Number of queued rows to display. Default: 15
  --recent-limit N            Number of recent completed rows to display. Default: 12
  --live-summary-limit N      Number of newest completed rows in live summary mode. Default: 10
  --run-live-summary          Print a global newest-completed summary after the batch.
  --dry-run                   Show what would run without mutating queue state.
  --help                      Show this help text.

Examples:
  FOCUS_PREFIX=/icloud/Scanned/ DEFER_PREFIX=/icloud/Downloads/ \
    ./deploy/roles/cloudsync/run_targeted_classification_batch.sh

  ./deploy/roles/cloudsync/run_targeted_classification_batch.sh \
    --focus-prefix /icloud/Scanned/ \
    --defer-prefix /icloud/Downloads/ \
    --max-polls 2
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

assert_safe_sql_literal() {
  local value="$1"
  if [[ "${value}" == *"'"* ]]; then
    fail "Single quotes are not supported in SQL-bound prefixes: ${value}"
  fi
}

docker_compose() {
  docker compose \
    -p "${COMPOSE_PROJECT}" \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    "$@"
}

psql_exec() {
  local sql="$1"
  docker_compose exec -T "${POSTGRES_SERVICE}" \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "${sql}"
}

queued_preview_sql() {
  local where_clause=""
  if [[ -n "${FOCUS_PREFIX}" ]]; then
    where_clause=" and f.path like '${FOCUS_PREFIX}%'"
  fi

  cat <<EOF
select cj.id, cj.priority_bucket, cj.priority_rank, cj.next_attempt_at, f.path
from classification_jobs cj
join files f on f.id = cj.file_id
where cj.status = 'queued'${where_clause}
order by cj.priority_rank asc, cj.id asc
limit ${QUEUE_LIMIT};
EOF
}

recent_completed_sql() {
  local where_clause=""
  if [[ -n "${FOCUS_PREFIX}" ]]; then
    where_clause=" and f.path like '${FOCUS_PREFIX}%'"
  fi

  cat <<EOF
select cs.id, f.path, cs.classifier_note_path
from classification_states cs
join files f on f.id = cs.file_id
where cs.submission_status = 'completed'${where_clause}
order by cs.id desc
limit ${RECENT_LIMIT};
EOF
}

overall_recent_completed_sql() {
  cat <<EOF
select cs.id, f.path, cs.classifier_note_path
from classification_states cs
join files f on f.id = cs.file_id
where cs.submission_status = 'completed'
order by cs.id desc
limit ${LIVE_SUMMARY_LIMIT};
EOF
}

print_queue_counts() {
  psql_exec \
    "select submission_status, count(*) from classification_states group by submission_status order by submission_status;"
}

print_focus_previews() {
  log_line "Queued preview${FOCUS_PREFIX:+ for ${FOCUS_PREFIX}}:"
  psql_exec "$(queued_preview_sql)"
  log_line "Recent completed preview${FOCUS_PREFIX:+ for ${FOCUS_PREFIX}}:"
  psql_exec "$(recent_completed_sql)"
}

print_live_summary() {
  if [[ "${RUN_LIVE_SUMMARY}" != "1" ]]; then
    return 0
  fi
  log_line "Recent completed rows overall:"
  psql_exec "$(overall_recent_completed_sql)"
}

apply_defer_prefix() {
  if [[ -z "${DEFER_PREFIX}" ]]; then
    return 0
  fi
  assert_safe_sql_literal "${DEFER_PREFIX}"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log_line "Dry run enabled; would temporarily defer queued jobs under ${DEFER_PREFIX}"
    return 0
  fi
  log_line "Temporarily deferring queued jobs under ${DEFER_PREFIX}"
  psql_exec \
    "update classification_jobs cj
     set next_attempt_at = now() + interval '2 hours',
         updated_at = now(),
         error_message = '${TEMP_DEFER_ERROR}'
     from files f
     where f.id = cj.file_id
       and cj.status = 'queued'
       and f.path like '${DEFER_PREFIX}%';"
  DEFER_APPLIED=1
}

clear_defer_prefix() {
  if [[ "${DEFER_APPLIED}" != "1" ]]; then
    return 0
  fi
  log_line "Restoring deferred queued jobs"
  psql_exec \
    "update classification_jobs
     set next_attempt_at = null,
         error_message = null,
         updated_at = now()
     where status = 'queued'
       and error_message = '${TEMP_DEFER_ERROR}';"
  DEFER_APPLIED=0
}

cleanup_worker_containers() {
  local ids
  ids="$(docker ps -aq --filter "name=${COMPOSE_PROJECT}-${CLASSIFICATION_SERVICE}-run")"
  if [[ -n "${ids}" ]]; then
    docker rm -f ${ids} >/dev/null
  fi
}

cleanup() {
  local exit_code=$?
  set +e
  clear_defer_prefix
  cleanup_worker_containers
  set -e
  return "${exit_code}"
}

trap cleanup EXIT

run_worker_pass() {
  local python_command
  local -a worker_command
  python_command="from icloud_index_service.classification_worker import run_classification_worker_loop; print(run_classification_worker_loop(max_polls=${MAX_POLLS}, poll_interval_seconds=${POLL_INTERVAL_SECONDS}))"
  worker_command=(
    docker compose
    -p "${COMPOSE_PROJECT}"
    --env-file "${ENV_FILE}"
    -f "${COMPOSE_FILE}"
    run --rm --no-deps
    -e "CLASSIFICATION_SUBMISSION_CONCURRENCY=${CONCURRENCY}"
    "${CLASSIFICATION_SERVICE}"
    uv run python -c "${python_command}"
  )

  if [[ "${DRY_RUN}" == "1" ]]; then
    log_line "Dry run enabled; skipping worker execution."
    return 0
  fi

  log_line "Starting bounded worker pass"
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout "${WORKER_TIMEOUT_SECONDS}s" "${worker_command[@]}"
    WORKER_EXIT_STATUS=$?
  else
    "${worker_command[@]}"
    WORKER_EXIT_STATUS=$?
  fi
  set -e

  if [[ "${WORKER_EXIT_STATUS}" == "124" ]]; then
    log_line "Worker command hit the timeout; verifying live DB state instead of failing."
    return 0
  fi

  if [[ "${WORKER_EXIT_STATUS}" != "0" ]]; then
    fail "Worker command failed with exit code ${WORKER_EXIT_STATUS}"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --focus-prefix)
        FOCUS_PREFIX="$2"
        shift 2
        ;;
      --defer-prefix)
        DEFER_PREFIX="$2"
        shift 2
        ;;
      --concurrency)
        CONCURRENCY="$2"
        shift 2
        ;;
      --max-polls)
        MAX_POLLS="$2"
        shift 2
        ;;
      --poll-interval)
        POLL_INTERVAL_SECONDS="$2"
        shift 2
        ;;
      --worker-timeout)
        WORKER_TIMEOUT_SECONDS="$2"
        shift 2
        ;;
      --queue-limit)
        QUEUE_LIMIT="$2"
        shift 2
        ;;
      --recent-limit)
        RECENT_LIMIT="$2"
        shift 2
        ;;
      --live-summary-limit)
        LIVE_SUMMARY_LIMIT="$2"
        shift 2
        ;;
      --run-live-summary)
        RUN_LIVE_SUMMARY="1"
        shift
        ;;
      --dry-run)
        DRY_RUN="1"
        shift
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
}

main() {
  parse_args "$@"

  require_command docker
  [[ -f "${ENV_FILE}" ]] || fail "Missing env file: ${ENV_FILE}"
  [[ -f "${COMPOSE_FILE}" ]] || fail "Missing compose file: ${COMPOSE_FILE}"

  assert_safe_sql_literal "${FOCUS_PREFIX}"
  assert_safe_sql_literal "${DEFER_PREFIX}"
  assert_safe_sql_literal "${TEMP_DEFER_ERROR}"

  log_line "Targeted bounded classification batch helper"
  log_line "Repo root: ${REPO_ROOT}"
  log_line "Focus prefix: ${FOCUS_PREFIX:-<all queued rows>}"
  log_line "Deferred prefix: ${DEFER_PREFIX:-<none>}"
  log_line "Concurrency: ${CONCURRENCY}; max polls: ${MAX_POLLS}; timeout: ${WORKER_TIMEOUT_SECONDS}s"

  log_line "Queue counts before:"
  print_queue_counts
  print_focus_previews

  apply_defer_prefix
  run_worker_pass

  log_line "Queue counts after:"
  print_queue_counts
  print_focus_previews
  print_live_summary
}

main "$@"
