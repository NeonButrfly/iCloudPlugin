#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.live}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-icloudplugin}"
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/docker-compose.yml}"
HOST_SUMMARY_DIR="${HOST_SUMMARY_DIR:-${SCRIPT_DIR}/logs/learning-maintenance}"
SUMMARY_JSON="${SUMMARY_JSON:-/logs/learning-maintenance/learning-maintenance-$(date -u +%Y%m%dT%H%M%SZ).json}"

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

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

load_env_file "${ENV_FILE}"
require_command docker
mkdir -p "${HOST_SUMMARY_DIR}"

EXTRA_ARGS=()
if [[ "${LEARNING_MAINTENANCE_TRAIN_FROM_INDEX:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  EXTRA_ARGS+=(--train-from-index)
fi
if [[ -n "${LEARNING_MAINTENANCE_DATABASE_URL:-}" ]]; then
  EXTRA_ARGS+=(--database-url "${LEARNING_MAINTENANCE_DATABASE_URL}")
fi
if [[ -n "${LEARNING_MAINTENANCE_MIN_ROWS:-}" ]]; then
  EXTRA_ARGS+=(--min-rows "${LEARNING_MAINTENANCE_MIN_ROWS}")
fi
if [[ -n "${LEARNING_MAINTENANCE_MIN_NEW_ROWS:-}" ]]; then
  EXTRA_ARGS+=(--min-new-rows "${LEARNING_MAINTENANCE_MIN_NEW_ROWS}")
fi

cd "${REPO_ROOT}"
docker compose \
  --project-name "${COMPOSE_PROJECT}" \
  --env-file "${ENV_FILE}" \
  -f "${COMPOSE_FILE}" \
  run --rm --no-deps classifier-api \
  python -m apps.classifier.learning_maintenance \
  --summary-json "${SUMMARY_JSON}" \
  "${EXTRA_ARGS[@]}"

echo "Wrote learning-maintenance summary: ${SUMMARY_JSON}"
