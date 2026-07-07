#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
SYNC_SCRIPT_SOURCE="${SYNC_SCRIPT_SOURCE:-${SCRIPT_DIR}/cloud-vault-sync.sh}"
GMAIL_EXPORT_SCRIPT_SOURCE="${GMAIL_EXPORT_SCRIPT_SOURCE:-${SCRIPT_DIR}/export_gmail_messages.py}"
SYNC_SERVICE_SOURCE="${SYNC_SERVICE_SOURCE:-${SCRIPT_DIR}/cloud-vault-sync.service}"
SYNC_TIMER_SOURCE="${SYNC_TIMER_SOURCE:-${SCRIPT_DIR}/cloud-vault-sync.timer}"

SCRIPT_TARGET="${SCRIPT_TARGET:-/usr/local/bin/cloud-vault-sync.sh}"
GMAIL_EXPORT_SCRIPT_TARGET="${GMAIL_EXPORT_SCRIPT_TARGET:-/usr/local/bin/cloud-vault-gmail-export.py}"
SERVICE_TARGET="${SERVICE_TARGET:-/etc/systemd/system/cloud-vault-sync.service}"
TIMER_TARGET="${TIMER_TARGET:-/etc/systemd/system/cloud-vault-sync.timer}"
SUDO_PASSWORD="${SUDO_PASSWORD:-}"
RUN_SYNC_AFTER_INSTALL="${RUN_SYNC_AFTER_INSTALL:-0}"

usage() {
  cat <<'EOF'
Usage: install_storage_host_sync_assets.sh [options]

Install or refresh the storage-host cloud-vault sync assets from the repo.

Options:
  --run-sync-after-install   Start the oneshot sync service immediately after the timer install/update.
  --help                     Show this help text.

Environment:
  REPO_ROOT                  Repo root used to resolve default asset paths.
  SUDO_PASSWORD              Optional sudo password for one-shot elevated runs.
  SCRIPT_TARGET              Override the installed script path.
  SERVICE_TARGET             Override the installed systemd service path.
  TIMER_TARGET               Override the installed systemd timer path.
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

sudo_command() {
  if sudo -n true >/dev/null 2>&1; then
    sudo -n "$@"
    return 0
  fi

  if [[ -n "${SUDO_PASSWORD}" ]]; then
    printf '%s\n' "${SUDO_PASSWORD}" | sudo -S "$@"
    return 0
  fi

  fail "This installer requires sudo. Use passwordless sudo or set SUDO_PASSWORD."
}

install_asset() {
  local source_path="$1"
  local target_path="$2"
  local mode="$3"
  [[ -f "${source_path}" ]] || fail "Missing source asset: ${source_path}"
  sudo_command install -m "${mode}" "${source_path}" "${target_path}"
}

print_installed_hashes() {
  local source_path="$1"
  local target_path="$2"
  local source_hash target_hash
  source_hash="$(sha256sum "${source_path}" | awk '{print $1}')"
  target_hash="$(sudo_command sha256sum "${target_path}" | awk '{print $1}')"
  printf '%s %s %s\n' "${target_path}" "${source_hash}" "${target_hash}"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-sync-after-install)
        RUN_SYNC_AFTER_INSTALL="1"
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

  require_command install
  require_command sha256sum
  require_command systemctl

  log_line "Installing storage-host cloud-vault sync assets"
  log_line "Repo root: ${REPO_ROOT}"

  install_asset "${SYNC_SCRIPT_SOURCE}" "${SCRIPT_TARGET}" 755
  install_asset "${GMAIL_EXPORT_SCRIPT_SOURCE}" "${GMAIL_EXPORT_SCRIPT_TARGET}" 755
  install_asset "${SYNC_SERVICE_SOURCE}" "${SERVICE_TARGET}" 644
  install_asset "${SYNC_TIMER_SOURCE}" "${TIMER_TARGET}" 644

  sudo_command systemctl daemon-reload
  sudo_command systemctl enable --now "$(basename "${TIMER_TARGET}")"

  if [[ "${RUN_SYNC_AFTER_INSTALL}" == "1" ]]; then
    sudo_command systemctl start "$(basename "${SERVICE_TARGET}")"
  fi

  log_line "Installed asset hashes (target source_sha installed_sha):"
  print_installed_hashes "${SYNC_SCRIPT_SOURCE}" "${SCRIPT_TARGET}"
  print_installed_hashes "${GMAIL_EXPORT_SCRIPT_SOURCE}" "${GMAIL_EXPORT_SCRIPT_TARGET}"
  print_installed_hashes "${SYNC_SERVICE_SOURCE}" "${SERVICE_TARGET}"
  print_installed_hashes "${SYNC_TIMER_SOURCE}" "${TIMER_TARGET}"

  log_line "Timer status:"
  sudo_command systemctl status "$(basename "${TIMER_TARGET}")" --no-pager --lines=5

  if [[ "${RUN_SYNC_AFTER_INSTALL}" == "1" ]]; then
    log_line "Service status:"
    sudo_command systemctl status "$(basename "${SERVICE_TARGET}")" --no-pager --lines=5 || true
  fi
}

main "$@"
