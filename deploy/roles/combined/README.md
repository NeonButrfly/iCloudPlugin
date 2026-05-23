# Combined Role

Runs cloudsync, API, and classifier roles together on one host when desired.

Use this only when one machine should own:

- mirrored-drive crawl
- operator/API surface
- classifier note generation

Primary services in `docker-compose.yml`:

- `postgres`
- `migrate`
- `service`
- `worker`
- `classification-worker`
- `ollama`
- `classifier-api`
