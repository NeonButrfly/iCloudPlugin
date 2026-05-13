# Operations

## Start the stack

```bash
docker compose up --build
```

## Bootstrap Apple session

1. Open the auth bootstrap URL exposed by the service.
2. Complete the Apple web sign-in flow from a normal browser on another machine if the Linux host is headless.
3. Confirm `/auth/status` reports a usable session before relying on fresh refresh jobs.

Current limitation:
- the browser-assisted Apple web client in the repo is still a placeholder, so the service can report auth/bootstrap status but cannot yet complete a live iCloud Drive refresh crawl end to end

## Local plugin

1. Run `python -m pip install -e .` from the repo root.
2. Keep the service reachable at `ICLOUD_INDEX_SERVICE_URL`, or leave it on the default `http://127.0.0.1:8080`.
3. Use the repo-local plugin in `plugins/icloud-drive`.

## Degraded mode

- Search and file APIs return controlled `503` responses when the database is unavailable.
- Auth-needed responses should preserve whether cached results exist so callers can decide whether to surface stale-but-useful data.

## Upgrade hooks

- AI categorization stays suggestion-only in this rollout: prompts should yield category, confidence, and reasoning, not move files.
- Markdown collections should aggregate summaries with clear provenance back to indexed source files.
