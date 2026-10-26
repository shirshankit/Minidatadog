"""Locust Load Test Suite for MiniDatadog

Simulates realistic mixed traffic:
1. Standard user application traffic (browsing products, health checks, dashboard).
2. Telemetry ingestion from external microservices (metrics, logs, traces, batch payloads).

Usage:
    locust -f load-tests/locustfile.py --host=http://localhost:8000
Or headless:
    locust -f load-tests/locustfile.py --headless -u 50 -r 10 --run-time 30s --host=http://localhost:8000
"""

import os
from uuid import uuid4
from locust import HttpUser, between, task


class MiniDatadogTrafficUser(HttpUser):
    """Simulates mixed observability traffic hitting MiniDatadog."""

    wait_time = between(0.05, 0.2)  # High-frequency realistic microservice traffic
    api_key: str | None = None

    def on_start(self):
        """Register a test project and obtain an API key for ingestion tasks."""
        env_key = os.getenv("LOAD_TEST_API_KEY")
        if env_key:
            self.api_key = env_key
            return

        resp = self.client.post(
            "/api/v1/projects",
            json={"name": f"load-test-worker-{uuid4().hex[:6]}"},
            name="[Auth] Create Project & API Key",
        )
        if resp.status_code == 200:
            self.api_key = resp.json().get("api_key")

    # --- Read & Health Checks ---

    @task(5)
    def test_health(self):
        self.client.get("/health", name="[Read] /health")

    @task(4)
    def test_products(self):
        self.client.get("/products", name="[Read] /products")

    @task(3)
    def test_metrics_summary(self):
        self.client.get("/metrics/summary", name="[Read] /metrics/summary")

    @task(1)
    def test_dashboard(self):
        self.client.get("/dashboard", name="[UI] /dashboard")

    # --- Telemetry Ingestion ---

    @task(4)
    def ingest_single_metric(self):
        if not self.api_key:
            return
        headers = {"X-API-Key": self.api_key}
        self.client.post(
            "/api/v1/ingest/metrics",
            headers=headers,
            json={
                "service_name": "checkout-svc",
                "method": "POST",
                "path": "/api/v1/cart",
                "status_code": 200,
                "duration_ms": 28.5,
                "request_id": str(uuid4()),
            },
            name="[Ingest] Single Metric",
        )

    @task(3)
    def ingest_batch_metrics(self):
        if not self.api_key:
            return
        headers = {"X-API-Key": self.api_key}
        self.client.post(
            "/api/v1/ingest/metrics/batch",
            headers=headers,
            json={
                "metrics": [
                    {
                        "service_name": "order-svc",
                        "method": "GET",
                        "path": "/api/v1/orders",
                        "status_code": 200,
                        "duration_ms": 14.2,
                        "request_id": str(uuid4()),
                    },
                    {
                        "service_name": "order-svc",
                        "method": "POST",
                        "path": "/api/v1/orders",
                        "status_code": 201,
                        "duration_ms": 65.0,
                        "request_id": str(uuid4()),
                    },
                ]
            },
            name="[Ingest] Batch Metrics",
        )

    @task(3)
    def ingest_log(self):
        if not self.api_key:
            return
        headers = {"X-API-Key": self.api_key}
        self.client.post(
            "/api/v1/ingest/logs",
            headers=headers,
            json={
                "service_name": "checkout-svc",
                "level": "INFO",
                "message": "Transaction verified and routed to payment provider",
                "request_id": str(uuid4()),
            },
            name="[Ingest] Single Log",
        )

    @task(2)
    def ingest_trace(self):
        if not self.api_key:
            return
        headers = {"X-API-Key": self.api_key}
        req_id = str(uuid4())
        self.client.post(
            "/api/v1/ingest/traces",
            headers=headers,
            json={
                "service_name": "checkout-svc",
                "operation": "POST /api/v1/cart",
                "status_code": 200,
                "duration_ms": 28.5,
                "started_at": "2026-10-26T12:00:00Z",
                "finished_at": "2026-10-26T12:00:00.028500Z",
                "request_id": req_id,
            },
            name="[Ingest] Single Trace",
        )

