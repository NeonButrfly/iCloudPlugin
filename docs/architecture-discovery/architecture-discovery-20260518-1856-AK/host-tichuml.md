# Host: tichuml

Host verification:
- Confirmed hostname: `tichuml`
- Verified address: `192.168.50.36`
- OS: Ubuntu 24.04.4 LTS
- Kernel / arch: `6.17.0-23-generic`, `x86_64`

## Network

- Primary interface is `wlo1` on `192.168.50.36`
- Docker bridge network present on `172.18.0.0/16`
- No Tailscale or WireGuard evidence was returned

## Storage

- Local LVM-backed root filesystem
- No shared NFS mount to `/srv/cloud-vault` or `/mnt/cloud-vault` was observed

## Listeners

Observed listeners:
- `22/tcp` SSH
- `54329/tcp` Postgres container publish
- `8090/tcp`, `8943/tcp`, `19002/tcp`, `19003/tcp`, `19004/udp`, and `53/udp` for NxFilter

Absent during probe:
- `4310/tcp`
- `4319/tcp`

## Services And Docker

Running services of note:
- `docker.service`
- `nxfilter.service`
- `systemd-networkd.service`
- `ssh.service`

Confirmed running container:
- `tichu-postgres` on `0.0.0.0:54329->5432`

Compose observations:
- `docker compose ls` reported project `tichuml`
- `/opt/tichuml/docker-compose.yml` exposed only Postgres-related lines during the targeted grep
- `/tichuml/docker-compose.yml` also showed Postgres-related lines, with one copy binding Postgres to loopback only

## App Clues

Verified directories:
- `/opt/tichuml`
- `/tichuml`
- `/srv/tichu`

Git remote checks for `/opt/tichuml` and `/tichuml` returned no remotes during this sweep.

Health checks:
- `http://127.0.0.1:4310/health` failed immediately
- `http://127.0.0.1:4319/health` failed immediately

## Current-State Interpretation

- This host is not currently serving the expected Tichu application backend on `4310`
- It appears to carry a tichu-related checkout plus a live Postgres container and NxFilter service
- Relative to the starting assumption, this is the clearest contradiction in the probe set

## Open Questions

- Whether this machine is a standby, an older deployment, or a database-only helper for tichu work
- Why there are two `tichuml` directory roots with different compose publishing behavior
