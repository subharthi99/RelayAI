# RelayAI Local API

RelayAI provides a small authenticated HTTP API for local integrations.
It exposes stored pipeline definitions and execution receipts without allowing
remote pipeline mutation or action dispatch.

## Security boundary

- The server accepts only the literal bind address `127.0.0.1`.
- A bearer token of at least 32 characters is required at startup.
- All `/v1/*` routes require constant-time bearer-token comparison.
- `/health` is unauthenticated and returns only process status and package version.
- Responses include `Cache-Control: no-store` and
  `X-Content-Type-Options: nosniff`.
- The server has no CORS headers and is not intended for browser-origin access.
- The API is read-only. It cannot import pipelines, approve destinations, execute
  actions, or delete history.

Loopback binding is not a substitute for authentication: unrelated local
processes may be able to connect to localhost.

## Starting the API

Initialize a database and generate a token:

```sh
relayai database --database relayai.sqlite3 init
export RELAYAI_API_TOKEN="$(openssl rand -hex 32)"
relayai serve --database relayai.sqlite3 --port 8765
```

The process prints one JSON startup record:

```json
{
  "database": "relayai.sqlite3",
  "listen": "http://127.0.0.1:8765",
  "status": "serving"
}
```

Use `--token-env` to read a differently named environment variable:

```sh
relayai serve --database relayai.sqlite3 \
  --token-env MY_RELAYAI_TOKEN \
  --port 8765
```

Tokens are never accepted as command-line values.

## Authentication

```sh
curl \
  -H "Authorization: Bearer $RELAYAI_API_TOKEN" \
  http://127.0.0.1:8765/v1/pipelines
```

Missing or incorrect credentials return:

```http
HTTP/1.0 401 Unauthorized
Content-Type: application/json; charset=utf-8
Cache-Control: no-store

{"error":"unauthorized"}
```

## Endpoints

### `GET /health`

Does not require authentication.

```json
{
  "status": "ok",
  "version": "0.3.0"
}
```

### `GET /v1/pipelines`

Returns safe summaries ordered by pipeline ID.

```json
[
  {
    "id": "private-dictation",
    "local_only": true,
    "name": "Private dictation",
    "schema_version": 1
  }
]
```

### `GET /v1/pipelines/{pipeline_id}`

Returns the complete secret-free pipeline document. Pipeline IDs are URL-decoded
and cannot contain `/`.

Returns `404` when the pipeline does not exist.

### `GET /v1/runs`

Returns redacted receipt summaries in descending start-time order.

Optional query parameters:

- `pipeline_id` — exact pipeline ID filter.
- `limit` — integer from 1 through 1000; defaults to 50.

```json
[
  {
    "completed_at": 1785123456.0,
    "destination_statuses": [
      {
        "destination_id": "cursor",
        "status": "succeeded"
      }
    ],
    "id": "run-uuid",
    "pipeline_id": "private-dictation",
    "started_at": 1785123455.0,
    "status": "succeeded",
    "warning_count": 0
  }
]
```

Run summaries intentionally omit raw and refined transcript text.

### `GET /v1/runs/{run_id}`

Returns the complete stored `PipelineRun` receipt.

> [!WARNING]
> Full receipts may contain `raw_transcript` and `final_text`. Callers must treat
> this endpoint as sensitive local data and must not cache or forward responses.

Returns `404` when the run does not exist.

## Error responses

| Status | Error | Meaning |
| --- | --- | --- |
| `400` | `invalid_request` | Query or storage validation failed |
| `401` | `unauthorized` | Bearer token missing or incorrect |
| `404` | `not_found` | Route or requested record does not exist |

An invalid `limit` string returns `limit_must_be_an_integer`.

## Operational guidance

- Use a newly generated token rather than a human password.
- Store tokens in a user-scoped secret manager or protected process environment.
- Rotate the token whenever local process access is uncertain.
- Do not expose the port through SSH forwarding, containers, reverse proxies,
  tunnels, or public interfaces.
- Run the API under the same local user that owns the RelayAI database.
- Stop the process before moving or restoring its SQLite database.
- Assume full-run responses contain private speech-derived content.

## Deliberate omissions

The current API does not support:

- recording or audio upload;
- pipeline import, update, or deletion;
- execution preparation;
- destination approval or dispatch;
- credential management; or
- history deletion.

Those operations require stronger authorization, CSRF/origin considerations,
request idempotency, and concrete audio/provider adapters. They should not be
added as thin wrappers around unfinished functionality.
