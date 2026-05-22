# Vault Reconciliation Design

Related issue: #8

## Goal

Add a safe first-pass background reconciler that keeps Obsidian notes aligned
with the current mirrored iCloud file location without changing the existing
one-way iCloud mirror behavior.

## Current State

- `iCloudPlugin` indexes the mirrored filesystem rooted at
  `/srv/cloud-vault/mirrors/icloud`.
- `local-doc-classifier` writes notes into the live vault at
  `\\kayraspi2\cloud-vault\local-doc-classifier-vault`.
- Notes currently depend on copied files under `90 Attachments`, which makes the
  vault drift away from the canonical live file location when mirrored files are
  renamed or moved.
- The service already has background worker infrastructure, mirror-aware file
  discovery, and hash-aware extraction tracking, but it does not own any
  vault-level repair pass.

## Approved Approach

Use a compatibility-first design.

- Keep the vault where it is today.
- Keep the current one-way `rclone copy icloud: -> /srv/cloud-vault/mirrors/icloud`
  architecture unchanged.
- Add a background reconciliation pass in `iCloudPlugin`.
- Let the classifier start writing canonical source metadata that the
  reconciler can trust.
- Preserve `90 Attachments` as a compatibility layer in the first pass instead
  of deleting or replacing it outright.

## Non-Goals For This Pass

- No bidirectional iCloud sync.
- No source-of-truth move into the iCloud mirror tree.
- No destructive bulk rewrite of notes.
- No automatic rewrite when the service cannot make a confident file match.

## Reconciler Responsibilities

The reconciler owns note-to-file repair, not note generation.

For each note that advertises canonical source metadata, the reconciler should:

1. Read the current canonical source path and source hash from note metadata.
2. Check whether the current canonical path still exists.
3. If the path is missing, search the mirrored tree for a replacement candidate.
4. Prefer an exact content-hash match.
5. If no hash match is available, fall back to filename comparison:
   - exact basename match first
   - normalized close-name comparison second
6. Only rewrite note metadata when the match is confident.
7. Mark uncertain cases for review instead of guessing.

## Confidence Rules

The service should only auto-repair when one of these holds:

- exactly one mirrored file has the same canonical content hash
- no hash match exists, but exactly one mirrored file has the same normalized
  filename within the expected scope and there is no competing close-name file

The reconciler should not auto-rewrite when:

- multiple files share the same hash and the path cannot be disambiguated
- multiple close-name candidates exist
- canonical metadata is missing or malformed

## Integration Shape

The reconciler should run as background work owned by `iCloudPlugin`.

- It must not block metadata refresh completion.
- It must not prevent classification submission from continuing.
- It may run after refresh batches or on a small periodic background cadence.
- First pass should prefer small, bounded scans and incremental repair over
  whole-vault rescans on every loop.

## Data Contract Expected From The Classifier

The service expects notes to include enough metadata to make repair decisions:

- canonical source path
- canonical source hash
- last-seen filename
- attachment mode
- compatibility attachment path when one exists

The service should treat this metadata as advisory input and avoid changing note
content outside the fields it owns for repair.

## Failure Handling

- Missing metadata: skip and report as unverified or unreconcilable.
- Ambiguous match: leave the note untouched and surface review metadata.
- Read/write failure on a single note: record the failure and continue.
- Reconciler failure must not fail the refresh job or mark the mirror unhealthy.

## Testing

- unit tests for confident hash-match selection
- unit tests for exact-name and close-name fallback behavior
- unit tests proving ambiguous matches do not auto-rewrite notes
- integration-style test showing a note can be repaired after a mirrored move
- regression validation proving refresh and classification worker behavior stay
  intact when reconciliation is enabled

## Rollout Notes

This design intentionally creates a safe bridge:

- today: copied attachments remain usable
- next: notes gain canonical live-file metadata
- later: sync-direction and canonical-storage decisions can change without
  throwing away note history or guessing where files moved
