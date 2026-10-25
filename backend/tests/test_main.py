import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.database import cleanup_old_telemetry, pool
from backend.app.main import app
from backend.app.notifications import (
    clear_notification_state,
    notify_triggered_alerts,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_hsts_is_opt_in_for_local_development(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FORCE_HTTPS", raising=False)

    response = client.get("/health")

    assert "Strict-Transport-Security" not in response.headers


def test_authentication_is_disabled_without_credentials(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MINIDATADOG_USERNAME", raising=False)
    monkeypatch.delenv("MINIDATADOG_PASSWORD", raising=False)

    response = client.get("/health")

    assert response.status_code == 200


def test_application_is_public_when_legacy_authentication_is_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIDATADOG_USERNAME", "admin")
    monkeypatch.setenv("MINIDATADOG_PASSWORD", "test-password")

    health_response = client.get("/health")
    products_response = client.get("/products")
    dashboard_response = client.get("/dashboard")

    assert health_response.status_code == 200
    assert products_response.status_code == 200
    assert dashboard_response.status_code == 200

    monkeypatch.delenv("MINIDATADOG_USERNAME")
    monkeypatch.delenv("MINIDATADOG_PASSWORD")


def test_list_products(client: TestClient) -> None:
    response = client.get("/products")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "name": "Keyboard", "price": 49},
        {"id": 2, "name": "Mouse", "price": 25},
        {"id": 3, "name": "Monitor", "price": 199},
    ]


def test_unique_test_endpoint_creates_distinct_events(
    client: TestClient,
) -> None:
    first_response = client.get(
        "/test/unique",
        params={"label": "friend-location-a"},
    )
    second_response = client.get(
        "/test/unique",
        params={"label": "friend-location-b"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_event = first_response.json()
    second_event = second_response.json()
    assert first_event["event_id"] != second_event["event_id"]
    assert first_event["label"] == "friend-location-a"
    assert second_event["label"] == "friend-location-b"


def test_unique_test_endpoint_validates_label(
    client: TestClient,
) -> None:
    response = client.get("/test/unique?label=")

    assert response.status_code == 422


def test_external_project_can_ingest_isolated_telemetry(
    client: TestClient,
) -> None:
    project_response = client.post(
        "/api/v1/projects",
        json={"name": "friend-shop"},
    )

    assert project_response.status_code == 200
    project = project_response.json()
    api_key = project["api_key"]
    headers = {"X-API-Key": api_key}

    metric_response = client.post(
        "/api/v1/ingest/metrics",
        headers=headers,
        json={
            "service_name": "friend-shop-api",
            "method": "GET",
            "path": "/orders",
            "status_code": 200,
            "duration_ms": 42.5,
            "request_id": "friend-request-1",
        },
    )
    log_response = client.post(
        "/api/v1/ingest/logs",
        headers=headers,
        json={
            "service_name": "friend-shop-api",
            "level": "INFO",
            "message": "Order request completed",
            "request_id": "friend-request-1",
        },
    )
    trace_response = client.post(
        "/api/v1/ingest/traces",
        headers=headers,
        json={
            "request_id": "friend-request-1",
            "service_name": "friend-shop-api",
            "operation": "GET /orders",
            "status_code": 200,
            "duration_ms": 42.5,
            "started_at": "2026-01-01T12:00:00Z",
            "finished_at": "2026-01-01T12:00:00.042500Z",
        },
    )

    assert metric_response.status_code == 200
    assert log_response.status_code == 200
    assert trace_response.status_code == 200
    assert client.get(
        "/api/v1/data/metrics",
        headers=headers,
    ).json()[0]["service_name"] == "friend-shop-api"
    assert client.get("/api/v1/data/logs", headers=headers).json()[0][
        "request_id"
    ] == "friend-request-1"
    assert client.get("/api/v1/data/traces", headers=headers).json()[0][
        "request_id"
    ] == "friend-request-1"


def test_external_ingestion_requires_a_valid_api_key(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/ingest/logs",
        json={
            "service_name": "unknown",
            "level": "INFO",
            "message": "Should be rejected",
        },
    )

    assert response.status_code == 401


def test_request_includes_process_time(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200

    process_time = response.headers.get("X-Process-Time-ms")
    assert process_time is not None
    assert math.isfinite(float(process_time))
    assert float(process_time) >= 0

    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    assert len(request_id) == 36


def test_request_creates_trace_span(client: TestClient) -> None:
    response = client.get("/products")

    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None

    traces_response = client.get(
        "/traces",
        params={"request_id": request_id},
    )

    assert traces_response.status_code == 200
    traces = traces_response.json()
    assert len(traces) == 2
    root_trace = next(
        trace for trace in traces if trace["parent_span_id"] is None
    )
    assert root_trace["request_id"] == request_id
    assert root_trace["operation"] == "GET /products"
    assert root_trace["status_code"] == 200
    assert any(
        trace["parent_span_id"] is None
        for trace in traces
    )
    assert any(
        trace["parent_span_id"] is not None
        for trace in traces
    )


def test_client_errors_are_recorded_as_warning_logs(
    client: TestClient,
) -> None:
    response = client.get("/missing-endpoint")
    request_id = response.headers["X-Request-ID"]

    logs_response = client.get(
        "/logs",
        params={"request_id": request_id},
    )

    assert response.status_code == 404
    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert logs
    assert logs[0]["level"] == "WARNING"


def test_traces_can_filter_by_service(client: TestClient) -> None:
    response = client.get(
        "/traces",
        params={"service_name": "demo-service"},
    )

    assert response.status_code == 200
    assert response.json()

def test_metrics_are_recorded(client: TestClient) -> None:
    health_response = client.get("/health")

    response = client.get(
        "/metrics",
        params={
            "request_id": health_response.headers["X-Request-ID"],
            "limit": 1,
        },
    )

    assert response.status_code == 200

    metrics = response.json()
    assert len(metrics) >= 1

    health_metrics = [
        metric for metric in metrics if metric["path"] == "/health"
    ]

    assert health_metrics
    assert health_metrics[-1]["method"] == "GET"
    assert health_metrics[-1]["service_name"] == "demo-service"
    assert health_metrics[-1]["status_code"] == 200
    assert health_metrics[-1]["duration_ms"] >= 0
    assert any(
        metric["request_id"] == health_response.headers["X-Request-ID"]
        for metric in health_metrics
    )


def test_metrics_support_pagination(client: TestClient) -> None:
    first_response = client.get(
        "/metrics",
        params={"limit": 1, "offset": 0},
    )
    second_response = client.get(
        "/metrics",
        params={"limit": 1, "offset": 1},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(first_response.json()) <= 1
    assert len(second_response.json()) <= 1
    assert int(first_response.headers["X-Total-Count"]) >= 1
    assert first_response.headers["X-Limit"] == "1"
    assert first_response.headers["X-Offset"] == "0"


def test_metrics_reject_invalid_pagination(client: TestClient) -> None:
    assert client.get("/metrics?limit=0").status_code == 422
    assert client.get("/metrics?limit=501").status_code == 422
    assert client.get("/metrics?offset=-1").status_code == 422


def test_telemetry_rejects_non_positive_time_windows(
    client: TestClient,
) -> None:
    assert client.get("/metrics?since_seconds=0").status_code == 422
    assert client.get("/logs?since_seconds=0").status_code == 422
    assert client.get("/traces?since_seconds=0").status_code == 422


def test_telemetry_supports_rolling_time_windows(
    client: TestClient,
) -> None:
    response = client.get("/products")
    request_id = response.headers["X-Request-ID"]

    metrics = client.get(
        "/metrics",
        params={"request_id": request_id, "since_seconds": 60},
    )
    logs = client.get(
        "/logs",
        params={"request_id": request_id, "since_seconds": 60},
    )
    traces = client.get(
        "/traces",
        params={"request_id": request_id, "since_seconds": 60},
    )

    assert metrics.status_code == 200
    assert logs.status_code == 200
    assert traces.status_code == 200
    assert metrics.json()
    assert logs.json()
    assert traces.json()


def test_application_logs_can_store_request_id(
    client: TestClient,
) -> None:
    request_id = "manual-request-correlation"
    response = client.post(
        "/logs",
        json={
            "service_name": "log-test-service",
            "level": "INFO",
            "message": "Correlated application log",
            "request_id": request_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["request_id"] == request_id

def test_metrics_summary(client: TestClient) -> None:
    client.get("/health")
    client.get("/products")

    response = client.get("/metrics/summary")

    assert response.status_code == 200

    summary = response.json()
    assert summary["total_requests"] >= 2
    assert summary["error_count"] >= 0
    assert 0.0 <= summary["error_rate"] <= 1.0
    assert summary["average_duration_ms"] >= 0
    assert summary["max_duration_ms"] >= 0
    
def test_simulate_error(client: TestClient) -> None:
    response = client.get("/simulate-error")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Simulated service failure",
    }

def test_metrics_summary_counts_errors(client: TestClient) -> None:
    client.get("/simulate-error")

    response = client.get("/metrics/summary")

    assert response.status_code == 200

    summary = response.json()
    assert summary["error_count"] >= 1
    assert summary["error_rate"] > 0

def test_metrics_summary_supports_time_window(client: TestClient) -> None:
    client.get("/health")

    response = client.get("/metrics/summary?since_seconds=60")

    assert response.status_code == 200

    summary = response.json()
    assert summary["total_requests"] >= 1


def test_metrics_summary_rejects_non_positive_time_window(
    client: TestClient,
) -> None:
    response = client.get("/metrics/summary?since_seconds=0")

    assert response.status_code == 422
def test_database_health_check(client: TestClient) -> None:
    response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
    }
def test_metrics_can_filter_by_service_name(client: TestClient) -> None:
    client.get("/health")

    response = client.get(
        "/metrics",
        params={"service_name": "demo-service"},
    )

    assert response.status_code == 200

    metrics = response.json()
    assert metrics
    assert all(
        metric["service_name"] == "demo-service"
        for metric in metrics
    )


def test_metrics_filter_returns_empty_for_unknown_service(
    client: TestClient,
) -> None:
    response = client.get(
        "/metrics",
        params={"service_name": "unknown-service"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_summary_can_filter_by_service_name(client: TestClient) -> None:
    client.get("/health")

    response = client.get(
        "/metrics/summary",
        params={"service_name": "demo-service"},
    )

    assert response.status_code == 200

    summary = response.json()
    assert summary["total_requests"] >= 1
    assert 0.0 <= summary["error_rate"] <= 1.0


def test_summary_filter_returns_zero_for_unknown_service(
    client: TestClient,
) -> None:
    response = client.get(
        "/metrics/summary",
        params={"service_name": "unknown-service"},
    )

    assert response.status_code == 200

    summary = response.json()
    assert summary["total_requests"] == 0
    assert summary["error_count"] == 0
    assert summary["error_rate"] == 0.0

def test_dashboard_page_loads(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "MiniDatadog Dashboard" in response.text
    assert "Total Requests" in response.text
    assert 'id="metrics-previous"' in response.text
    assert 'id="logs-next"' in response.text
    assert 'id="traces-page"' in response.text
    assert 'id="alert-rule-form"' in response.text
    assert 'id="alert-rules-container"' in response.text
    assert 'id="alert-history-container"' in response.text
    assert 'id="trace-search-form"' in response.text
    assert 'id="trace-details-container"' in response.text
    assert "trace-span-bar" in response.text
    assert "external-project-section" in response.text
    assert "external-project-form" in response.text
    assert "status-warning" in response.text
    assert 'href = "#trace-details-container"' in response.text


def test_trace_details_can_be_found_by_request_id(
    client: TestClient,
) -> None:
    response = client.get("/products")
    request_id = response.headers["X-Request-ID"]

    trace_response = client.get(
        "/traces",
        params={"request_id": request_id},
    )

    assert trace_response.status_code == 200
    assert trace_response.json()[0]["request_id"] == request_id


def test_trace_can_be_loaded_from_dedicated_endpoint(
    client: TestClient,
) -> None:
    response = client.get("/products")
    request_id = response.headers["X-Request-ID"]

    trace_response = client.get(f"/traces/{request_id}")

    assert trace_response.status_code == 200
    traces = trace_response.json()
    assert len(traces) == 2
    assert all(trace["request_id"] == request_id for trace in traces)


def test_trace_summary_can_be_loaded_by_request_id(
    client: TestClient,
) -> None:
    response = client.get("/products")
    request_id = response.headers["X-Request-ID"]

    summary_response = client.get(
        f"/traces/{request_id}/summary"
    )

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["request_id"] == request_id
    assert summary["span_count"] == 2
    assert summary["operation"] == "GET /products"


def test_trace_summary_returns_not_found_for_unknown_request(
    client: TestClient,
) -> None:
    response = client.get(
        "/traces/00000000-0000-0000-0000-000000000000/summary"
    )

    assert response.status_code == 404

def test_create_alert_rule(client: TestClient) -> None:
    response = client.post(
        "/alerts/rules",
        json={
            "service_name": "test-alert-service",
            "metric": "error_rate",
            "operator": ">",
            "threshold": 0.25,
        },
    )

    assert response.status_code == 200

    alert_rule = response.json()
    assert alert_rule["service_name"] == "test-alert-service"
    assert alert_rule["metric"] == "error_rate"
    assert alert_rule["operator"] == ">"
    assert alert_rule["threshold"] == 0.25
    assert alert_rule["enabled"] is True


def test_list_alert_rules(client: TestClient) -> None:
    client.post(
        "/alerts/rules",
        json={
            "service_name": "list-test-service",
            "metric": "average_duration_ms",
            "operator": ">",
            "threshold": 100.0,
        },
    )

    response = client.get("/alerts/rules")

    assert response.status_code == 200

    alert_rules = response.json()
    assert isinstance(alert_rules, list)
    assert any(
        rule["service_name"] == "list-test-service"
        for rule in alert_rules
    )


def test_disable_alert_rule(client: TestClient) -> None:
    response = client.post(
        "/alerts/rules",
        json={
            "service_name": "disable-test-service",
            "metric": "error_count",
            "operator": ">",
            "threshold": 0,
        },
    )
    rule_id = response.json()["id"]

    disable_response = client.delete(f"/alerts/rules/{rule_id}")

    assert disable_response.status_code == 204
    assert not any(
        rule["id"] == rule_id
        for rule in client.get("/alerts/rules").json()
    )
    assert client.delete(f"/alerts/rules/{rule_id}").status_code == 404


def test_alert_history_is_recorded_and_listed(client: TestClient) -> None:
    client.get("/health")
    client.post(
        "/alerts/rules",
        json={
            "service_name": "demo-service",
            "metric": "error_count",
            "operator": ">",
            "threshold": 0,
        },
    )
    client.get("/alerts/triggered")

    response = client.get("/alerts/history", params={"limit": 10})

    assert response.status_code == 200
    assert any(
        entry["service_name"] == "demo-service"
        and entry["metric"] == "error_count"
        and entry["status"] == "TRIGGERED"
        for entry in response.json()
    )


def test_triggered_alert_evaluation_does_not_duplicate_open_history(
    client: TestClient,
) -> None:
    client.get("/health")
    client.post(
        "/alerts/rules",
        json={
            "service_name": "demo-service",
            "metric": "error_count",
            "operator": ">",
            "threshold": 0,
        },
    )

    first = client.get("/alerts/triggered")
    second = client.get("/alerts/triggered")

    assert first.status_code == 200
    assert second.status_code == 200
    history = client.get("/alerts/history", params={"limit": 200}).json()
    matching = [
        entry
        for entry in history
        if entry["service_name"] == "demo-service"
        and entry["metric"] == "error_count"
        and entry["status"] == "TRIGGERED"
    ]
    assert matching


def test_triggered_alerts_include_matching_rule(
    client: TestClient,
) -> None:
    client.get("/health")

    client.post(
        "/alerts/rules",
        json={
            "service_name": "demo-service",
            "metric": "error_rate",
            "operator": ">",
            "threshold": 0.0,
        },
    )

    response = client.get("/alerts/triggered")

    assert response.status_code == 200

    triggered_alerts = response.json()
    assert any(
        alert["service_name"] == "demo-service"
        and alert["metric"] == "error_rate"
        and alert["triggered"] is True
        for alert in triggered_alerts
    )


def test_alert_webhook_notification_respects_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://example.test/hook")
    monkeypatch.setenv("ALERT_COOLDOWN_SECONDS", "900")
    monkeypatch.setattr(
        "backend.app.notifications.urlopen",
        fake_urlopen,
    )
    clear_notification_state()

    alert = {
        "id": 987654,
        "service_name": "demo-service",
        "metric": "error_count",
        "operator": ">",
        "threshold": 0.0,
        "current_value": 1.0,
        "triggered": True,
    }

    assert notify_triggered_alerts([alert]) == 1
    assert notify_triggered_alerts([alert]) == 0
    assert len(requests) == 1
    request_body = requests[0][0].data.decode("utf-8")
    assert '"content": "MiniDatadog alert:' in request_body
    assert '"text":' not in request_body
    clear_notification_state()
def test_create_alert_rule_rejects_invalid_metric(
    client: TestClient,
) -> None:
    response = client.post(
        "/alerts/rules",
        json={
            "service_name": "demo-service",
            "metric": "invalid_metric",
            "operator": ">",
            "threshold": 0.1,
        },
    )

    assert response.status_code == 422


def test_create_alert_rule_rejects_invalid_operator(
    client: TestClient,
) -> None:
    response = client.post(
        "/alerts/rules",
        json={
            "service_name": "demo-service",
            "metric": "error_rate",
            "operator": "between",
            "threshold": 0.1,
        },
    )

    assert response.status_code == 422


def test_create_alert_rule_rejects_negative_threshold(
    client: TestClient,
) -> None:
    response = client.post(
        "/alerts/rules",
        json={
            "service_name": "demo-service",
            "metric": "error_rate",
            "operator": ">",
            "threshold": -1,
        },
    )

    assert response.status_code == 422

def test_create_application_log(client: TestClient) -> None:
    response = client.post(
        "/logs",
        json={
            "service_name": "log-test-service",
            "level": "ERROR",
            "message": "Test application error",
        },
    )

    assert response.status_code == 200

    log = response.json()
    assert log["service_name"] == "log-test-service"
    assert log["level"] == "ERROR"
    assert log["message"] == "Test application error"
    assert isinstance(log["id"], int)
    assert "recorded_at" in log


def test_list_application_logs(client: TestClient) -> None:
    client.post(
        "/logs",
        json={
            "service_name": "list-log-service",
            "level": "INFO",
            "message": "Informational test log",
        },
    )

    response = client.get("/logs")

    assert response.status_code == 200

    logs = response.json()
    assert isinstance(logs, list)
    assert any(
        log["service_name"] == "list-log-service"
        for log in logs
    )


def test_filter_application_logs_by_level(
    client: TestClient,
) -> None:
    client.post(
        "/logs",
        json={
            "service_name": "level-log-service",
            "level": "WARNING",
            "message": "Warning test log",
        },
    )

    response = client.get(
        "/logs",
        params={"level": "WARNING"},
    )

    assert response.status_code == 200

    logs = response.json()
    assert logs
    assert all(log["level"] == "WARNING" for log in logs)


def test_application_logs_can_filter_by_request_id(
    client: TestClient,
) -> None:
    response = client.get("/products")
    request_id = response.headers["X-Request-ID"]

    logs_response = client.get(
        "/logs",
        params={"request_id": request_id},
    )

    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert logs
    assert all(log["request_id"] == request_id for log in logs)


def test_logs_support_pagination(client: TestClient) -> None:
    response = client.get(
        "/logs",
        params={"limit": 1, "offset": 0},
    )

    assert response.status_code == 200
    assert len(response.json()) <= 1


def test_traces_support_pagination(client: TestClient) -> None:
    response = client.get(
        "/traces",
        params={
            "service_name": "demo-service",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert len(response.json()) <= 1


def test_logs_and_traces_reject_invalid_pagination(
    client: TestClient,
) -> None:
    assert client.get("/logs?limit=0").status_code == 422
    assert client.get("/traces?offset=-1").status_code == 422


def test_cleanup_rejects_invalid_retention_period() -> None:
    with pytest.raises(ValueError, match="retention_days"):
        cleanup_old_telemetry(retention_days=0)


def test_cleanup_removes_old_telemetry(client: TestClient) -> None:
    old_timestamp = datetime.now(timezone.utc) - timedelta(days=31)

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO request_metrics (
                    service_name, method, path, status_code,
                    duration_ms, recorded_at
                )
                VALUES ('retention-test-service', 'GET', '/old', 200, 1, %s)
                """,
                (old_timestamp,),
            )
            cursor.execute(
                """
                INSERT INTO application_logs (
                    service_name, level, message, recorded_at
                )
                VALUES ('retention-test-service', 'INFO', 'old log', %s)
                """,
                (old_timestamp,),
            )
            cursor.execute(
                """
                INSERT INTO trace_spans (
                    request_id, service_name, operation, status_code,
                    duration_ms, started_at, finished_at
                )
                VALUES (
                    'retention-test-request', 'retention-test-service',
                    'GET /old', 200, 1, %s, %s
                )
                """,
                (old_timestamp, old_timestamp + timedelta(seconds=1)),
            )
        connection.commit()

    deleted = cleanup_old_telemetry(retention_days=30)

    assert deleted["metrics"] >= 1
    assert deleted["logs"] >= 1
    assert deleted["traces"] >= 1


def test_create_application_log_rejects_invalid_level(
    client: TestClient,
) -> None:
    response = client.post(
        "/logs",
        json={
            "service_name": "demo-service",
            "level": "DEBUG",
            "message": "Invalid level test",
        },
    )

    assert response.status_code == 422

def test_requests_create_application_logs(
    client: TestClient,
) -> None:
    response = client.get("/products")

    assert response.status_code == 200

    logs_response = client.get(
        "/logs",
        params={"service_name": "demo-service"},
    )

    assert logs_response.status_code == 200

    logs = logs_response.json()
    assert any(
        log["level"] == "INFO"
        and log["message"] == "GET /products returned 200"
        for log in logs
    )