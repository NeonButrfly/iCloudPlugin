#!/usr/bin/env bash
set -euo pipefail

VAULT_MOUNT="${VAULT_MOUNT:-/srv/cloud-vault}"
LOG_DIR="${LOG_DIR:-${VAULT_MOUNT}/logs}"
LOCK_DIR="${LOCK_DIR:-${VAULT_MOUNT}/.locks}"
LOCK_FILE="${LOCK_FILE:-${LOCK_DIR}/sync.lock}"
STATE_DIR="${STATE_DIR:-${VAULT_MOUNT}/.rclone-bisync}"

REMOTE_ICLOUD="${REMOTE_ICLOUD:-icloud}"
REMOTE_GOOGLE_1="${REMOTE_GOOGLE_1:-gdrive1}"
REMOTE_GOOGLE_2="${REMOTE_GOOGLE_2:-gdrive2}"
REMOTE_ICLOUD_INITIAL_RESYNC_MODE="${REMOTE_ICLOUD_INITIAL_RESYNC_MODE:-path2}"
REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE="${REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE:-path1}"
REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE="${REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE:-path1}"

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

log_line() {
  local log_file="$1"
  shift
  printf '%s %s\n' "$(date -Is)" "$*" >> "${log_file}"
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
  local workdir="${STATE_DIR}/${remote_name}"

  if ! remote_is_configured "${remote_name}"; then
    log_line "${log_file}" "Remote ${remote_name} is not configured. Skipping."
    return 0
  fi

  if ! remote_is_reachable "${remote_name}"; then
    log_line "${log_file}" "Remote ${remote_name} is configured but not reachable. Skipping."
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
    return 0
  fi

  log_line "${log_file}" "===== ${remote_name} bisync finished ====="
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

  run_bisync "${REMOTE_ICLOUD}" "${REMOTE_ICLOUD}:" "${VAULT_MOUNT}/mirrors/icloud" "${LOG_DIR}/icloud.log" "${REMOTE_ICLOUD_INITIAL_RESYNC_MODE}"
  run_bisync "${REMOTE_GOOGLE_1}" "${REMOTE_GOOGLE_1}:" "${VAULT_MOUNT}/mirrors/google1" "${LOG_DIR}/google1.log" "${REMOTE_GOOGLE_1_INITIAL_RESYNC_MODE}"
  run_bisync "${REMOTE_GOOGLE_2}" "${REMOTE_GOOGLE_2}:" "${VAULT_MOUNT}/mirrors/google2" "${LOG_DIR}/google2.log" "${REMOTE_GOOGLE_2_INITIAL_RESYNC_MODE}"

) 9>"${LOCK_FILE}"
