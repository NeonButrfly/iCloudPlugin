#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/deploy/roles/classifier/.env.live}"
READINESS_HELPER="${READINESS_HELPER:-${SCRIPT_DIR}/report_codex_arbiter_readiness.sh}"
JSON_PYTHON="${JSON_PYTHON:-python3}"

SOURCE_RELATIVE_PATH=""
CANONICAL_SOURCE_PATH=""
CATEGORIES=""
JSON_OUT=""
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-900}"
ATTACH_ORIGINALS="false"
NO_VISION="false"
ENABLE_CODEX_ARBITER_OVERRIDE="true"

usage() {
  cat <<'EOF'
Usage: run_codex_arbiter_smoke.sh --source-relative-path <provider/path/file.ext> [options]

Options:
  --source-relative-path PATH     Provider-relative path under the shared source root (required)
  --canonical-source-path PATH    Canonical source path stored in the generated note
  --categories CSV                Optional classifier category subset
  --json-out PATH                 Write the combined smoke artifact to this file
  --request-timeout-seconds N     Bound the classifier API request time (default: 900)
  --attach-originals              Request attachment-copy behavior for this smoke run
  --no-vision                     Disable vision fallback during the smoke request
  --no-arbiter-override           Do not force-enable the Codex arbiter for this one request
  --help                          Show this help
EOF
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

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

normalize_relative_path() {
  "${JSON_PYTHON}" - "$1" <<'PY'
import sys

value = (sys.argv[1] if len(sys.argv) > 1 else "").strip().replace("\\", "/").lstrip("/")
if not value or value in {".", ".."}:
    raise SystemExit(1)
parts = value.split("/")
if any(part in {"", ".", ".."} for part in parts):
    raise SystemExit(1)
print(value)
PY
}

bool_json() {
  case "${1}" in
    true|TRUE|1|yes|YES|on|ON) printf 'true' ;;
    *) printf 'false' ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-relative-path)
      SOURCE_RELATIVE_PATH="${2:-}"
      shift 2
      ;;
    --canonical-source-path)
      CANONICAL_SOURCE_PATH="${2:-}"
      shift 2
      ;;
    --categories)
      CATEGORIES="${2:-}"
      shift 2
      ;;
    --json-out)
      JSON_OUT="${2:-}"
      shift 2
      ;;
    --request-timeout-seconds)
      REQUEST_TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --attach-originals)
      ATTACH_ORIGINALS="true"
      shift
      ;;
    --no-vision)
      NO_VISION="true"
      shift
      ;;
    --no-arbiter-override)
      ENABLE_CODEX_ARBITER_OVERRIDE="false"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_command curl
require_command "${JSON_PYTHON}"
load_env_file "${ENV_FILE}"

if [[ ! -x "${READINESS_HELPER}" ]]; then
  echo "Readiness helper is missing or not executable: ${READINESS_HELPER}" >&2
  exit 1
fi

if [[ -z "${SOURCE_RELATIVE_PATH}" ]]; then
  echo "--source-relative-path is required" >&2
  usage >&2
  exit 1
fi

SOURCE_RELATIVE_PATH="$(normalize_relative_path "${SOURCE_RELATIVE_PATH}")" || {
  echo "Source relative path must stay inside the shared source root" >&2
  exit 1
}

CLASSIFIER_API_PORT="${CLASSIFIER_API_PORT:-4319}"
CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL:-http://127.0.0.1:${CLASSIFIER_API_PORT}/health}"
CLASSIFIER_CLASSIFY_URL="${CLASSIFIER_CLASSIFY_URL:-http://127.0.0.1:${CLASSIFIER_API_PORT}/classify/source}"
ICLOUD_MIRROR_ROOT="${ICLOUD_MIRROR_ROOT:-/srv/cloud-vault/mirrors}"

if [[ -z "${CANONICAL_SOURCE_PATH}" ]]; then
  CANONICAL_SOURCE_PATH="${ICLOUD_MIRROR_ROOT%/}/${SOURCE_RELATIVE_PATH}"
fi

if [[ -z "${CLASSIFIER_API_TOKEN:-}" ]]; then
  echo "CLASSIFIER_API_TOKEN is required to run the smoke classification." >&2
  exit 1
fi

READINESS_JSON="$(ENV_FILE="${ENV_FILE}" CLASSIFIER_HEALTH_URL="${CLASSIFIER_HEALTH_URL}" "${READINESS_HELPER}")"

OVERRIDE_JSON="$(bool_json "${ENABLE_CODEX_ARBITER_OVERRIDE}")"
READINESS_CHECK="$("${JSON_PYTHON}" - "${READINESS_JSON}" "${OVERRIDE_JSON}" <<'PY'
import json
import sys

readiness = json.loads(sys.argv[1])
override_enabled = sys.argv[2].strip().lower() == "true"
codex = readiness.get("codex_arbiter", {})
errors = []
if override_enabled:
    if not codex.get("cli_available"):
        errors.append("codex-cli-unavailable")
    if not codex.get("auth_present"):
        errors.append("codex-auth-missing")
print(json.dumps({"override_enabled": override_enabled, "errors": errors}))
PY
)"

READINESS_ERRORS="$("${JSON_PYTHON}" - "${READINESS_CHECK}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
print("\n".join(payload.get("errors", [])))
PY
)"

if [[ -n "${READINESS_ERRORS}" ]]; then
  echo "Codex arbiter smoke preflight failed:" >&2
  while IFS= read -r readiness_error; do
    [[ -n "${readiness_error}" ]] || continue
    printf '  - %s\n' "${readiness_error}" >&2
  done <<< "${READINESS_ERRORS}"
  exit 1
fi

curl_args=(
  -fsS
  --max-time "${REQUEST_TIMEOUT_SECONDS}"
  -H "X-API-Key: ${CLASSIFIER_API_TOKEN}"
  -F "source_relative_path=${SOURCE_RELATIVE_PATH}"
  -F "canonical_source_path=${CANONICAL_SOURCE_PATH}"
  -F "ingestion_mode=real-folder"
  -F "attach_originals=${ATTACH_ORIGINALS}"
  -F "no_vision=${NO_VISION}"
)

if [[ -n "${CATEGORIES}" ]]; then
  curl_args+=(-F "categories=${CATEGORIES}")
fi

if [[ "${ENABLE_CODEX_ARBITER_OVERRIDE}" == "true" ]]; then
  curl_args+=(-F "enable_codex_arbiter_override=true")
fi

CLASSIFY_JSON="$(curl "${curl_args[@]}" "${CLASSIFIER_CLASSIFY_URL}")"

combined_json="$("${JSON_PYTHON}" - "${READINESS_JSON}" "${CLASSIFY_JSON}" "${SOURCE_RELATIVE_PATH}" "${CANONICAL_SOURCE_PATH}" "${ENV_FILE}" "${CLASSIFIER_CLASSIFY_URL}" "${ATTACH_ORIGINALS}" "${NO_VISION}" "${OVERRIDE_JSON}" "${CATEGORIES}" <<'PY'
import json
import sys
from datetime import datetime, timezone

readiness = json.loads(sys.argv[1])
response = json.loads(sys.argv[2])

payload = {
    "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "env_file": sys.argv[5],
    "classifier_classify_url": sys.argv[6],
    "request": {
        "source_relative_path": sys.argv[3],
        "canonical_source_path": sys.argv[4],
        "attach_originals": sys.argv[7].strip().lower() == "true",
        "no_vision": sys.argv[8].strip().lower() == "true",
        "enable_codex_arbiter_override": sys.argv[9].strip().lower() == "true",
        "categories": sys.argv[10] or None,
    },
    "readiness": readiness,
    "response": response,
}

print(json.dumps(payload, indent=2))
PY
)"

if [[ -n "${JSON_OUT}" ]]; then
  mkdir -p "$(dirname "${JSON_OUT}")"
  printf '%s\n' "${combined_json}" > "${JSON_OUT}"
fi

printf '%s\n' "${combined_json}"
