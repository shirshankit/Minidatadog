import base64
import binascii
import hmac
import os
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.templating import Jinja2Templates

from backend.app.database import (
    check_database_connection,
    cleanup_old_telemetry,
    close_database_pool,
    count_application_logs,
    count_metrics,
    count_trace_spans,
    create_alert_rule,
    create_application_log,
    create_trace_span,
    create_external_project,
    disable_alert_rule,
    evaluate_alert_rules,
    fetch_alert_rules,
    fetch_alert_history,
    fetch_application_logs,
    fetch_metrics,
    fetch_metrics_summary,
    fetch_trace_spans,
    fetch_trace_summary,
    fetch_external_logs,
    fetch_external_metrics,
    fetch_external_traces,
    get_external_project_id,
    ingest_external_log,
    ingest_external_metric,
    ingest_external_trace,
    get_service_name,
    initialize_database,
    open_database_pool,
    save_metric,
)

from backend.app.metrics import record_metric
from backend.app.notifications import notify_triggered_alerts


from backend.app.schemas import (
    AlertRuleCreate,
    AlertRuleResponse,
    AlertHistoryResponse,
    ApplicationLogCreate,
    ApplicationLogResponse,
    MetricResponse,
    MetricsSummaryResponse,
    TriggeredAlertResponse,
    TraceSpanResponse,
    TraceSummaryResponse,
    ExternalLogCreate,
    ExternalMetricCreate,
    ExternalProjectCreate,
    ExternalProjectResponse,
    ExternalTraceCreate,
    ExternalIngestResponse,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    open_database_pool()
    initialize_database()
    retention_days = int(os.getenv("TELEMETRY_RETENTION_DAYS", "5"))
    cleanup_old_telemetry(retention_days=retention_days)

    yield

    close_database_pool()


app = FastAPI(
    title="MiniDatadog Demo Service",
    lifespan=lifespan,
)
templates = Jinja2Templates(
    directory="backend/app/templates"
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'"
    )
    if os.getenv("FORCE_HTTPS", "").lower() == "true":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response

@app.middleware("http")
async def require_basic_auth(request: Request, call_next):
    if (
        request.url.path == "/health"
        or request.url.path.startswith("/api/v1/ingest")
        or request.url.path.startswith("/api/v1/data")
    ):
        return await call_next(request)

    username = os.getenv("MINIDATADOG_USERNAME")
    password = os.getenv("MINIDATADOG_PASSWORD")

    if username is None and password is None:
        return await call_next(request)

    if not username or not password:
        return Response(
            content="Authentication configuration is incomplete",
            status_code=500,
        )

    authorization = request.headers.get("Authorization", "")
    scheme, _, encoded_credentials = authorization.partition(" ")

    if scheme.lower() != "basic" or not encoded_credentials:
        return Response(
            content="Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        decoded_credentials = base64.b64decode(
            encoded_credentials,
            validate=True,
        ).decode("utf-8")
        supplied_username, supplied_password = (
            decoded_credentials.split(":", 1)
        )
    except (ValueError, UnicodeDecodeError, binascii.Error):
        supplied_username = ""
        supplied_password = ""

    if not (
        hmac.compare_digest(supplied_username, username)
        and hmac.compare_digest(supplied_password, password)
    ):
        return Response(
            content="Invalid credentials",
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    return await call_next(request)


def require_external_project(x_api_key: str | None) -> int:
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key header is required",
        )
    project_id = get_external_project_id(x_api_key)
    if project_id is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return project_id


@app.middleware("http")
async def measure_request_time(request: Request, call_next):
    request_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    start_time = perf_counter()

    response = await call_next(request)

    duration_ms = (perf_counter() - start_time) * 1000

    record_metric(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )

    save_metric(
        service_name=get_service_name(),
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        request_id=request_id,
    )

    log_level = (
        "ERROR"
        if response.status_code >= 500
        else "WARNING"
        if response.status_code >= 400
        else "INFO"
    )

    create_application_log(
        service_name=get_service_name(),
        level=log_level,
        message=(
            f"{request.method} {request.url.path} "
            f"returned {response.status_code}"
        ),
        request_id=request_id,
    )

    finished_at = datetime.now(timezone.utc)
    root_span = create_trace_span(
        request_id=request_id,
        service_name=get_service_name(),
        operation=f"{request.method} {request.url.path}",
        status_code=response.status_code,
        duration_ms=duration_ms,
        started_at=started_at,
        finished_at=finished_at,
    )
    create_trace_span(
        request_id=request_id,
        service_name=get_service_name(),
        operation="request.processing",
        status_code=response.status_code,
        duration_ms=duration_ms,
        started_at=started_at,
        finished_at=finished_at,
        parent_span_id=int(root_span["id"]),
    )

    response.headers["X-Process-Time-ms"] = f"{duration_ms:.2f}"
    response.headers["X-Request-ID"] = request_id

    return response


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/health/database")
def database_health_check() -> dict[str, str]:
    if not check_database_connection():
        raise HTTPException(
            status_code=503,
            detail="Database health check failed",
        )

    return {
        "status": "ok",
        "database": "ok",
    }


@app.post(
    "/api/v1/projects",
    response_model=ExternalProjectResponse,
)
def create_external_project_endpoint(
    project: ExternalProjectCreate,
) -> ExternalProjectResponse:
    return ExternalProjectResponse(**create_external_project(project.name))


@app.post(
    "/api/v1/ingest/metrics",
    response_model=ExternalIngestResponse,
)
def ingest_metric_endpoint(
    metric: ExternalMetricCreate,
    x_api_key: str | None = Header(default=None),
) -> ExternalIngestResponse:
    project_id = require_external_project(x_api_key)
    return ExternalIngestResponse(
        id=ingest_external_metric(
            project_id=project_id,
            service_name=metric.service_name,
            method=metric.method,
            path=metric.path,
            status_code=metric.status_code,
            duration_ms=metric.duration_ms,
            request_id=metric.request_id,
        )
    )


@app.post(
    "/api/v1/ingest/logs",
    response_model=ExternalIngestResponse,
)
def ingest_log_endpoint(
    log: ExternalLogCreate,
    x_api_key: str | None = Header(default=None),
) -> ExternalIngestResponse:
    project_id = require_external_project(x_api_key)
    return ExternalIngestResponse(
        id=ingest_external_log(
            project_id=project_id,
            service_name=log.service_name,
            level=log.level,
            message=log.message,
            request_id=log.request_id,
        )
    )


@app.post(
    "/api/v1/ingest/traces",
    response_model=ExternalIngestResponse,
)
def ingest_trace_endpoint(
    trace: ExternalTraceCreate,
    x_api_key: str | None = Header(default=None),
) -> ExternalIngestResponse:
    if trace.finished_at < trace.started_at:
        raise HTTPException(
            status_code=422,
            detail="finished_at must be after started_at",
        )
    project_id = require_external_project(x_api_key)
    return ExternalIngestResponse(
        id=ingest_external_trace(
            project_id=project_id,
            request_id=trace.request_id,
            service_name=trace.service_name,
            operation=trace.operation,
            status_code=trace.status_code,
            duration_ms=trace.duration_ms,
            started_at=trace.started_at,
            finished_at=trace.finished_at,
            parent_span_id=trace.parent_span_id,
        )
    )


@app.get("/api/v1/data/metrics")
def list_external_metrics(
    limit: int = Query(default=100, ge=1, le=500),
    x_api_key: str | None = Header(default=None),
) -> list[dict]:
    return fetch_external_metrics(require_external_project(x_api_key), limit)


@app.get("/api/v1/data/logs")
def list_external_logs(
    limit: int = Query(default=100, ge=1, le=500),
    x_api_key: str | None = Header(default=None),
) -> list[dict]:
    return fetch_external_logs(require_external_project(x_api_key), limit)


@app.get("/api/v1/data/traces")
def list_external_traces(
    limit: int = Query(default=100, ge=1, le=500),
    x_api_key: str | None = Header(default=None),
) -> list[dict]:
    return fetch_external_traces(require_external_project(x_api_key), limit)

@app.post(
    "/alerts/rules",
    response_model=AlertRuleResponse,
)
def create_alert_rule_endpoint(
    alert_rule: AlertRuleCreate,
) -> AlertRuleResponse:
    return AlertRuleResponse(
        **create_alert_rule(
            service_name=alert_rule.service_name,
            metric=alert_rule.metric,
            operator=alert_rule.operator,
            threshold=alert_rule.threshold,
        )
    )


@app.get(
    "/alerts/rules",
    response_model=list[AlertRuleResponse],
)
def list_alert_rules() -> list[AlertRuleResponse]:
    return [
        AlertRuleResponse(**alert_rule)
        for alert_rule in fetch_alert_rules()
    ]


@app.delete("/alerts/rules/{rule_id}", status_code=204)
def disable_alert_rule_endpoint(rule_id: int) -> None:
    if not disable_alert_rule(rule_id):
        raise HTTPException(
            status_code=404,
            detail="Alert rule not found",
        )


@app.get(
    "/alerts/triggered",
    response_model=list[TriggeredAlertResponse],
)
def list_triggered_alerts() -> list[TriggeredAlertResponse]:
    triggered_alerts = evaluate_alert_rules()
    notify_triggered_alerts(triggered_alerts)
    return [
        TriggeredAlertResponse(**alert)
        for alert in triggered_alerts
    ]


@app.get(
    "/alerts/history",
    response_model=list[AlertHistoryResponse],
)
def list_alert_history(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AlertHistoryResponse]:
    return [
        AlertHistoryResponse(**alert)
        for alert in fetch_alert_history(limit=limit)
    ]

@app.post(
    "/logs",
    response_model=ApplicationLogResponse,
)
def create_log_endpoint(
    log: ApplicationLogCreate,
) -> ApplicationLogResponse:
    return ApplicationLogResponse(
        **create_application_log(
            service_name=log.service_name,
            level=log.level,
            message=log.message,
            request_id=log.request_id,
        )
    )


@app.get(
    "/logs",
    response_model=list[ApplicationLogResponse],
)
def list_logs(
    response: Response,
    service_name: str | None = Query(default=None, min_length=1),
    level: str | None = Query(default=None, min_length=1),
    request_id: str | None = Query(default=None, min_length=1),
    since_seconds: float | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ApplicationLogResponse]:
    logs = [
        ApplicationLogResponse(**log)
        for log in fetch_application_logs(
            service_name=service_name,
            level=level,
            request_id=request_id,
            since_seconds=since_seconds,
            limit=limit,
            offset=offset,
        )
    ]
    response.headers["X-Total-Count"] = str(
        count_application_logs(
            service_name=service_name,
            level=level,
            request_id=request_id,
            since_seconds=since_seconds,
        )
    )
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    return logs


@app.get(
    "/traces",
    response_model=list[TraceSpanResponse],
)
def list_traces(
    response: Response,
    request_id: str | None = Query(default=None, min_length=1),
    service_name: str | None = Query(default=None, min_length=1),
    since_seconds: float | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[TraceSpanResponse]:
    traces = [
        TraceSpanResponse(**trace)
        for trace in fetch_trace_spans(
            request_id=request_id,
            service_name=service_name,
            since_seconds=since_seconds,
            limit=limit,
            offset=offset,
        )
    ]
    response.headers["X-Total-Count"] = str(
        count_trace_spans(
            request_id=request_id,
            service_name=service_name,
            since_seconds=since_seconds,
        )
    )
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    return traces


@app.get(
    "/traces/{request_id}",
    response_model=list[TraceSpanResponse],
)
def get_trace_by_request_id(
    request_id: str,
) -> list[TraceSpanResponse]:
    return [
        TraceSpanResponse(**trace)
        for trace in fetch_trace_spans(
            request_id=request_id,
            limit=500,
        )
    ]


@app.get(
    "/traces/{request_id}/summary",
    response_model=TraceSummaryResponse,
)
def get_trace_summary(
    request_id: str,
) -> TraceSummaryResponse:
    summary = fetch_trace_summary(request_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return TraceSummaryResponse(**summary)


@app.get("/products")
def list_products() -> list[dict[str, int | str]]:
    return [
        {"id": 1, "name": "Keyboard", "price": 49},
        {"id": 2, "name": "Mouse", "price": 25},
        {"id": 3, "name": "Monitor", "price": 199},
    ]


@app.get("/test/unique")
def create_unique_test_event(
    label: str = Query(default="friend-test", min_length=1, max_length=80),
) -> dict[str, str]:
    event_id = str(uuid4())
    return {
        "status": "ok",
        "message": "Unique test event created",
        "event_id": event_id,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/simulate-error")
def simulate_error() -> None:
    raise HTTPException(
        status_code=500,
        detail="Simulated service failure",
    )

@app.get("/dashboard")
def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={},
    )

@app.get("/metrics", response_model=list[MetricResponse])
def list_metrics(
    response: Response,
    service_name: str | None = Query(default=None, min_length=1),
    request_id: str | None = Query(default=None, min_length=1),
    since_seconds: float | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[MetricResponse]:
    metrics = [
        MetricResponse(**metric)
        for metric in fetch_metrics(
            since_seconds=since_seconds,
            service_name=service_name,
            request_id=request_id,
            limit=limit,
            offset=offset,
        )
    ]
    response.headers["X-Total-Count"] = str(
        count_metrics(
            since_seconds=since_seconds,
            service_name=service_name,
            request_id=request_id,
        )
    )
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    return metrics

@app.get(
    "/metrics/summary",
    response_model=MetricsSummaryResponse,
)
def metrics_summary(
    since_seconds: float | None = Query(default=None, gt=0),
    service_name: str | None = Query(default=None, min_length=1),
) -> MetricsSummaryResponse:
    return MetricsSummaryResponse(
        **fetch_metrics_summary(
            since_seconds=since_seconds,
            service_name=service_name,
        )
    )