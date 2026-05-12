# iCloud Index Plugin Design

Date: 2026-05-11
Status: Approved for planning
Repository: `C:\Code\iCloudPlugin`

## Goal

Build a current Codex/OpenAI-style local plugin that lets the user query iCloud Drive files by relevance. The plugin should support:

- read-only access only in v1
- direct iCloud access through Apple's private web flows
- extracted content indexing when possible
- a server-backed hybrid index for speed and relevance

The system should not depend on a local iCloud-synced folder copy as its primary source of truth.

## Scope

### In scope

- On-prem Linux service that maintains Apple web session state
- Dockerized deployment
- Postgres-backed metadata and extracted-content index
- Hybrid search over file metadata and extracted text
- Read-only retrieval of metadata, excerpts, and downloadable file handles
- Background refresh plus on-demand refresh
- Thin local Codex/OpenAI plugin that calls the service

### Out of scope for v1

- Upload, rename, move, or delete operations
- Public internet exposure without additional hardening
- Official Apple API support claim
- Full local mirroring of all file bytes
- Multi-tenant user management
- Semantic embeddings as a required search dependency

## Constraints

- Apple does not provide a supported public API for general iCloud Drive browsing in this use case.
- The system must use an unsupported private web approach and should isolate that fragility to the server side.
- Authentication should avoid storing the Apple password for normal steady-state operation.
- The service must stay read-only in v1.

## High-Level Architecture

The solution has two main parts:

1. A Linux `icloud-index-service` stack running on-prem in Docker.
2. A thin local plugin that exposes tools and delegates all data work to the service.

### Service responsibilities

- manage Apple web session state
- crawl configured iCloud Drive scopes
- download files temporarily for extraction when needed
- index metadata and extracted text in Postgres
- answer search and retrieval requests
- schedule refresh and extraction jobs

### Plugin responsibilities

- expose a small tool surface to Codex/OpenAI
- authenticate to the service with a plugin API token
- present search results, snippets, and file metadata
- request refresh actions when needed

## Components

### 1. `icloud-web-client`

Responsible for:

- authenticated communication with Apple private web endpoints
- listing folders and files
- reading metadata
- obtaining download URLs or file streams
- session refresh handling

Notes:

- this layer is the most fragile part of the system
- endpoint and auth behavior may drift when Apple changes the web app

### 2. `auth-session-manager`

Responsible for:

- browser-assisted login/bootstrap
- secure storage of session tokens/cookies
- encryption at rest for session material
- auth status reporting
- challenge/expiry detection

Design decisions:

- do not keep Apple credentials for normal operation
- support manual re-auth when Apple invalidates the session

### 3. `crawler`

Responsible for:

- walking configured iCloud Drive scopes
- collecting and updating metadata
- detecting changes through timestamps, etags, version markers, or equivalent signals
- queuing extraction work only when content changed or extraction is missing

### 4. `extractor`

Responsible for:

- temporary file retrieval
- text extraction for supported formats
- parser selection by MIME type and extension
- summary/snippet generation
- extraction status and failure recording

Supported-first formats for v1:

- `.txt`
- `.md`
- `.json`
- `.csv`
- `.pdf`
- common Office documents where reliable parser support exists

Unsupported or binary files should still be indexed as metadata-only records.

### 5. `query-service`

Responsible for:

- processing natural-language file search requests
- ranking by metadata and extracted text
- selecting top candidates for optional live verification or excerpt refresh
- returning structured results with snippets and retrieval info

### 6. `worker`

Responsible for:

- background extraction jobs
- background refresh jobs
- non-blocking long-running tasks

This should be a separate container or worker process so searches remain responsive while indexing runs.

## Deployment Model

The system runs on-prem in Docker containers:

- `icloud-index-service`
- `worker`
- `postgres`
- optional `reverse-proxy`

### Recommended network model

- keep the service private in v1
- avoid direct public exposure
- access through a private overlay network or tightly restricted proxy
- require service-level token authentication from the plugin

## Data Model

Postgres is the source of truth for index state.

### Core tables

`files`
- file id
- drive/container identifiers
- current name
- MIME hint
- extension
- size
- created/modified timestamps
- version marker
- active/deleted flags

`file_paths`
- file id
- canonical path
- parent path
- path display string
- path scope

`file_versions`
- file id
- version marker or etag
- content hash if known
- seen-at timestamp

`extracted_content`
- file id
- extracted plain text
- short snippet
- extraction status
- parser type
- extraction hash
- extracted-at timestamp
- content byte cap used

`sync_runs`
- sync run id
- scope
- start/end timestamps
- status
- counts for scanned, changed, extracted, failed
- error summary

`auth_sessions`
- session id
- encrypted session payload
- created-at
- expires-at
- last-validated-at
- status

`query_audit`
- query id
- query text
- request timestamp
- result count
- latency
- optional caller metadata

## Indexing Strategy

Use a hybrid metadata index, not a full local mirror and not live-only querying.

### What is stored persistently

- file metadata
- normalized paths
- extracted plain text where available
- short snippets/summaries
- hashes and version markers
- extraction status and sync history

### What is not stored long-term

- full source file bytes by default
- unsupported large binary payloads

### Refresh behavior

- scheduled background refresh over configured scopes
- on-demand refresh API for a scope or a file subset
- only re-extract when content changed or extraction is missing/stale

## Search and Ranking

### First pass

Use Postgres full-text search over:

- file name
- path
- extracted text
- stored snippet text

### Second pass reranking

Blend in:

- exact filename matches
- path keyword matches
- recency
- file type hints
- selective live fetch for the top candidates when local summary quality is weak

This keeps the default query fast while still allowing better results when the index needs help.

## Plugin Interface

The local plugin should remain intentionally small.

### Proposed tool surface

`search_icloud_files`
- inputs: `query`, `limit`, optional `path_scope`
- returns: ranked file results with metadata, snippet, and retrieval handle info

`get_icloud_file`
- inputs: `file_id`
- returns: metadata plus service-proxied download or fetch details

`get_icloud_file_excerpt`
- inputs: `file_id`, optional `max_chars`
- returns: excerpt text, extraction status, and freshness indicators

`refresh_icloud_index`
- inputs: optional `path_scope`, optional `max_files`
- returns: accepted job info and refresh status

## Security Model

### Trust boundaries

- Apple session state lives only on the server
- the plugin never handles raw Apple credentials directly
- plugin-to-service access uses a service token

### Required protections

- encrypted session storage at rest
- environment-variable or secret-mounted encryption key
- private network by default
- audit logs for refresh and query activity
- read-only enforcement in API and crawler layers

### Security tradeoffs

- the server is a high-value target because it holds iCloud session material and indexed content
- internet exposure raises risk substantially and should be avoided in v1

## Failure Handling

The system should fail explicitly and remain queryable whenever possible.

### Examples

- expired Apple session: return auth-needed status and keep last known index available
- extraction failure: store failure status, keep metadata searchable
- unsupported format: index metadata only
- oversized file: skip full extraction, mark reason, and continue
- sync interruption: record partial run and resume later

## Testing and Validation Plan

### Automated tests

- session state and token encryption unit tests
- metadata normalization tests
- crawler change-detection tests
- extractor tests for supported file types
- query ranking tests over seeded Postgres fixtures
- API contract tests for plugin-facing endpoints

### Integration tests

- Docker Compose stack boot
- Postgres migrations
- refresh job scheduling
- search over seeded fixture files
- degraded-mode behavior when Apple auth is unavailable

### Manual validation

- bootstrap session through browser-assisted login
- run initial scope crawl
- verify indexed results for a mixed file set
- confirm metadata-only handling for unsupported files
- confirm excerpt retrieval for supported files

## Operational Boundaries for v1

- read-only only
- configured root scopes instead of assuming the full drive
- private on-prem deployment
- manual re-auth support is acceptable
- no promise of Apple web compatibility stability

## Recommended Implementation Order

1. Docker Compose stack with service, worker, and Postgres
2. Postgres schema and migrations
3. Service API skeleton
4. Apple session bootstrap and secure storage
5. Metadata crawler
6. Extraction pipeline
7. Search and ranking
8. Thin local plugin client
9. End-to-end validation against a real iCloud account

## Risks

- Apple can change private endpoints or auth flows at any time
- Linux-host auth bootstrap may need browser-assisted flow from another machine
- content extraction quality will vary by format
- indexing very large drives needs caps, batching, and careful refresh controls

## Decision Summary

Approved decisions:

- build a current Codex/OpenAI-style local plugin
- target `C:\Code\iCloudPlugin`
- use direct iCloud access through Apple private web flows
- keep v1 read-only
- extract content when possible
- use a hybrid metadata index
- run an on-prem Linux service
- store index state in Postgres
- deploy with Docker containers

