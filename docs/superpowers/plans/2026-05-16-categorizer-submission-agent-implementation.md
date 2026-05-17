## Categorizer Submission Agent Implementation Plan

Date: 2026-05-16
Issue: #7
Milestone: `v1 - Private iCloud Index Service`

### Objective

Implement a durable parallel categorizer submission agent inside `iCloudPlugin`
that backfills already indexed files, keeps up with new or changed files, and
pushes full-file uploads to the classifier API without blocking the existing
metadata refresh path.

### Execution Shape

1. Add failing tests for:
   - classification priority ordering
   - backfill queue creation from indexed files
   - duplicate active-job suppression
   - classifier submission success persistence
   - retry and permanent failure handling
   - compose wiring for classifier worker and env
2. Add schema support:
   - `classification_jobs`
   - `classification_states`
   - model registration
   - Alembic migration
3. Implement the classification services:
   - source fingerprinting
   - priority bucketing
   - backfill enqueue
   - incremental enqueue helpers
   - classifier API upload client
4. Add a dedicated classification worker lane and compose service so
   categorization runs in parallel with metadata ingestion.
5. Update docs and operational configuration, then validate end to end with
   focused tests, full `pytest`, and `docker compose config`.

### Guardrails

- Keep metadata refresh behavior unchanged unless required for integration.
- Treat classifier API success as the primary completion signal.
- Submit full files from the mirrored filesystem source.
- Default classification concurrency to `2`, configurable to `4`.
