# Role-Based Monorepo Design

Related issue: #9

## Goal

Merge the current sync/indexing stack and the local document classifier into one
 monorepo while preserving separate deployable roles for different servers and
 cleaning up operator-facing vault and note naming.

## Approved Direction

Use the current `iCloudPlugin` repository as the monorepo backbone.

- keep one codebase
- keep separate deployable roles
- keep sync/indexing and classifier able to run on different hosts
- clean up naming so the vault reads like a human library rather than a debug
  artifact set

## Why This Direction

The current split repos model two sides of the same system:

- mirrored-drive sync and indexed file inventory
- classifier note generation and vault maintenance

They share concepts such as:

- canonical live-file paths
- source hashes
- note contracts
- vault reconciliation
- operator deployment configuration

Keeping those concepts in separate repos increases drift risk and keeps naming
 cleanup harder than it needs to be.

## Monorepo Shape

The monorepo should be organized around deployable roles and shared packages.

### Apps

- `apps/cloudsync`
  - mirrored filesystem crawl
  - sync jobs and refresh scheduling
  - moved-file detection inputs
- `apps/classifier`
  - classification API
  - note generation
  - review-note cleanup
  - vault maintenance tasks
- `apps/api`
  - operator/search/status API
  - health endpoints
  - refresh and reconciliation status
- `apps/mcp`
  - Codex/ChatGPT plugin bridge

### Shared packages

- `packages/contracts`
  - API payloads
  - note frontmatter contract
  - reconciliation result schemas
- `packages/storage`
  - file records
  - hashing helpers
  - path logic
  - moved-file matching utilities
- `packages/vault`
  - note naming
  - vault naming
  - metadata updates
  - rename normalization rules
- `packages/classification`
  - classifier output shaping
  - fallback summary and reason helpers
  - label routing helpers
- `packages/runtime`
  - role config
  - env parsing
  - shared startup wiring

## Separate Deployment Requirement

Separate deployment is a first-class requirement, not a temporary compatibility
 mode.

The design must support:

- `kayraspi2` running `cloudsync` plus `api`
- `tichuml1` running `classifier`
- optional combined deployment on one host later

This means:

- no role may assume local filesystem access to another role's private runtime
  state beyond explicit shared mounts
- inter-role communication should use explicit contracts and APIs
- runtime config should be role-scoped and not rely on hidden same-host
  assumptions

## Naming Cleanup

### Repository and platform naming

The monorepo should adopt a neutral platform identity rather than a source- or
 implementation-specific name.

Recommended platform name:

- `cloud-vault-platform`

This name keeps the system open to future non-iCloud sources while still
 matching the current mirrored-drive and vault workflow.

### Role naming

Recommended deployable role names:

- `cloudsync`
- `classifier`
- `api`
- `mcp`

### Vault naming

The live Obsidian vault should stop being framed as classifier-only output.

Recommended operator-facing vault name:

- `document-vault`

This should replace user-facing references such as
`local-doc-classifier-vault` in docs, deploy examples, and runtime labels over
 time.

## Note and Artifact Naming

### Current problem

Visible hashes make note filenames harder to scan and harder to live with in
 Obsidian.

### New default note naming

Recommended default note filename:

- `{clean-title} - {primary-label}.md`

If there is a collision:

- `{clean-title} - {primary-label} (2).md`
- `{clean-title} - {primary-label} (3).md`

Hashes should remain in metadata, not in the default visible filename.

### Extracted markdown naming

Recommended extracted-markdown filename:

- `{clean-title}.extracted.md`

Use collision suffixes only when necessary.

### Compatibility attachments

Compatibility attachments should prefer human-readable filenames and keep
 canonical hashes in metadata instead of visible file names.

## Migration Strategy

The merge should happen in safe phases.

### Phase 1: repository structure

- create the monorepo app/package skeleton in the backbone repo
- import classifier code into `apps/classifier`
- preserve current runtime behavior while moving code

### Phase 2: shared contracts

- move shared note-contract, hashing, and path logic into packages
- remove duplicated config and helper code across roles

### Phase 3: naming cleanup for new outputs

- switch new notes to human-readable filenames
- switch new operator-facing naming to `document-vault`
- keep hashes in metadata

### Phase 4: safe normalization for existing vault content

- add a background rename and normalization pass for existing notes
- preserve link integrity
- record collision-safe renames during transition

### Phase 5: retirement of old split structure

- prove deployment parity
- retire the old standalone repo layout only after role-based deploys are
  stable

## Non-Goals For The First Merge Phase

- no bidirectional sync change
- no giant all-at-once live vault rename
- no forced combined deployment
- no removal of compatibility attachments before naming and reconciliation are
  proven stable

## Testing Expectations

- repo structure tests or smoke validation for role entrypoints
- config validation for separate-host deployment
- regression tests for classifier note contract and vault reconciliation
- naming tests proving new note filenames are human-readable and collision-safe
- migration tests proving rename normalization preserves link integrity

## Operational Expectations

The merged repo should ship role-specific deployment examples under a clear
 deployment path such as:

- `deploy/roles/cloudsync`
- `deploy/roles/classifier`
- `deploy/roles/combined`

Each role should document:

- required environment variables
- required mounts
- network dependencies
- shared contracts with other roles

## Success State

The merge is successful when:

- one repo owns sync, indexing, classification, vault metadata, and MCP access
- sync and classifier still deploy independently on different servers
- new note and vault naming is human-readable
- hashes remain available for correctness and reconciliation without dominating
  the operator experience
