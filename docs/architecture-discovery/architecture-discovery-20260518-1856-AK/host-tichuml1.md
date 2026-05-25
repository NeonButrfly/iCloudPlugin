# Host: tichuml1

Host verification:
- Confirmed hostname: `tichuml1`
- Verified address: `192.168.50.196`
- OS: Ubuntu 25.10 (`Questing Quokka`)
- Kernel / arch: `6.17.0-23-generic`, `x86_64`

## Network

- Primary interface is `wlp0s20f3` on `192.168.50.196`
- Docker bridge networks are active on `172.18.0.0/16`, `172.19.0.0/16`, and `172.20.0.0/16`
- SSH is socket-activated

## Storage

- Root filesystem is local LVM-backed ext4
- Shared vault mount:
  `192.168.50.86:/srv/cloud-vault` mounted read-write at `/mnt/cloud-vault`

## Listeners

Observed listeners:
- `22/tcp` SSH
- `111/tcp` and `111/udp` RPC bind
- `139/tcp`, `445/tcp`, `137/udp`, `138/udp` Samba
- `4319/tcp` application listener
- `54329/tcp` Postgres container publish
- `8444/tcp` NxFilter
- `11434/tcp` localhost-only Ollama

No `4310/tcp` backend listener was observed.

## Services And Timers

Running services of note:
- `docker.service`
- `smbd.service`
- `nmbd.service`
- `rpcbind.service`
- `chrony.service`
- `systemd-networkd.service`

Timers of note:
- `local-doc-classifier-taxonomy-sync.timer`
- standard OS maintenance timers

Unit detail:
- `local-doc-classifier-taxonomy-sync.service` runs `/usr/bin/python3 /opt/local-doc-classifier/sync-public-categories.py`

## Docker

Direct `docker ps` access as `kay` was denied, but `sudo -n docker ps` succeeded.

Confirmed running containers:
- `local-doc-classifier-api` on `0.0.0.0:4319->8080`
- `local-doc-classifier-ollama` on `127.0.0.1:11434`
- `nxfilter` on `8444`
- `tichu-postgres` on `54329`

Compose hints:
- `/opt/local-doc-classifier/docker-compose.yml` publishes `4319`
- `/opt/tichuml/docker-compose.yml` only showed Postgres-related lines during this probe

## App Clues

Verified app roots:
- `/opt/local-doc-classifier`
- `/home/kay/local-doc-classifier`
- `/opt/tichuml`
- `/opt/nxfilter`

Verified Git remotes:
- `/opt/local-doc-classifier` -> `NeonButrfly/local-doc-classifier`
- `/opt/tichuml` -> `NeonButrfly/tichuml`

Health checks:
- Repeated `curl` probes to `http://127.0.0.1:4319/health` timed out
- Workstation TCP connectivity to `192.168.50.196:4319` succeeded
- Result:
  application presence on `4319` is verified, but classifier health remains `unverified`

## Current-State Interpretation

- This is the live classifier host
- It writes into the shared vault on `kayraspi2`
- It also carries a `tichu-postgres` container and a checked-out `tichuml` repo, but not a live `4310` backend
- For sanitized architecture docs, the canonical Obsidian location should now be treated as `\\kayraspi2\cloud-vault\local-doc-classifier-vault`

## Open Questions

- Why `4319` accepts TCP connections but does not return `/health` within 10 seconds
- Whether the checked-out `tichuml` tree on this host is active, staged, or stale
