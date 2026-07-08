# Architecture Discovery Report

Generated: 2026-05-18 18:56 AKDT

Read-only scope:
- no services changed
- no packages changed
- no firewall, Docker, mounts, users, or configs changed

## Confirmed Hosts

- `kayraspi` at `192.168.50.232`
  Debian 13 Pi, iCloud service host, Tailscale node, and consumer of the shared vault via read-only NFS
- `kayraspi2` at `192.168.50.86`
  Debian 13 Pi, primary storage server, NFS/SMB host, iPhone backup host, and public reverse proxy
- `tichuml1` at `192.168.50.196`
  Ubuntu 25.10 host carrying the live classifier stack and an NFS read-write mount of the shared vault
- `tichuml` at `192.168.50.36`
  Ubuntu 24.04.4 host carrying Postgres and NxFilter, but not the expected Tichu HTTP backend

## Unreachable Hosts

- None of the four requested primary targets were unreachable

Not probed because preconditions were not met:
- `192.168.50.83`
- `192.168.50.128`

These should now be treated as non-canonical historical addresses rather than
current operator targets. Use the Ethernet-backed LAN addresses for active host
mapping instead:

- `kayraspi2` -> `192.168.50.86`
- `tichuml1` -> `192.168.50.196`
- `kayraspi` -> `192.168.50.232`
- `tichuml` -> `192.168.50.36`

## Services Discovered

### Confirmed live

- `iCloudPlugin` on `kayraspi:8080`
- shared Postgres for that stack on `kayraspi:5432`
- `local-doc-classifier-api` on `tichuml1:4319`
- `tichu-postgres` on both Ubuntu hosts at `54329`
- Caddy reverse proxy on `kayraspi2:80/443`
- NxFilter on all three non-storage hosts
- `usbmuxd` plus iPhone backup timer on `kayraspi2`
- Cloudflare DDNS timer on `kayraspi`
- Tailscale on `kayraspi`
- RPi Connect on both Pis

### Confirmed absent or not responding

- No `4310` backend was found on `tichuml1`
- No `4310` backend was found on `tichuml`
- No `4319` classifier listener was found on `tichuml`
- No `3080` calsync listener was found on `kayraspi`

### Present but health unverified

- `tichuml1:4319`
  listener and container are live, but `/health` timed out repeatedly

## Storage And Shares Discovered

- Primary shared storage is `kayraspi2:/srv/cloud-vault` on local ext4 disk
- `tichuml1` mounts that storage read-write at `/mnt/cloud-vault`
- `kayraspi` mounts that storage read-only at `/srv/cloud-vault`
- `kayraspi2` exports the same path over SMB as `[cloud-vault]`
- canonical Obsidian location should now be treated as `\\kayraspi2\cloud-vault\document-vault`; `local-doc-classifier-vault` is a compatibility link during the soak period
- iPhone backup directories are stored under `/srv/cloud-vault`

## Application And Service Dependencies

- `iCloudPlugin` depends on:
  local Postgres and a downstream classifier target at `192.168.50.196:4319`
- `local-doc-classifier` depends on:
  shared vault storage from `kayraspi2` and local Ollama on `127.0.0.1:11434`
- Public app ingress depends on:
  Caddy on `kayraspi2`, with Cloudflare-facing hostnames routed into the LAN
- `calsync` appears intended to depend on:
  `kayraspi:3080`, but that upstream was not live during this discovery

## Contradictions To Prior Assumptions

- The expected Tichu backend on `4310` was not running on either probed Tichu host
- `tichuml` (`192.168.50.36`) looked more like a Postgres-plus-NxFilter box than an active application backend
- `calsync` has a configured public proxy route but no matching live upstream on `kayraspi`
- `kayraspi` contains a classifier checkout at `/opt/classifier`, but current live classification traffic appears to belong to `tichuml1`

## Open Questions

- Why does `local-doc-classifier-api` on `tichuml1` accept TCP connections but fail to answer `/health` within 10 seconds
- Whether `tichuml1`'s checked-out `tichuml` repo is active or only colocated with other services
- Whether `tichuml` is a standby, retired, or partial deployment
- Why `cloud-vault-sync.service` is failing on `kayraspi2`
- Whether the screenshot-derived Cloudflare record set still matches the live zone exactly

## Recommended Architecture Doc Updates

1. Document the document-processing pipeline as:
   `kayraspi iCloudPlugin -> tichuml1 local-doc-classifier -> kayraspi2 shared vault`
2. Mark `kayraspi2` as both:
   the storage authority and the public reverse-proxy entrypoint
3. Mark `tichuml1` as:
   the active classifier host, with classifier health still needing confirmation
4. Mark `tichuml` as:
   present and reachable, but not currently serving the expected `4310` backend
5. Document Cloudflare/public routing separately from LAN truth:
   public names may exist even when the LAN upstream is absent, as shown by `calsync`
6. Call out the NFS access model explicitly:
   `tichuml1` has write access; `kayraspi` has read-only access
7. Add an operations note for `cloud-vault-sync.service`:
   observed failed during this discovery, root cause not investigated
8. Mark the Ethernet LAN addresses above as canonical and retire stale
   wireless-era addresses from operator guidance
