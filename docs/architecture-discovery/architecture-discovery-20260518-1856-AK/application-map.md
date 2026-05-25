# Application Map

## Runtime Inventory

| Application | Local repo evidence | Live host and path | Ports | Data / dependencies | Current-state status |
| --- | --- | --- | --- | --- | --- |
| `iCloudPlugin` | `C:\Code\iCloudPlugin` | `kayraspi` at `/opt/iCloudPlugin` | `8080`, `5432` | pushes classification work toward `192.168.50.196:4319`; public route `clouddrive.neonbutterfly.net` | verified live |
| `local-doc-classifier` | `C:\Code\local-doc-classifier` | `tichuml1` at `/opt/local-doc-classifier` and `/home/kay/local-doc-classifier` | `4319`, `11434 localhost` | NFS mount from `kayraspi2`; public route `classify.neonbutterfly.net` | live container verified; `/health` unverified |
| `calsync` | `C:\Code\calsync` | no checked-out host path verified during this run | expected `3080` from repo docs | public route `calsync.neonbutterfly.net` targets `kayraspi:3080` | repo exists, runtime unverified and upstream absent |
| `tichuml` | no local Windows repo supplied in this request | directories on `tichuml1` and `tichuml` | expected `4310`; observed `54329` Postgres only | Postgres on both Ubuntu hosts | backend absent during probe |
| `NxFilter` | no local repo supplied | `kayraspi`, `tichuml1`, and `tichuml` | `89/8090`, `8444`, `8090/8943/1900x` depending on host | standalone filtering service | live on three hosts |
| `cloud-vault` / iPhone backup tooling | no local repo supplied | `kayraspi2` at `/srv/cloud-vault` | `2049`, `445`, `139` and backup timers | NFS, SMB, `usbmuxd`, `rclone` remotes | verified live |
| `random` | `C:\Code\random` | no runtime evidence | unverified | unknown | local repo only |

## Strongest Cross-App Dependencies

### iCloudPlugin -> classifier

- Confirmed in local `iCloudPlugin` code:
  default classifier URL points to `http://192.168.50.196:4319`
- This matches the live port exposure on `tichuml1`

### classifier -> shared vault

- Confirmed in live mounts:
  `tichuml1` mounts `192.168.50.86:/srv/cloud-vault` read-write
- This matches earlier local-doc-classifier docs and compose expectations

### public DNS / proxy -> internal apps

- Confirmed in live Caddy config on `kayraspi2`
- Public names terminate at the proxy and route to internal LAN apps

## Cloudflare-Related Notes

Screenshot-derived record set:
- `home`
- `classify`
- `clouddrive`
- `calsync`
- apex `neonbutterfly.net`

Live proxy config only confirmed hostnames for:
- `home.neonbutterfly.net`
- `classify.neonbutterfly.net`
- `clouddrive.neonbutterfly.net`
- `calsync.neonbutterfly.net`

## Contradictions And Gaps

- `calsync` has both a local repo and a public reverse-proxy route, but no live app listener was found on the configured upstream
- `tichuml` has runtime directories on two Ubuntu hosts, but no live `4310` backend was found on either
- `kayraspi` also has `/opt/classifier`, but its role in the current-state architecture is unverified because no matching live classifier listener was observed there
