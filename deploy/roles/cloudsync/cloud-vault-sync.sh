#!/usr/bin/env bash
set -euo pipefail

VAULT_MOUNT="${VAULT_MOUNT:-/srv/cloud-vault}"
LOG_DIR="${LOG_DIR:-${VAULT_MOUNT}/logs}"
STATUS_DIR="${STATUS_DIR:-${LOG_DIR}}"
STATUS_FILE="${STATUS_FILE:-${STATUS_DIR}/cloud-vault-sync-status.json}"
LOCK_DIR="${LOCK_DIR:-${VAULT_MOUNT}/.locks}"
LOCK_FILE="${LOCK_FILE:-${LOCK_DIR}/sync.lock}"
STATE_DIR="${STATE_DIR:-${VAULT_MOUNT}/.rclone-bisync}"
STATUS_PYTHON="${STATUS_PYTHON:-python3}"

REMOTE_ICLOUD="${REMOTE_ICLOUD:-icloud}"
REMOTE_GOOGLE_1="${REMOTE_GOOGLE_1:-gdrive1}"
REMOTE_GOOGLE_2="${REMOTE_GOOGLE_2:-gdrive2}"
REMOTE_ICLOUD_INITIAL_RESYNC_MODE="${REMOTE_ICLOUD_INITIAL_RESYNC_MODE:-path2}"
REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE="${REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE:-path1}"
REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE="${REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE:-path1}"
REMOTE_ICLOUD_REQUIRED="${REMOTE_ICLOUD_REQUIRED:-true}"
REMOTE_GOOGLE_1_REQUIRED="${REMOTE_GOOGLE_1_REQUIRED:-false}"
REMOTE_GOOGLE_2_REQUIRED="${REMOTE_GOOGLE_2_REQUIRED:-false}"

CHECK_FILENAME="${CHECK_FILENAME:-RCLONE_TEST}"
RCLONE_COMMON_ARGS=(
  --create-empty-src-dirs
  --check-access
  --check-filename "${CHECK_FILENAME}"
  --compare size,modtime
  --conflict-resolve newer
  --drive-skip-dangling-shortcuts
  --resilient
  --recover
)

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${STATE_DIR}"
SYNC_STATUS_ROWS_FILE="$(mktemp "${LOCK_DIR%/}/sync-status-XXXXXX.tsv")"
RUN_STARTED_AT="$(date -Is)"

log_line() {
  local log_file="$1"
  shift
  printf '%s %s\n' "$(date -Is)" "$*" >> "${log_file}"
}

record_sync_status() {
  local remote_name="$1"
  local required_flag="$2"
  local sync_status="$3"
  local log_file="$4"
  local detail="$5"
  local recorded_at
  recorded_at="$(date -Is)"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${remote_name}" \
    "${required_flag}" \
    "${sync_status}" \
    "${log_file}" \
    "${detail//$'\t'/ }" \
    "${recorded_at}" >> "${SYNC_STATUS_ROWS_FILE}"
}

write_sync_status_file() {
  local run_exit_code="${1:-0}"
  STATUS_FILE="${STATUS_FILE}" \
  STATUS_ROWS_FILE="${SYNC_STATUS_ROWS_FILE}" \
  RUN_STARTED_AT="${RUN_STARTED_AT}" \
  RUN_FINISHED_AT="$(date -Is)" \
  RUN_EXIT_CODE="${run_exit_code}" \
  VAULT_MOUNT="${VAULT_MOUNT}" \
  STATUS_PYTHON="${STATUS_PYTHON}" \
  "${STATUS_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

status_file = Path(os.environ["STATUS_FILE"])
rows_file = Path(os.environ["STATUS_ROWS_FILE"])
run_exit_code = int(os.environ.get("RUN_EXIT_CODE", "0") or "0")

entries = []
if rows_file.exists():
    for raw_line in rows_file.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        remote_name, required_flag, sync_status, log_file, detail, recorded_at = raw_line.split("\t", 5)
        entries.append(
            {
                "remote_name": remote_name,
                "required": required_flag.strip().lower() in {"1", "true", "yes", "on"},
                "status": sync_status,
                "log_file": log_file,
                "detail": detail,
                "recorded_at": recorded_at,
            }
        )

degraded_statuses = {"failed", "unreachable"}
required_failure_statuses = degraded_statuses | {"not-configured"}
degraded_remotes = []
required_failures = []

for entry in entries:
    status = entry["status"]
    required = bool(entry["required"])
    if status in degraded_statuses or (required and status in required_failure_statuses):
        degraded_remotes.append(entry["remote_name"])
    if required and status in required_failure_statuses:
        required_failures.append(entry["remote_name"])

overall_status = "ok"
if run_exit_code != 0:
    overall_status = "failed"
elif degraded_remotes:
    overall_status = "degraded"

payload = {
    "generated_at": os.environ.get("RUN_FINISHED_AT", ""),
    "started_at": os.environ.get("RUN_STARTED_AT", ""),
    "finished_at": os.environ.get("RUN_FINISHED_AT", ""),
    "overall_status": overall_status,
    "run_exit_code": run_exit_code,
    "required_failures_present": bool(required_failures),
    "degraded_remotes": degraded_remotes,
    "required_failure_remotes": required_failures,
    "vault_mount": os.environ.get("VAULT_MOUNT", ""),
    "status_file": str(status_file),
    "remote_statuses": entries,
}

status_file.parent.mkdir(parents=True, exist_ok=True)
status_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

remote_is_configured() {
  local remote_name="$1"
  rclone listremotes | grep -qx "${remote_name}:"
}

remote_is_reachable() {
  local remote_name="$1"
  timeout 45 rclone lsf "${remote_name}:" --max-depth 1 >/dev/null 2>&1
}

run_bisync() {
  local remote_name="$1"
  local remote_path="$2"
  local dest_path="$3"
  local log_file="$4"
  local initial_resync_mode="$5"
  local required_flag="$6"
  local workdir="${STATE_DIR}/${remote_name}"

  if ! remote_is_configured "${remote_name}"; then
    local detail="Remote ${remote_name} is not configured. Skipping."
    log_line "${log_file}" "${detail}"
    record_sync_status "${remote_name}" "${required_flag}" "not-configured" "${log_file}" "${detail}"
    return 0
  fi

  if ! remote_is_reachable "${remote_name}"; then
    local detail="Remote ${remote_name} is configured but not reachable. Skipping."
    log_line "${log_file}" "${detail}"
    record_sync_status "${remote_name}" "${required_flag}" "unreachable" "${log_file}" "${detail}"
    return 0
  fi

  mkdir -p "${dest_path}" "${workdir}"

  if [[ ! -f "${dest_path}/${CHECK_FILENAME}" ]]; then
    printf 'cloud-vault-check\n' > "${dest_path}/${CHECK_FILENAME}"
  fi

  # The first bisync run needs a baseline listing. Existing local mirrors such
  # as iCloud can prefer path2, while newly connected remotes should prefer
  # path1 so an empty local mirror does not become the source of truth.
  local bisync_args=("${RCLONE_COMMON_ARGS[@]}" --workdir "${workdir}")
  if ! compgen -G "${workdir}/*.lst" > /dev/null; then
    bisync_args+=(--resync --resync-mode "${initial_resync_mode}")
    log_line "${log_file}" "No bisync state found for ${remote_name}. Running initial resync with ${initial_resync_mode} preferred."
  fi

  log_line "${log_file}" "===== ${remote_name} bisync started ====="
  if ! rclone bisync "${remote_path}" "${dest_path}" \
    "${bisync_args[@]}" \
    --log-file "${log_file}" \
    --log-level INFO; then
    log_line "${log_file}" "===== ${remote_name} bisync failed ====="
    record_sync_status "${remote_name}" "${required_flag}" "failed" "${log_file}" "rclone bisync failed"
    return 0
  fi

  log_line "${log_file}" "===== ${remote_name} bisync finished ====="
  record_sync_status "${remote_name}" "${required_flag}" "ok" "${log_file}" "rclone bisync finished"
}

if ! mountpoint -q "${VAULT_MOUNT}"; then
  echo "$(date -Is) Vault mount is not mounted at ${VAULT_MOUNT}." >&2
  exit 1
fi

(
  flock -n 9 || {
    echo "$(date -Is) Previous sync is still running. Exiting."
    exit 0
  }

  run_bisync "${REMOTE_ICLOUD}" "${REMOTE_ICLOUD}:" "${VAULT_MOUNT}/mirrors/icloud" "${LOG_DIR}/icloud.log" "${REMOTE_ICLOUD_INITIAL_RESYNC_MODE}" "${REMOTE_ICLOUD_REQUIRED}"
  run_bisync "${REMOTE_GOOGLE_1}" "${REMOTE_GOOGLE_1}:" "${VAULT_MOUNT}/mirrors/google1" "${LOG_DIR}/google1.log" "${REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE}" "${REMOTE_GOOGLE_1_REQUIRED}"
  run_bisync "${REMOTE_GOOGLE_2}" "${REMOTE_GOOGLE_2}:" "${VAULT_MOUNT}/mirrors/google2" "${LOG_DIR}/google2.log" "${REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE}" "${REMOTE_GOOGLE_2_REQUIRED}"
  write_sync_status_file 0

) 9>"${LOCK_FILE}"
