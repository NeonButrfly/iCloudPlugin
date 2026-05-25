# Host: kayraspi

Host verification:
- Confirmed hostname: `kayraspi`
- Verified addresses: `192.168.50.232` on `eth0`, `192.168.50.235` on `wlan0`, `100.96.90.42` on `tailscale0`
- OS: Debian GNU/Linux 13 (`trixie`)
- Kernel / arch: `6.12.75+rpt-rpi-v8`, `aarch64`

## Network

- Default routes exist on both `eth0` and `wlan0`
- Additional Docker bridge networks are present on `172.19.0.0/16`, `172.22.0.0/16`, and several inactive bridge ranges
- Tailscale is active and reports node `kayraspi`

## Storage

- Root filesystem is local ext4 on `/dev/mmcblk0p2`
- `/srv/cloud-vault` is not local storage on this host
  it is mounted from `192.168.50.86:/srv/cloud-vault`
- Mount mode for that NFS mount is read-only

## Listeners

Observed listeners:
- `22/tcp` SSH
- `89/tcp` NxFilter HTTP via Docker
- `5432/tcp` Docker-published Postgres
- `5900/tcp` VNC Server
- `8080/tcp` iCloudPlugin service via Docker
- `8090/tcp` NxFilter HTTPS via Docker
- `111/tcp` and `111/udp` RPC bind

## Services And Timers

Running services of note:
- `docker.service`
- `tailscaled.service`
- `vncserver-x11-serviced.service`
- `ssh.service`
- `NetworkManager.service`

Timers of note:
- `cloudflare-ddns.timer`
- standard OS maintenance timers

## Docker

Confirmed running containers:
- `icloudplugin-service-1` with published `8080`
- `icloudplugin-postgres-1` with published `5432`
- `icloudplugin-worker-1`
- `icloudplugin-classification-worker-1`
- `nxfilter` with published `89` and `8090`

Compose projects:
- `icloudplugin`
- `nxfilter`

## App Clues

Verified app roots:
- `/opt/iCloudPlugin`
- `/opt/classifier`
- `/opt/nxfilter`

Verified Git remotes:
- `/opt/iCloudPlugin` -> `NeonButrfly/iCloudPlugin`
- `/opt/classifier` -> `NeonButrfly/local-doc-classifier`

Health checks:
- `http://127.0.0.1:8080/health` returned `200 OK`

Code and config signals:
- Local `iCloudPlugin` code points classifier submissions to `http://192.168.50.196:4319/classify/upload`
- `cloudflare-ddns.service` exists and executes a local shell script

## Remote Access And Peripheral Tooling

- Tailscale is active
- RPi Connect reports signed in, event subscription enabled, screen sharing allowed, and remote shell allowed
- iPhone-related directories exist under the mounted cloud vault:
  `iphone-backups`, `iphone-backups-pymobiledevice3`, `iphone-backups-pymobiledevice3-usb`

## Current-State Interpretation

- This is the live iCloud service host
- It consumes the shared vault from `kayraspi2` read-only
- It publishes the `clouddrive` application on port `8080`
- It also carries an NxFilter deployment and Cloudflare DDNS automation

## Open Questions

- `/opt/classifier` exists on this host, but no classifier listener was observed here during this run
- No live `calsync` listener was found on `3080` even though a public proxy route points to this host on that port
