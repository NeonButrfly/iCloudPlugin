# Storage And Shares

## Primary Shared Storage

Primary vault host:
- `kayraspi2` (`192.168.50.86`)

Backing device:
- `/dev/sda1`

Filesystem:
- ext4

Mount point:
- `/srv/cloud-vault`

Capacity:
- about `3.6T`

Observed usage:
- about `280G`

## NFS Layout

Exports from `kayraspi2`:

| Export | Client | Access |
| --- | --- | --- |
| `/srv/cloud-vault` | `192.168.50.196` | read-write |
| `/srv/cloud-vault` | `192.168.50.232` | read-only |

Observed client mounts:

| Client host | Mount point | Source | Access |
| --- | --- | --- | --- |
| `tichuml1` | `/mnt/cloud-vault` | `192.168.50.86:/srv/cloud-vault` | read-write |
| `kayraspi` | `/srv/cloud-vault` | `192.168.50.86:/srv/cloud-vault` | read-only |

Interpretation:
- `tichuml1` appears to be the writer for classifier output
- `kayraspi` appears to consume the same vault content read-only

## SMB Layout

Confirmed on `kayraspi2`:

| Share | Path | Access model |
| --- | --- | --- |
| `cloud-vault` | `/srv/cloud-vault` | write-capable for user `kay` |

Notes:
- `[cloud-vault]` lives on the storage server
- Current canonical Obsidian location is `\\kayraspi2\cloud-vault\document-vault`.
  `local-doc-classifier-vault` remains only as a compatibility link during the
  soak period.

## Backup And Archive Directories

Observed under `/srv/cloud-vault`:
- `local-doc-classifier-vault`
- `local-doc-classifier-vault-reset-20260516-202212`
- `iphone-backups`
- `iphone-backups-pymobiledevice3`
- `iphone-backups-pymobiledevice3-usb`

Interpretation:
- The shared storage is doing double duty:
  classifier vault storage plus Apple backup retention

## Backup Tooling

Confirmed on `kayraspi2`:
- `usbmuxd.service` running
- `iphone-backup-if-connected.timer` active
- `iphone-backup-if-connected.service` last observed exiting successfully

## Storage Risks And Open Questions

- `cloud-vault-sync.service` was in failed state on `kayraspi2`
- The target and purpose of that mirror sync are not fully documented in the live outputs collected here
- `kayraspi` exposes the shared vault under the same path `/srv/cloud-vault`, but only as an NFS read-only mount, so local docs should avoid describing it as authoritative storage
