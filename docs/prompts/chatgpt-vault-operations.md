# ChatGPT Vault Operation Prompts

Issue: [#84](https://github.com/NeonButrfly/iCloudPlugin/issues/84)

## Purpose

These prompts give ChatGPT a consistent operator-facing command style for the
vault workflows planned in the reversible CRUD design:

- read files from `google1`, `google2`, and `icloud`
- categorize files
- create structured Obsidian notes in `document_vault`
- run dedupe workflows
- analyze folder layout
- rearrange folders with reversible moves
- undo changes through `_CHANGES_BACKUP`

Use these prompts after the CRUD and restore implementation is live. Until that
work is implemented, treat them as the target operating language rather than a
claim that every workflow is already shipped.

## General Rules To Include In Prompts

When asking ChatGPT to perform vault work, keep these constraints explicit:

- read from `google1`, `google2`, `icloud`, and `document_vault` only as needed
- ignore all directories whose basename starts with `_` during normal
  read/list/search work
- do not hard delete files
- route deletes, overwrites, and moves through `_CHANGES_BACKUP`
- log every reversible change with enough metadata to undo some or all of the
  operation later
- create `document_vault` notes using the structured categorizer-compatible
  note contract
- prefer vault-local attachment links when creating Obsidian notes
- use manual note moves and folder placement in `document_vault` as feedback
  signals where applicable

## Daily Operator Prompts

### 1. Categorize And Write Obsidian Notes

```text
Read uncategorized files from google1, google2, and icloud, categorize them,
and create structured Obsidian notes in document_vault. Skip any folders
starting with _. Do not hard delete anything. Use the categorizer-compatible
document_vault note format and prefer vault-local attachment links.
```

### 2. Re-Read The Obsidian Vault For Feedback

```text
Re-read document_vault, use manual note moves and folder placement as training
signals, and then classify new files from google1, google2, and icloud using
that updated feedback context. Ignore all _-prefixed folders during normal
reads.
```

### 3. Run Dedupe Safely

```text
Run a dedupe across google1, google2, and icloud. For any duplicates, route the
changes through the _CHANGES_BACKUP workflow so they can be undone later. Ignore
all _-prefixed folders except where backup logs must be written.
```

### 4. Analyze And Rearrange Folder Structure

```text
Analyze the current folder layout across google1, google2, and icloud, propose
a cleaner structure, and then apply the reorganization using reversible moves
only. Ignore all _-prefixed folders during analysis, and log every move in
_CHANGES_BACKUP so the full reorganization can be undone later.
```

### 5. Full Processing Pass

```text
Process the cloud vaults: read files from google1, google2, and icloud;
categorize them; create structured Obsidian notes in document_vault; detect
duplicates; optionally reorganize folders; ignore all _-prefixed directories
during normal reads; and record every move, delete, overwrite, and restore point
in _CHANGES_BACKUP so the entire operation can be undone.
```

### 6. Undo A Prior Change Set

```text
Restore the change set <CHANGE_SET_ID> from _CHANGES_BACKUP and undo the
associated file moves, deletes, or overwrites. Repair any related
document_vault source references as part of the restore.
```

## Safer Variants

Use these when you want planning or dry-run behavior before mutation.

### Dry Run Reorganization

```text
Analyze the current folder layout across google1, google2, and icloud and
propose a cleaner structure, but do not apply any changes yet. Ignore all
_-prefixed folders during normal reads and explain what change sets would be
created if I approve the reorganization.
```

### Dry Run Dedupe

```text
Analyze google1, google2, and icloud for duplicates, but do not move or delete
anything yet. Ignore all _-prefixed folders during normal reads and report what
would be routed into _CHANGES_BACKUP if I approve the dedupe.
```

## Notes For Future Tooling

The intended tool-backed behavior behind these prompts is:

- read/list/search tools for ordinary discovery
- structured `document_vault` note creation tools
- dedupe and reorganization tools that emit reversible `change_set_id` values
- restore tools that can undo a full change set or a targeted subset

If the tool surface grows, update this document first so the operator language
and the actual plugin capabilities stay aligned.
