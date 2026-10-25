# MiniDatadog

MiniDatadog is an educational observability service built with FastAPI and
PostgreSQL. It collects request metrics, structured logs, and basic trace
spans, then displays them in a web dashboard.

## Run locally

Start PostgreSQL:

```bash
docker compose -f infra/docker-compose.yml up -d
```

Run the API:

```bash
.venv/bin/uvicorn backend.app.main:app --reload
```

Open the dashboard at <http://127.0.0.1:8000/dashboard>.

## Configuration

The application reads these environment variables:

| Variable | Description | Default |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | required |
| `SERVICE_NAME` | Service name attached to telemetry | required |
| `TELEMETRY_RETENTION_DAYS` | Number of days to retain metrics, logs, and traces | `5` |
| `MINIDATADOG_USERNAME` | Legacy setting; no longer used for dashboard access | unused |
| `MINIDATADOG_PASSWORD` | Legacy setting; no longer used for dashboard access | unused |
| `FORCE_HTTPS` | Adds HSTS headers when set to `true` behind HTTPS | disabled |
| `ALERT_WEBHOOK_URL` | Optional webhook URL for triggered alerts | disabled |
| `ALERT_COOLDOWN_SECONDS` | Minimum time between notifications for one rule | `900` |

Old telemetry is cleaned automatically during application startup according to
`TELEMETRY_RETENTION_DAYS`. The value must be a positive integer.

The dashboard and built-in API are publicly accessible. External project
telemetry remains isolated by the project's `X-API-Key`; keep those keys
private. When `ALERT_WEBHOOK_URL` is configured, the application sends a JSON `POST`
notification when a rule is triggered. Notifications are disabled by default
and are limited by `ALERT_COOLDOWN_SECONDS` (15 minutes by default).

The API adds security headers by default, including clickjacking protection,
MIME-sniffing protection, a restrictive referrer policy, and a Content Security
Policy. Enable `FORCE_HTTPS=true` only when the deployment terminates traffic
over HTTPS.

## Test

```bash
.venv/bin/python -m pytest backend/tests -q
```

## Main endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Application health |
| `GET /health/database` | PostgreSQL health |
| `GET /dashboard` | Observability dashboard |
| `GET /test/unique` | Create a uniquely identified remote test event |
| `POST /api/v1/projects` | Create an external application project and API key |
| `GET /api/v1/projects` | List registered projects with key prefixes |
| `POST /api/v1/api-keys/revoke` | Revoke a compromised or obsolete project API key |
| `POST /api/v1/ingest/metrics` | Ingest a metric from an external application |
| `POST /api/v1/ingest/metrics/batch` | Ingest a batch of metrics |
| `POST /api/v1/ingest/logs` | Ingest a log from an external application |
| `POST /api/v1/ingest/logs/batch` | Ingest a batch of structured logs |
| `POST /api/v1/ingest/traces` | Ingest a trace span from an external application |
| `POST /api/v1/ingest/traces/batch` | Ingest a batch of trace spans |
| `GET /api/v1/data/metrics` | Read the authenticated project's metrics |
| `GET /api/v1/data/logs` | Read the authenticated project's logs |
| `GET /api/v1/data/traces` | Read the authenticated project's traces |
| `GET /api/v1/data/summary` | Read aggregated project metrics summary |
| `GET /metrics` | Request metrics with filters and pagination |
| `GET /logs` | Structured logs with filters and pagination |
| `GET /traces` | Request trace spans with filters and pagination |
| `GET /traces/{request_id}` | Load one complete request timeline |
| `GET /traces/{request_id}/summary` | Load trace status and timing summary |
| `GET /alerts/triggered` | Currently triggered alerts |
| `GET /alerts/history` | Triggered and resolved alert events |

The paginated telemetry endpoints accept `limit` (1-500) and `offset` (0 or
greater). Metrics, logs, and traces also accept `since_seconds` for a positive
rolling time window. They return `X-Total-Count`, `X-Limit`, and `X-Offset`
headers.

To create a new test event from another location, open
`/test/unique?label=friend-location` or call it with `curl`. The response
contains a unique `event_id`; the request itself also creates a metric, log,
and trace with its own `X-Request-ID`.

### External application monitoring

Create a new project:

```bash
curl -X POST https://minidatadog.onrender.com/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"friend-shop"}'
```

The response contains a secure API key (`mdg_...`). Store it securely; it is only returned once when the project is created. External applications authenticate by passing this key in the `X-API-Key` header:

```bash
curl -X POST https://minidatadog.onrender.com/api/v1/ingest/metrics \
  -H "X-API-Key: mdg_your_project_key" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name":"friend-shop-api",
    "method":"GET",
    "path":"/orders",
    "status_code":200,
    "duration_ms":42.5,
    "request_id":"order-request-1"
  }'
```

Batch ingestion is also supported via `POST /api/v1/ingest/metrics/batch`, `POST /api/v1/ingest/logs/batch`, and `POST /api/v1/ingest/traces/batch`.

The key scopes every ingestion and read request to one project, ensuring strong multi-tenant data isolation. Keys are stored strictly as SHA-256 hashes. Ingestion endpoints enforce rate limiting (120 requests/minute per key), returning `429 Too Many Requests` with a `Retry-After` header when limits are exceeded.

If a key is compromised, it can be revoked immediately via:

```bash
curl -X POST https://minidatadog.onrender.com/api/v1/api-keys/revoke \
  -H "X-API-Key: mdg_your_project_key"
```

Once revoked, all subsequent ingestion or queries using that key are rejected with `401 Unauthorized`.

### Integration Examples and SDK

Executable examples and a lightweight Python client are available in the [`examples/`](./examples) directory:

- [`examples/minidatadog_client.py`](./examples/minidatadog_client.py): Python client SDK (`MiniDatadogClient`).
- [`examples/fastapi_integration.py`](./examples/fastapi_integration.py): Sample FastAPI application demonstrating automatic telemetry middleware.
- [`examples/curl_examples.sh`](./examples/curl_examples.sh): Shell script demonstrating project creation, single & batch ingestion, querying, and revocation.

Logs submitted through `POST /logs` may include `request_id` to correlate an
application log with an existing request trace.

Alert history records each alert lifecycle once. An event is marked
`TRIGGERED` when its condition first becomes true and `RESOLVED` when the
condition returns to normal.

Trace rows include a request ID. Paste that ID into the dashboard's
**Trace Details** search to inspect the matching request timeline. Each
timeline has a root HTTP span and a child request-processing span linked by
`parent_span_id`.

Request IDs in the Recent Traces table are clickable shortcuts to the
corresponding trace timeline.

Logs can be filtered by `request_id`, and request IDs in the Recent Logs table
link directly to the matching trace timeline.

Alert rules can be created and disabled from the dashboard. To test an alert,
create a rule for `demo-service`, trigger `/simulate-error`, and refresh the
dashboard. To test resolution, use a threshold that can move from true to
false, such as `average_duration_ms`, then change the threshold above the
current value.

If `ALERT_WEBHOOK_URL` is configured, active alert evaluations send a JSON
webhook notification. `ALERT_COOLDOWN_SECONDS` prevents repeated notifications
for the same rule; it defaults to 900 seconds.

## Deploy to Render

This repository includes [render.yaml](./render.yaml), which provisions a
Docker web service and a PostgreSQL database.

1. Push the repository to GitHub or GitLab.
2. In Render, choose **New > Blueprint** and select the repository.
3. Review the services from `render.yaml` and apply the blueprint.
4. Open the generated service URL and verify `/health` and `/dashboard`.

Render supplies the `PORT` variable to the Docker container. The service uses
the managed PostgreSQL connection string from the database resource, and
`FORCE_HTTPS=true` enables HSTS because Render terminates HTTPS at the edge.