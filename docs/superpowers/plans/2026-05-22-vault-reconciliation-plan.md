# Vault Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe background vault reconciler that repairs stale note-to-file linkage using canonical metadata without changing refresh semantics or sync direction.

**Architecture:** Implement reconciliation as a small service module owned by `iCloudPlugin`, backed by existing classification state and mirrored file records. Run it from the classification worker so it stays near note-producing background work, use canonical hash-first matching with conservative filename fallback, and only rewrite note metadata when the match is confident.

**Tech Stack:** Python 3, pytest, SQLAlchemy models, background worker loop, filesystem note edits

---

### Task 1: Add reconciliation tests first

**Files:**
- Create: `C:\Code\iCloudPlugin\tests\test_vault_reconciliation.py`
- Read: `C:\Code\iCloudPlugin\src\icloud_index_service\services\classification_submission.py`
- Read: `C:\Code\iCloudPlugin\src\icloud_index_service\classification_worker.py`

- [ ] **Step 1: Write a failing confident-hash-match test**
- [ ] Seed:
  - one classified file state with a note path
  - a note whose canonical source path is stale
  - a live mirrored replacement file with the same canonical hash
- [ ] Assert reconciliation updates the note metadata and keeps a review-safe result structure.
- [ ] **Step 2: Run**
  - `python -m pytest tests/test_vault_reconciliation.py -q`
- [ ] **Expected**
  - fail because no reconciler exists

- [ ] **Step 3: Write a failing ambiguity test**
- [ ] Seed multiple candidate files and assert the note is left untouched.
- [ ] **Step 4: Run**
  - `python -m pytest tests/test_vault_reconciliation.py -q`
- [ ] **Expected**
  - fail because no conservative reconciliation path exists

### Task 2: Implement the reconciler

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\vault_reconciliation.py`
- Modify: `C:\Code\iCloudPlugin\src\icloud_index_service\classification_worker.py`
- Modify: `C:\Code\iCloudPlugin\docker-compose.yml`
- Modify if needed: `C:\Code\iCloudPlugin\README.md`
- Modify if needed: `C:\Code\iCloudPlugin\docs\operations.md`

- [ ] **Step 1: Add vault-root configuration**
- [ ] Introduce a classifier vault root env contract for reconciliation and make the classification worker able to write to the mounted vault path.
- [ ] **Step 2: Implement note parsing and safe line-level updates**
- [ ] Read only the frontmatter fields owned by reconciliation and avoid broad markdown rewrites.
- [ ] **Step 3: Implement match selection**
- [ ] Prefer canonical hash matches, then exact-name, then close-name fallback.
- [ ] Return unverified/ambiguous results without rewriting when confidence is not high enough.
- [ ] **Step 4: Call reconciliation from the classification worker**
- [ ] Run a small bounded reconciliation pass each poll without blocking job processing.

### Task 3: Validate background behavior and config wiring

**Files:**
- Modify if needed: `C:\Code\iCloudPlugin\tests\test_health_api.py`
- Test: `C:\Code\iCloudPlugin\tests\test_vault_reconciliation.py`
- Test: `C:\Code\iCloudPlugin\tests\test_classification_submission.py`

- [ ] **Step 1: Run focused tests**
  - `python -m pytest tests/test_vault_reconciliation.py tests/test_classification_submission.py -q`
- [ ] **Step 2: Run worker/config regressions**
  - `python -m pytest tests/test_health_api.py tests/test_crawler.py -q`
- [ ] **Step 3: Update operator docs**
- [ ] Document the new vault-root env and the fact that this first pass is still reconciliation over a one-way mirror, not bidirectional sync.
