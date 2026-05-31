#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/classifier/.env.live}"
CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL:-}"
JSON_PYTHON="${JSON_PYTHON:-python3}"

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

capture_health_json() {
  if [[ -z "${CLASSIFIER_HEALTH_URL}" ]]; then
    return 0
  fi
  if [[ -z "${CLASSIFIER_API_TOKEN:-}" ]]; then
    printf '%s' '{"ok":false,"error":"classifier-api-token-missing"}'
    return 0
  fi
  if ! curl -fsS -H "X-API-Key: ${CLASSIFIER_API_TOKEN}" "${CLASSIFIER_HEALTH_URL}" 2>/dev/null; then
    printf '%s' '{"ok":false,"error":"health-request-failed"}'
  fi
}

load_env_file "${ENV_FILE}"
require_command "${JSON_PYTHON}"

CODEX_ARBITER_COMMAND="${CODEX_ARBITER_COMMAND:-codex exec}"
CODEX_ARBITER_TIMEOUT_SECONDS="${CODEX_ARBITER_TIMEOUT_SECONDS:-120}"
CLASSIFIER_API_PORT="${CLASSIFIER_API_PORT:-4319}"
CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL:-http://127.0.0.1:${CLASSIFIER_API_PORT}/health}"
CODEX_ARBITER_ENABLED="${CODEX_ARBITER_ENABLED:-0}"

first_token="${CODEX_ARBITER_COMMAND%% *}"
cli_path=""
if command -v "${first_token}" >/dev/null 2>&1; then
  cli_path="$(command -v "${first_token}")"
fi

auth_mode="missing"
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  auth_mode="api-key-env"
elif [[ -f "${HOME}/.codex/auth.json" ]]; then
  auth_mode="codex-auth-file"
fi

codex_enabled_python="False"
if [[ "${CODEX_ARBITER_ENABLED}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  codex_enabled_python="True"
fi

HEALTH_JSON="$(capture_health_json)"

"${JSON_PYTHON}" - <<PY
import json

health = {}
raw_health = ${HEALTH_JSON@Q}
if raw_health:
    try:
        health = json.loads(raw_health)
    except json.JSONDecodeError:
        health = {"ok": False, "error": "invalid-health-json"}

print(json.dumps({
    "env_file": ${ENV_FILE@Q},
    "codex_arbiter": {
        "enabled": ${codex_enabled_python},
        "command": ${CODEX_ARBITER_COMMAND@Q},
        "timeout_seconds": int(${CODEX_ARBITER_TIMEOUT_SECONDS@Q}),
        "cli_available": bool(${cli_path@Q}),
        "cli_path": ${cli_path@Q} or None,
        "auth_mode": ${auth_mode@Q},
        "auth_present": ${auth_mode@Q} != "missing",
    },
    "classifier_health_url": ${CLASSIFIER_HEALTH_URL@Q},
    "classifier_health": health,
}, indent=2))
PY
