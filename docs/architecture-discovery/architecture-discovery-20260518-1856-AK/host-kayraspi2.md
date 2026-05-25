# Host: kayraspi2

Host verification:
- Confirmed hostname: `kayraspi2`
- Verified addresses: `192.168.50.86` on `eth0`, `192.168.50.88` on `wlan0`
- OS: Debian GNU/Linux 13 (`trixie`)
- Kernel / arch: `6.12.75+rpt-rpi-2712`, `aarch64`

## Network

- Default routes exist on both `eth0` and `wlan0`
- No Docker stack was observed on this host
- Caddy is the only confirmed `80/443` reverse proxy among the four probed hosts

## Storage

- Primary vault disk: `/dev/sda1`
- Filesystem: ext4
- Mounted at: `/srv/cloud-vault`
- Capacity: about `3.6T`
- Current use: about `280G`

## Shares

NFS exports:
- `/srv/cloud-vault` -> `192.168.50.196` as read-write
- `/srv/cloud-vault` -> `192.168.50.232` as read-only

Samba:
- Share name: `[cloud-vault]`
- Backing path: `/srv/cloud-vault`
- Valid user: `kay`
- Forced user/group: `kay`

Backup-related directories under `/srv/cloud-vault`:
- `local-doc-classifier-vault`
- `local-doc-classifier-vault-reset-20260516-202212`
- `iphone-backups`
- `iphone-backups-pymobiledevice3`
- `iphone-backups-pymobiledevice3-usb`

## Listeners

Observed listeners:
- `22/tcp` SSH
- `80/tcp` Caddy
- `443/tcp` Caddy
- `111/tcp` and `111/udp` RPC bind
- `139/tcp`, `445/tcp`, `137/udp`, `138/udp` Samba
- `2049/tcp` NFS
- dynamic `nfs-mountd` and `rpc-statd` ports

## Services And Timers

Running services of note:
- `caddy.service`
- `smbd.service`
- `nmbd.service`
- `nfs-mountd.service`
- `rpcbind.service`
- `usbmuxd.service`

Timers of note:
- `cloud-vault-sync.timer`
- `iphone-backup-if-connected.timer`

Observed unit state:
- `cloud-vault-sync.service` was last observed in `failed` state
- `iphone-backup-if-connected.service` last observed exited `0`

## Cloudflare / Proxy Signals

Live Caddy routing confirmed:
- `home.neonbutterfly.net` -> static `200` response
- `classify.neonbutterfly.net` -> `http://192.168.50.196:4319`
- `calsync.neonbutterfly.net` -> `http://192.168.50.232:3080`
- `clouddrive.neonbutterfly.net` -> `http://192.168.50.232:8080`

Cloudflare-related facts:
- Caddy is configured to use a local origin certificate pair
- `cloudflare-ddns` itself was not found on this host; the DDNS timer lives on `kayraspi`

## Remote Access And Tooling

- `usbmuxd` is running
- `rclone listremotes` returned:
  `icloud`
  `gdrive1`
- RPi Connect reports signed in, event subscription enabled, screen sharing allowed, and remote shell allowed

## Current-State Interpretation

- This is the primary storage server for the document pipeline
- It also fronts the public reverse proxy layer for the probed `neonbutterfly.net` app routes
- It carries the iPhone backup automation and Apple device plumbing

## Open Questions

- `cloud-vault-sync.service` is failing, but the reason was not investigated because this run stayed read-only
- The `calsync` proxy target points to `192.168.50.232:3080`, but that upstream was not listening during this sweep
