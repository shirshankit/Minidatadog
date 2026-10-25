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
| `GET /alerts/triggered` | Currently triggered alerts |
| `GET /alerts/history` | Triggered and resolved alert events |

The paginated telemetry endpoints accept `limit` (1-500) and `offset` (0 or
greater). They return `X-Total-Count`, `X-Limit`, and `X-Offset` headers.

Alert history records each alert lifecycle once. An event is marked
`TRIGGERED` when its condition first becomes true and `RESOLVED` when the
condition returns to normal.

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