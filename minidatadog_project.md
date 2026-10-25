# MiniDatadog --- Application Observability Platform

> A learning project that collects application telemetry, visualizes
> service health, correlates logs with traces, and alerts on performance
> problems.

## 1. Project Overview

MiniDatadog is a lightweight observability platform inspired by tools
such as Datadog. It helps developers understand what is happening inside
an application by collecting and presenting metrics, logs, and
distributed traces.

The project should demonstrate practical backend engineering, API
design, database modeling, instrumentation, asynchronous processing,
testing, containerization, and performance measurement.

**Important:** This is an educational implementation, not a
production-ready replacement for commercial monitoring platforms.

## 2. Problem Statement

When an application becomes slow or starts failing, developers need to
answer questions such as:

-   Which endpoint has the highest latency?
-   What percentage of requests are failing?
-   Which service or operation is responsible for a slow request?
-   What errors happened around the time of an incident?
-   Did performance improve after a fix?

MiniDatadog centralizes this evidence in one dashboard.

## 3. Goals

-   Collect request counts, response times, and error rates.
-   Store telemetry and make it queryable by service and time range.
-   Visualize service health and latency percentiles.
-   Collect structured logs and correlate them with trace IDs.
-   Support configurable alert rules and cooldowns.
-   Use distributed tracing to follow requests across services.
-   Provide repeatable load tests and publish measured results.
-   Run locally using Docker Compose.

## 4. Core Features

### MVP --- Build these first

1.  **Demo application**
    -   Create a small FastAPI application with endpoints such as `/`,
        `/products`, and `/checkout`.
    -   Add configurable simulated latency and errors for testing.
    -   Record request duration, status code, route, and service name.
2.  **Telemetry ingestion API**
    -   Accept validated telemetry payloads.
    -   Add timestamps and validate required fields.
    -   Return useful HTTP status codes for invalid or accepted data.
    -   Include authentication for ingestion clients before exposing the
        service publicly.
3.  **Metrics storage and queries**
    -   Store telemetry in PostgreSQL.
    -   Query by service, metric, and time range.
    -   Aggregate request counts, error rates, and latency percentiles.
4.  **Dashboard**
    -   Show request rate, error rate, P50/P95/P99 latency, and service
        health.
    -   Add time-range and service filters.
    -   Refresh data periodically without overwhelming the backend.
5.  **Alerting**
    -   Allow users to configure rules such as error rate above a
        threshold.
    -   Evaluate rules on a schedule.
    -   Add cooldowns and alert history to prevent repeated
        notifications.
    -   Start with an in-app alert; add email or webhook delivery later.

### Advanced Features

-   **Centralized logs:** Search structured logs by severity, service,
    time range, and trace ID.
-   **Distributed tracing:** Visualize spans and their parent-child
    relationships across services.
-   **Incident replay:** Reproduce a known latency or error scenario and
    compare before/after metrics.
-   **Queue and batching:** Buffer telemetry and batch writes to improve
    throughput.
-   **Anomaly detection:** Add a simple baseline-based detector only
    after threshold alerting works reliably.
-   **Multi-user access:** Add accounts, roles, and project-level access
    controls if time permits.

## 5. Suggested Technology Stack

  -----------------------------------------------------------------------
  Layer                   Technology              Why
  ----------------------- ----------------------- -----------------------
  Backend API             Python + FastAPI        Typed APIs and
                                                  asynchronous support

  Frontend                React + TypeScript      Interactive dashboard

  Database                PostgreSQL              Durable telemetry and
                                                  metadata storage

  Queue/cache             Redis                   Optional buffering and
                                                  background jobs

  Instrumentation         OpenTelemetry           Standard telemetry APIs
                                                  and exporters

  Charts                  Recharts or another     Time-series
                          React chart library     visualization

  Testing                 Pytest                  Unit and integration
                                                  tests

  Load testing            Locust                  Repeatable traffic
                                                  generation

  Containers              Docker + Docker Compose Reproducible local
                                                  environment

  CI                      GitHub Actions          Automated checks on
                                                  every change
  -----------------------------------------------------------------------

**Keep the first version small:** PostgreSQL can be enough for the MVP.
Add Redis only when you have a concrete buffering or
background-processing need.

## 6. High-Level Architecture

``` text
                 ┌──────────────────────┐
                 │ Demo application(s)  │
                 │ API + instrumentation│
                 └──────────┬───────────┘
                            │ telemetry
                            ▼
                 ┌──────────────────────┐
                 │ Ingestion API         │
                 │ validation/auth       │
                 └──────────┬───────────┘
                            │
                  optional queue/batching
                            │
                            ▼
                 ┌──────────────────────┐
                 │ PostgreSQL            │
                 │ metrics/logs/spans    │
                 └──────────┬───────────┘
                            │ query
                            ▼
                 ┌──────────────────────┐
                 │ Query + alert engine  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ React dashboard       │
                 │ charts, traces, alerts│
                 └──────────────────────┘
```

## 7. Repository Structure

A practical starting layout:

``` text
minidatadog/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── workers/
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── api/
│   │   └── charts/
│   ├── package.json
│   └── Dockerfile
├── demo-service/
│   ├── app/
│   ├── tests/
│   └── Dockerfile
├── infra/
│   └── docker-compose.yml
├── load-tests/
│   └── locustfile.py
├── docs/
│   ├── architecture.md
│   └── benchmark-results.md
├── .env.example
├── .gitignore
└── README.md
```

## 8. Initial Data Model

Start with a small, explicit schema. Adjust it as the design evolves.

### `services`

-   `id`: primary key
-   `name`: unique service name
-   `environment`: e.g. `local`, `staging`
-   `created_at`: creation timestamp

### `metric_points`

-   `id`: primary key
-   `service_id`: service reference
-   `metric_name`: e.g. `request_duration_ms`
-   `value`: numeric value
-   `timestamp`: event time
-   `attributes`: JSONB dimensions such as route, method, and status
    code

### `logs`

-   `id`: primary key
-   `service_id`: service reference
-   `timestamp`: event time
-   `severity`: debug/info/warn/error
-   `message`: structured message
-   `trace_id`: nullable trace correlation ID
-   `attributes`: JSONB metadata

### `spans`

-   `trace_id`: trace identifier
-   `span_id`: span identifier
-   `parent_span_id`: nullable parent
-   `service_id`: service reference
-   `operation_name`: operation or route
-   `start_time`: start timestamp
-   `duration_ms`: duration
-   `status`: success or error
-   `attributes`: JSONB metadata

### `alert_rules` and `alert_events`

Store each rule's metric, comparison operator, threshold, evaluation
window, enabled state, and cooldown. Record each triggered event with
its timestamp, value, and status.

For a larger implementation, consider time-based partitioning, retention
policies, indexes, and a dedicated time-series store. Do not add those
until measurements justify them.

## 9. API Design

Possible first endpoints:

  Method   Endpoint                      Purpose
  -------- ----------------------------- -----------------------------
  `POST`   `/api/v1/metrics`             Ingest metric points
  `POST`   `/api/v1/logs`                Ingest structured logs
  `POST`   `/api/v1/spans`               Ingest spans
  `GET`    `/api/v1/services`            List monitored services
  `GET`    `/api/v1/metrics/query`       Query metrics by time range
  `GET`    `/api/v1/logs`                Search logs
  `GET`    `/api/v1/traces/{trace_id}`   Retrieve a trace
  `GET`    `/api/v1/alerts`              List alert events
  `POST`   `/api/v1/alert-rules`         Create an alert rule
  `GET`    `/health`                     Health check

Use request/response schemas, pagination where needed, clear error
messages, and API versioning. Never allow a client-supplied query to
bypass authorization or create unbounded database work.

## 10. Six-Week Implementation Plan

### Week 1 --- Instrumentation and ingestion

-   Build a demo API with normal and deliberately slow/failing
    endpoints.
-   Measure request duration and status codes.
-   Implement ingestion schemas and validation.
-   Add unit tests.

**Deliverable:** Telemetry can be sent to the backend.

### Week 2 --- Persistence and queries

-   Add PostgreSQL and migrations.
-   Store metric points.
-   Implement time-range queries and aggregations.
-   Add indexes based on the query patterns.

**Deliverable:** Stored telemetry can be queried correctly.

### Week 3 --- Dashboard

-   Build service list and service detail pages.
-   Display request rate, error rate, and latency percentiles.
-   Add time-range filters and loading/error states.

**Deliverable:** A usable monitoring dashboard.

### Week 4 --- Logs and traces

-   Integrate OpenTelemetry instrumentation.
-   Ingest structured logs and spans.
-   Correlate logs with traces.
-   Display a trace waterfall or span tree.

**Deliverable:** A request can be followed across instrumented
operations.

### Week 5 --- Alerts and resilience

-   Add configurable alert rules.
-   Implement evaluation windows and cooldowns.
-   Handle database errors and malformed payloads.
-   Add bounded queues or batching only if needed.

**Deliverable:** A simulated incident produces a useful alert.

### Week 6 --- Benchmark and release

-   Add repeatable Locust scenarios.
-   Measure throughput, latency, and error rate.
-   Test recovery from failures.
-   Dockerize the complete stack.
-   Write architecture and benchmark documentation.
-   Publish a short demo video and screenshots.

**Deliverable:** A reproducible project with documented evidence.

## 11. Testing and Evaluation

Do not invent benchmark numbers. Measure them on your own machine or
deployment and record the environment.

Track:

-   Accepted telemetry events per second.
-   P50/P95/P99 ingestion latency.
-   Query latency for a defined time range.
-   Error rate under a defined load.
-   Memory and CPU usage.
-   Behavior during database downtime or queue saturation.
-   Alert detection delay and duplicate-alert behavior.

For fair comparisons, record CPU/RAM, database configuration, event
payload size, concurrency, test duration, and software version. Repeat
each test and report the method as well as the result.

## 12. Security and Reliability Checklist

-   [ ] Authenticate ingestion clients.
-   [ ] Validate payload sizes and field types.
-   [ ] Use parameterized database queries.
-   [ ] Keep secrets in environment variables, not source control.
-   [ ] Redact tokens, passwords, and personal data from logs.
-   [ ] Add request timeouts and sensible rate limits.
-   [ ] Bound queues and define behavior when full.
-   [ ] Retry transient failures carefully, with backoff.
-   [ ] Avoid infinite retry loops and duplicate alert storms.
-   [ ] Add health checks and structured application logs.
-   [ ] Document data retention and deletion behavior.

## 13. Definition of Done

The MVP is complete when:

-   [ ] A demo service produces telemetry.
-   [ ] The ingestion API validates and stores it.
-   [ ] The dashboard displays real stored data.
-   [ ] Error-rate and latency alerts work in a simulated incident.
-   [ ] Automated tests pass in CI.
-   [ ] The complete system starts from documented commands.
-   [ ] A benchmark report describes the test environment and measured
    results.
-   [ ] The README contains screenshots, architecture, limitations, and
    a demo link.

## 14. Resume Bullet

Use this only after the relevant features are implemented, and replace
the placeholders with measured results:

> Built MiniDatadog, a containerized observability platform using
> Python, FastAPI, PostgreSQL, React, and OpenTelemetry to collect
> application metrics, correlate distributed traces with logs, and
> trigger configurable latency and error-rate alerts. Benchmarked
> ingestion throughput and query latency under **\[documented
> workload\]**, achieving **\[measured result\]**.

Do not claim production-scale performance, AI diagnosis, or distributed
fault tolerance unless you have implemented and tested those
capabilities.

## 15. Suggested README Demo

A strong demo should show this sequence:

1.  Open the dashboard with a healthy service.
2.  Generate traffic against the demo API.
3.  Enable a simulated slow endpoint.
4.  Show P95 latency increasing and an alert firing.
5.  Open a trace and identify the slow operation.
6.  Fix the delay and show the metrics returning toward baseline.

This tells a clear engineering story: **detect → investigate → identify
→ fix → verify**.

## 16. Learning Resources

-   FastAPI: https://fastapi.tiangolo.com/
-   OpenTelemetry: https://opentelemetry.io/docs/
-   PostgreSQL: https://www.postgresql.org/docs/
-   Docker Compose: https://docs.docker.com/compose/
-   React: https://react.dev/
-   Locust: https://docs.locust.io/

------------------------------------------------------------------------

**Recommended starting point:** Build the demo API, ingestion endpoint,
PostgreSQL persistence, and one dashboard chart first. Get that vertical
slice working before adding logs, traces, queues, and advanced alerting.
