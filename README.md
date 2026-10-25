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
| `MINIDATADOG_USERNAME` | Optional Basic Authentication username | disabled |
| `MINIDATADOG_PASSWORD` | Optional Basic Authentication password | disabled |
| `FORCE_HTTPS` | Adds HSTS headers when set to `true` behind HTTPS | disabled |
| `ALERT_WEBHOOK_URL` | Optional webhook URL for triggered alerts | disabled |
| `ALERT_COOLDOWN_SECONDS` | Minimum time between notifications for one rule | `900` |

Old telemetry is cleaned automatically during application startup according to
`TELEMETRY_RETENTION_DAYS`. The value must be a positive integer.

When `ALERT_WEBHOOK_URL` is configured, the application sends a JSON `POST`
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
4. Set `MINIDATADOG_USERNAME` and `MINIDATADOG_PASSWORD` in the Render
   dashboard. These values are intentionally not stored in the repository.
5. Open the generated service URL and verify `/health` and `/dashboard`.

Render supplies the `PORT` variable to the Docker container. The service uses
the managed PostgreSQL connection string from the database resource, and
`FORCE_HTTPS=true` enables HSTS because Render terminates HTTPS at the edge.