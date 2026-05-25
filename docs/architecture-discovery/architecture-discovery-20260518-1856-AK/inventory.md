# Architecture Discovery Inventory

Generated: 2026-05-18 18:56 AKDT

Scope:
- Read-only live discovery of `kayraspi` (`192.168.50.232`), `kayraspi2` (`192.168.50.86`), `tichuml1` (`192.168.50.196`), and `tichuml` (`192.168.50.36`)
- Supporting local repo inspection at `C:\Code\iCloudPlugin`, `C:\Code\random`, `C:\Code\calsync`, and `C:\Code\local-doc-classifier`
- One user-supplied Cloudflare DNS screenshot, treated as screenshot-derived evidence rather than live API truth

Sanitization:
- No passwords, tokens, private keys, cookies, or secret-bearing config bodies are included
- Cloudflare is in scope, but only non-secret routing facts are captured
- Anything not directly proven by live command output is marked `unverified`

## Host Status

| Host | Verified IPs | Reachability | OS | Primary role | High-signal findings |
| --- | --- | --- | --- | --- | --- |
| `kayraspi` | `192.168.50.232`, `192.168.50.235`, `100.96.90.42` | SSH verified | Debian 13, aarch64 | iCloud/app Pi | `iCloudPlugin` is live on `8080`; Docker also exposes Postgres `5432` and NxFilter on `89/8090`; `/srv/cloud-vault` is an NFS read-only mount from `kayraspi2` |
| `kayraspi2` | `192.168.50.86`, `192.168.50.88` | SSH verified | Debian 13, aarch64 | Vault/share/proxy Pi | `/srv/cloud-vault` is the primary 3.6T ext4 store; NFS export to `tichuml1` and read-only NFS export to `kayraspi`; Samba share `[cloud-vault]`; Caddy proxies public hostnames |
| `tichuml1` | `192.168.50.196` | SSH verified | Ubuntu 25.10, x86_64 | Classifier host | `local-doc-classifier-api` container is up on `4319`; port `4319` is reachable, but `/health` timed out and remains `unverified`; NFS mount from `kayraspi2` is present at `/mnt/cloud-vault` |
| `tichuml` | `192.168.50.36` | SSH verified | Ubuntu 24.04.4, x86_64 | Legacy/secondary tichu host | `tichu-postgres` is running on `54329`; `tichuml` directories exist, but no `4310` backend listener was found |

## Biggest Current-State Findings

- The live three-host document pipeline is confirmed as:
  `kayraspi` (`iCloudPlugin`) -> `tichuml1` (`local-doc-classifier`) -> `kayraspi2` (`/srv/cloud-vault`)
- `kayraspi2` is the clear storage and sharing anchor:
  local disk at `/srv/cloud-vault`, NFS exports, SMB share, iPhone backup timers, `usbmuxd`, and the only confirmed `80/443` reverse proxy
- `tichuml1` is carrying both the classifier and a `tichu-postgres` container, but the expected `tichuml` backend on `4310` was not present during this sweep
- `tichuml` (`192.168.50.36`) appears to be a partial or older tichu deployment:
  repo directories exist and Postgres is up, but the application backend was absent on both `4310` and `4319`
- Cloudflare-facing routing is partly confirmed from live Caddy config on `kayraspi2`:
  `classify` -> `192.168.50.196:4319`, `clouddrive` -> `192.168.50.232:8080`, `calsync` -> `192.168.50.232:3080`, `home` -> static response
- `calsync` currently has a local repo and a public proxy route, but no live listener was found on `192.168.50.232:3080`

## Verification Boundaries

- No primary target host was unreachable; all four answered over SSH
- `192.168.50.83` was not probed because `192.168.50.36` was reachable and confirmed its hostname as `tichuml`
- `192.168.50.128` was not probed because the requested conditions for needing it were not met
- Cloudflare screenshot data was not validated against the Cloudflare API or public DNS during this run
- `tichuml1` classifier health remains `unverified` because repeated `curl` probes to `127.0.0.1:4319/health` timed out even though the port is listening and the container is up

## Local Repo Signals

- `C:\Code\iCloudPlugin`
  local repo exists; code defaults point the service at `127.0.0.1:8080` and classifier submission at `192.168.50.196:4319`
- `C:\Code\local-doc-classifier`
  local repo exists; compose and docs expect API port `4319`
- `C:\Code\calsync`
  local repo exists; docs describe a FastAPI/Postgres/worker stack with default `APP_PORT=3080`
- `C:\Code\random`
  local repo exists, but no live runtime tie-in was proven during this discovery

## Artifact Set

- `inventory.csv`
- `host-kayraspi.md`
- `host-kayraspi2.md`
- `host-tichuml1.md`
- `host-tichuml.md`
- `service-map.md`
- `storage-and-shares.md`
- `application-map.md`
- `network-topology.mmd`
- `architecture-discovery-report.md`
