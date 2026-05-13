#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${ICLOUDPLUGIN_ROOT:-/opt/iCloudPlugin}"
SERVICE_PORT="${SERVICE_PORT:-8080}"

cd "$REPO_ROOT"

docker compose up -d postgres service worker

docker compose exec -T postgres psql -U "${POSTGRES_USER:-icloud}" -d "${POSTGRES_DB:-icloud_index}" -v ON_ERROR_STOP=1 -c \
  "TRUNCATE TABLE extracted_contents, files, jobs, sync_runs RESTART IDENTITY CASCADE;"

curl -fsS -X POST "http://127.0.0.1:${SERVICE_PORT}/refresh"
printf '\n'
curl -fsS "http://127.0.0.1:${SERVICE_PORT}/refresh/status"
printf '\n'
