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


def test_health_check_is_public_when_authentication_is_enabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIDATADOG_USERNAME", "admin")
    monkeypatch.setenv("MINIDATADOG_PASSWORD", "test-password")

    health_response = client.get("/health")
    products_response = client.get("/products")

    assert health_response.status_code == 200
    assert products_response.status_code == 401

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
    assert len(traces) == 1
    assert traces[0]["request_id"] == request_id
    assert traces[0]["operation"] == "GET /products"
    assert traces[0]["status_code"] == 200


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
        for entry in response.json()
    )


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