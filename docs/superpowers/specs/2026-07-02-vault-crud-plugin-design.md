# Vault CRUD Plugin Design

Issue: [#84](https://github.com/NeonButrfly/iCloudPlugin/issues/84)

## Goal

Extend `iCloudPlugin` so ChatGPT can safely perform full CRUD operations across
the private shared vault surfaces while preserving reversibility, hiding
internal `_` directories from ordinary discovery, and keeping Obsidian
`document_vault` writes compliant with the same note contract the local
categorizer already uses.

This design covers:

- shared mirror namespaces:
  - `google1`
  - `google2`
  - `icloud`
- Obsidian namespace:
  - `document_vault`
- reversible `_CHANGES_BACKUP` logging and restore
- underscore-prefixed directory hiding
- automatic Obsidian feedback sync after relevant vault note changes
- retroactive import of `_DUPLICATE_QUARANTINE` and prior dedupe artifacts into
  `_CHANGES_BACKUP`
- operator-facing command patterns for classification, dedupe, folder
  reorganization, and undo

## Runtime Mapping

The live backend and plugin-facing routes execute on `tichuml1`
(`192.168.50.196`) against the mounted shared vault paths.

Canonical runtime roots:

- mirror root on `tichuml1`:
  - `/mnt/cloud-vault/mirrors`
- `document_vault` on `tichuml1`:
  - `/mnt/cloud-vault/document-vault`

Canonical storage truth remains on `kayraspi2` (`192.168.50.86`):

- `/srv/cloud-vault/mirrors`
- `/srv/cloud-vault/document-vault`

Normal plugin operations should not SSH-hop to the Pi. They should operate on
the mounted NFS view from `tichuml1`.

## Public Surface

### Namespaces

Expose four public writable namespaces:

- `google1`
- `google2`
- `icloud`
- `document_vault`

### Access Modes

Support both:

- path-based operations
- file-id-based operations for already indexed files

File-id-based operations apply to the three mirror namespaces. `document_vault`
operations are path-based and structured-note-based.

### Supported Operator Workflows

The public tool surface should be expressive enough for ChatGPT to reliably
carry out these higher-level workflows from explicit user commands:

- read files from `google1`, `google2`, and `icloud`
- categorize files and create structured notes in `document_vault`
- re-read `document_vault` and use manual note moves/folder placement as
  feedback signals
- analyze duplicates across mirror namespaces
- rearrange folder structures through reversible moves
- undo a prior change set or selected backed-up files

These are workflow-level capabilities built from multiple lower-level tools. The
design should not assume one opaque "do everything" endpoint; it should make the
workflow decomposition clear enough that ChatGPT can execute it safely.

### Hidden Directories Rule

Any directory whose basename starts with `_` is hidden from ordinary plugin
discovery:

- normal list operations cannot return `_` paths
- normal search operations cannot return `_` paths
- normal read operations cannot directly read `_` paths

Internal restore and backup flows may still read from and write to `_` paths.

## Architecture

Use an origin-first design with one canonical mutation engine in the on-prem
service. Local MCP, Cloudflare remote MCP, and plugin packaging remain thin
wrappers over origin routes and shared backend behavior.

### New Backend Service

Add a dedicated backend file-operations service responsible for:

- namespace resolution
- path normalization and safety checks
- `_`-directory visibility policy
- backup snapshot creation
- delete-as-move behavior
- change-set logging
- restore execution
- `_DUPLICATE_QUARANTINE` import
- `document_vault` structured note writes

This service becomes the only place where file mutations are implemented.

### Origin API

Add authenticated origin routes for:

- list files in a namespace
- read file content/metadata
- create file
- update file
- move/rename file
- delete file
- restore a change set
- restore a specific backed-up file
- inspect change-set history
- import legacy quarantine/dedupe history into `_CHANGES_BACKUP`
- trigger or reuse categorization and structured note-writing flows for selected
  source files
- run or stage dedupe/reorganization analysis in a way that produces reversible
  change sets when approved

The route layer should stay thin and delegate to the file-operations service.

### MCP And Plugin Layer

Add matching tools to:

- `src/icloud_plugin_mcp/server.py`
- `cloudflare/remote-mcp/src/index.ts`
- `cloudflare/remote-mcp/chatgpt-app-submission.json`
- plugin packaging metadata under `plugins/icloud-drive`

Tool metadata must make the split clear:

- read/list/search tools are private but non-destructive
- file CRUD and restore tools are mutating
- `document_vault` note creation is structured, not raw freeform file writes
- higher-level dedupe/reorganization tools either support dry-run mode or return
  an explicit proposed action set before mutation

### Operator Prompt Surface

Check in a repo-owned prompt reference document so the command language used by
humans and the plugin capability design evolve together.

Required document:

- `docs/prompts/chatgpt-vault-operations.md`

That document should provide prompt patterns for:

- categorize plus write structured Obsidian notes
- feedback re-read from manual Obsidian organization
- reversible dedupe
- reversible folder-structure analysis and reorganization
- targeted undo / restore

## Mutation Model

### General File CRUD

Mirror namespaces (`google1`, `google2`, `icloud`) support:

- create file
- read file
- overwrite file
- move/rename file
- delete file
- batch analyze for dedupe/reorganization planning
- approved batch mutation execution through reversible change sets

All mutating operations produce a `change_set_id`.

### Delete Semantics

Delete is not hard delete.

Default delete flow:

1. resolve and validate the live source path
2. create a `_CHANGES_BACKUP` change set
3. move the live file into `_CHANGES_BACKUP`
4. record the original live path and metadata in the change log
5. return the `change_set_id`

### Update And Move Semantics

Before overwrite or move:

1. snapshot the prior state into `_CHANGES_BACKUP`
2. log the intended mutation in the change set
3. apply the mutation
4. finalize the change-set entry

### Restore Semantics

Restore is first-class from day one.

Supported restore modes:

- restore a full change set
- restore a single file from a change set

Restore tools are the only user-facing paths allowed to read from
`_CHANGES_BACKUP`, and only in targeted, structured form.

### Batch Workflow Semantics

Dedupe and folder-reorganization operations should be modeled as explicit batch
workflows rather than untracked ad hoc loops.

Minimum batch behavior:

1. collect candidate actions
2. support dry-run or proposal output
3. apply approved moves/deletes/overwrites through normal reversible mutation
   helpers
4. group related actions under one or more traceable `change_set_id` values
5. leave enough metadata to undo all or part of the batch later

## `_CHANGES_BACKUP` Design

Each namespace gets its own reserved `_CHANGES_BACKUP` subtree so backups sync
with the same storage fabric while staying adjacent to the mutated content.

Expected roots:

- `/mnt/cloud-vault/mirrors/google1/_CHANGES_BACKUP`
- `/mnt/cloud-vault/mirrors/google2/_CHANGES_BACKUP`
- `/mnt/cloud-vault/mirrors/icloud/_CHANGES_BACKUP`
- `/mnt/cloud-vault/document-vault/_CHANGES_BACKUP`

Each change set stores:

- `change_set_id`
- timestamp
- operation type
- actor (`chatgpt-plugin`, `restore`, `legacy-import`, etc.)
- namespace
- original path
- resulting path
- status
- backed-up payload path or moved-file location
- optional notes for dedupe/quarantine import provenance

Use append-only machine-readable logs, plus a human-readable summary file per
change set.

## `document_vault` Structured Note Creation

`document_vault` does not support arbitrary raw freeform writes through the main
ChatGPT creation path. It must use structured note creation that reuses the same
note-writing contract as the local categorizer.

### Required Contract

The plugin note writer should reuse the existing categorizer note contract,
including:

- structured frontmatter
- canonical source metadata
- `source_parser`
- `heuristic_primary_hint`
- `hybrid_live_source`
- rendered sections such as:
  - `## Summary`
  - `## Classification`
  - `## Reason`
  - `## Retrieval`
  - `## Original File`
  - `## Extracted Markdown File`

### Link Strategy

For direct accessibility across Windows, Linux, and macOS inside Obsidian, the
preferred cross-platform representation is a vault-local attachment link when
the source file is available for copy into the vault.

Therefore, structured plugin-created notes should prefer:

- vault-local attachment links such as:
  - `[[90 Attachments/...]]`

while still preserving:

- `canonical_source_path`
- `source_link`
- `attachment_mode`

This reuses the current categorizer behavior instead of inventing a second link
contract. If attachment-copying is not possible for a specific operation, the
existing canonical source-link fallback may still be used.

### Tooling Exposure For ChatGPT

Expose the `document_vault` creation contract to ChatGPT through a dedicated
structured-note tool schema rather than asking the model to invent raw note
files. The tool input should describe:

- target folder
- visible title or source filename
- note purpose/type
- summary
- classification metadata when known
- source reference details when tied to a mirrored file
- optional extracted markdown body

## Automatic Feedback Sync

Relevant `document_vault` changes should automatically trigger the same feedback
sync path the local categorizer already uses.

Triggering operations:

- structured note creation in `document_vault`
- note moves between non-underscore folders
- note edits that change classifier-relevant frontmatter or source references

Automatic feedback sync should:

- ignore `_`-prefixed paths
- preserve the existing distinction between weak folder-derived signals and
  stronger generated-note move corrections
- avoid direct model training in the ChatGPT tool itself
- reuse the existing vault reconciliation / manual feedback ingestion path

The same feedback pathway should be callable as an intentional re-read command
so ChatGPT can refresh its categorization context after a human reorganizes the
Obsidian vault.

## Source File And Note Sync

When the plugin deletes or restores a source file that has a matching generated
or structured Obsidian note, the note should be updated automatically to remain
consistent.

Examples:

- deleting a source file can update its note state and source reference
- restoring a source file can restore or repair the note’s source reference
- moving a source file can update canonical source metadata when appropriate

This note-sync logic should also be centralized in the backend service so
mirror-file mutations and Obsidian note state do not drift.

## Categorizer And Indexing Rules

All `_`-prefixed directories must be ignored by categorization and by normal
indexed discovery.

That includes:

- `_CHANGES_BACKUP`
- `_DUPLICATE_QUARANTINE`
- any future underscore-prefixed maintenance directories

Update the existing file iteration and classifier intake logic so this rule is
consistent across:

- vault scanning
- mirror scanning
- manual note feedback collection
- plugin list/search surfaces where applicable

## Legacy Quarantine / Dedupe Import

Retroactively import the earlier dedupe work into `_CHANGES_BACKUP`.

Inputs:

- `_DUPLICATE_QUARANTINE` contents
- loose dedupe CSV/log files under `/home/kay`, including the previously listed
  `aetna-*`, `all-files-*`, and `icloud-dedupe-*` artifacts

Import behavior:

1. gather the legacy artifacts
2. map them into change sets under the namespace-specific `_CHANGES_BACKUP`
   structure
3. preserve provenance indicating they came from legacy dedupe/quarantine work
4. move or normalize `_DUPLICATE_QUARANTINE` content into the new backup model
5. leave a deterministic audit trail so later restore tools can reason about
   those imported items

This import is not log-only. It physically merges the legacy quarantine state
into the new `_CHANGES_BACKUP` layout.

## Commandability

The framework should make it realistic for an operator to give ChatGPT direct
commands such as:

- "Read uncategorized files from google1, google2, and icloud, categorize them,
  and create structured Obsidian notes in document_vault."
- "Run a dedupe across google1, google2, and icloud and route all reversible
  changes through _CHANGES_BACKUP."
- "Analyze the current folder layout and reorganize it using reversible moves
  only."
- "Restore change set `<id>` and repair related document_vault references."

This means the tool surface should expose both low-level primitives and enough
workflow-oriented entry points that ChatGPT does not need to invent hidden
state, raw note formats, or unlogged mutation behavior.

## Error Handling

- reject any mutation whose resolved path escapes the configured namespace root
- reject normal direct reads to `_` paths
- reject raw freeform `document_vault` note creation outside the structured note
  tool
- reject file-id operations when the file record no longer maps to a live,
  allowed namespace path
- reject restore requests that target unknown change sets or inconsistent backup
  payloads
- report partial import failures without silently skipping artifacts

## Testing

Use TDD for all new behavior.

Minimum coverage:

- namespace path resolution
- underscore-directory filtering for list/search/read
- create/update/move/delete for path-based mirror operations
- file-id-based mirror CRUD where applicable
- delete-as-move into `_CHANGES_BACKUP`
- change-set log creation
- restore of full change sets
- restore of a single file
- `document_vault` structured note creation using categorizer-compatible note
  output
- attachment-link preference for cross-platform note access
- automatic feedback sync trigger after relevant note changes
- note updates after source delete/restore
- `_DUPLICATE_QUARANTINE` and `/home/kay` dedupe import
- categorizer ignore rules for all `_` directories
- explicit workflow tests for:
  - categorize plus structured note write
  - feedback re-read from manual Obsidian moves/folders
  - dedupe dry-run and approved execution
  - reversible folder reorganization
  - targeted undo from a returned `change_set_id`
- MCP tool annotations and output schemas for new tools
- ChatGPT app submission metadata updates reflecting CRUD and restore behavior

## Rollout Order

1. backend file-operations service and underscore rules
2. origin API routes
3. structured `document_vault` note writer integration
4. automatic feedback sync wiring
5. local MCP tools
6. remote MCP tools and submission metadata
7. legacy quarantine/dedupe import tooling
8. host-side verification on `tichuml1`

## Spec Review Notes

Self-review completed:

- no unresolved placeholders remain
- the design consistently uses `tichuml1` as the execution host and
  `kayraspi2` as storage truth
- `document_vault` is modeled as structured-note-only for creation
- delete semantics, restore semantics, and `_`-directory behavior are explicit
