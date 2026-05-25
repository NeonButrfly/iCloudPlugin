# Service Map

## Document And File Pipeline

### iCloud ingestion

- Live host: `kayraspi` (`192.168.50.232`)
- Runtime evidence:
  Docker compose project `icloudplugin`
- Confirmed ports:
  `8080` for service, `5432` for its Postgres
- Health:
  `http://127.0.0.1:8080/health` returned `200 OK`
- Dependency:
  local repo code points classifier submission to `http://192.168.50.196:4319/classify/upload`

### Classification

- Live host: `tichuml1` (`192.168.50.196`)
- Runtime evidence:
  `local-doc-classifier-api` container published on `4319`
- Dependency:
  writes into shared storage mounted from `kayraspi2`
- Health:
  TCP listener verified, but `/health` timed out and remains `unverified`

### Vault and shares

- Live host: `kayraspi2` (`192.168.50.86`)
- Runtime evidence:
  local ext4 volume mounted at `/srv/cloud-vault`
- NFS clients:
  `tichuml1` mounts it read-write at `/mnt/cloud-vault`
  `kayraspi` mounts it read-only at `/srv/cloud-vault`
- SMB share:
  `[cloud-vault]` on the same backing path

## Public Reverse Proxy And Cloudflare-Related Routing

Confirmed from live Caddy config on `kayraspi2`:

| Public hostname | Reverse proxy target | Current state |
| --- | --- | --- |
| `home.neonbutterfly.net` | static response on Caddy | verified |
| `classify.neonbutterfly.net` | `192.168.50.196:4319` | target port listening; endpoint health unverified |
| `clouddrive.neonbutterfly.net` | `192.168.50.232:8080` | verified |
| `calsync.neonbutterfly.net` | `192.168.50.232:3080` | upstream absent during probe |

Supporting Cloudflare facts:
- User-supplied screenshot showed proxied records for `calsync`, `classify`, `clouddrive`, `home`, and the apex zone
- `kayraspi` also runs a `cloudflare-ddns.timer`

## Calendar Service

### calsync

- Local repo exists at `C:\Code\calsync`
- Repo docs describe:
  FastAPI + PostgreSQL + worker + Docker Compose
- Default app port from repo docs:
  `3080`
- Public-facing route exists in Caddy:
  `calsync.neonbutterfly.net` -> `192.168.50.232:3080`
- Live runtime result:
  no listener found on `192.168.50.232:3080`
- Status:
  `unverified / likely down or not deployed on the probed hosts`

## Tichu-Related Services

### tichuml1

- Repo root exists at `/opt/tichuml`
- Live app backend on `4310` was not found
- `tichu-postgres` container is running on `54329`

### tichuml

- Repo roots exist at `/opt/tichuml` and `/tichuml`
- Live app backend on `4310` was not found
- `tichu-postgres` container is running on `54329`

Interpretation:
- Tichu-related code and database components are present on both Ubuntu hosts
- The expected HTTP backend was not live on either probed Tichu host during this run

## NxFilter

- `kayraspi`
  Docker container exposing `89` and `8090`
- `tichuml1`
  Docker container exposing `8444`
- `tichuml`
  systemd service exposing `8090`, `8943`, and NxFilter-related UDP/TCP ports

## Apple / Backup Tooling

- Primary host: `kayraspi2`
- Evidence:
  `usbmuxd.service`, `iphone-backup-if-connected.timer`, and backup directories under `/srv/cloud-vault`
- Supporting mounts:
  those backup directories are visible from `kayraspi` through the read-only NFS mount

## Remote Access

- SSH on all four hosts
- Tailscale on `kayraspi`
- RPi Connect on `kayraspi` and `kayraspi2`
- VNC on `kayraspi`
