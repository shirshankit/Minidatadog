"""MiniDatadog Client SDK

A lightweight Python client for sending metrics, structured logs, and distributed
traces to a MiniDatadog instance using an API key.
"""

from datetime import datetime, timezone
from typing import Any
import requests


class MiniDatadogClient:
    """Client for ingesting telemetry into MiniDatadog."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        service_name: str = "external-app",
        timeout: float = 5.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            }
        )

    # --- Metrics ---

    def send_metric(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        request_id: str | None = None,
        service_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a single HTTP request metric."""
        payload = {
            "service_name": service_name or self.service_name,
            "method": method.upper(),
            "path": path,
            "status_code": int(status_code),
            "duration_ms": float(duration_ms),
            "request_id": request_id,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/ingest/metrics",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def send_metrics_batch(self, metrics: list[dict[str, Any]]) -> dict[str, Any]:
        """Send a batch of request metrics."""
        for m in metrics:
            if "service_name" not in m:
                m["service_name"] = self.service_name
        resp = self.session.post(
            f"{self.base_url}/api/v1/ingest/metrics/batch",
            json={"metrics": metrics},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Logs ---

    def send_log(
        self,
        message: str,
        level: str = "INFO",
        request_id: str | None = None,
        service_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a single structured application log."""
        payload = {
            "service_name": service_name or self.service_name,
            "level": level.upper(),
            "message": message,
            "request_id": request_id,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/ingest/logs",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def send_logs_batch(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        """Send a batch of application logs."""
        for l in logs:
            if "service_name" not in l:
                l["service_name"] = self.service_name
        resp = self.session.post(
            f"{self.base_url}/api/v1/ingest/logs/batch",
            json={"logs": logs},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Traces ---

    def send_trace(
        self,
        operation: str,
        status_code: int,
        duration_ms: float,
        started_at: datetime | str,
        finished_at: datetime | str,
        request_id: str,
        parent_span_id: str | None = None,
        service_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a single trace span."""
        if isinstance(started_at, datetime):
            started_at = started_at.isoformat()
        if isinstance(finished_at, datetime):
            finished_at = finished_at.isoformat()

        payload = {
            "request_id": request_id,
            "service_name": service_name or self.service_name,
            "operation": operation,
            "status_code": int(status_code),
            "duration_ms": float(duration_ms),
            "started_at": started_at,
            "finished_at": finished_at,
            "parent_span_id": parent_span_id,
        }
        resp = self.session.post(
            f"{self.base_url}/api/v1/ingest/traces",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def send_traces_batch(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        """Send a batch of trace spans."""
        for t in traces:
            if "service_name" not in t:
                t["service_name"] = self.service_name
            if isinstance(t.get("started_at"), datetime):
                t["started_at"] = t["started_at"].isoformat()
            if isinstance(t.get("finished_at"), datetime):
                t["finished_at"] = t["finished_at"].isoformat()
        resp = self.session.post(
            f"{self.base_url}/api/v1/ingest/traces/batch",
            json={"traces": traces},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # --- Query Telemetry ---

    def get_metrics(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch recorded metrics for this project."""
        resp = self.session.get(
            f"{self.base_url}/api/v1/data/metrics",
            params={"limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch recorded logs for this project."""
        resp = self.session.get(
            f"{self.base_url}/api/v1/data/logs",
            params={"limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_traces(self, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch recorded trace spans for this project."""
        resp = self.session.get(
            f"{self.base_url}/api/v1/data/traces",
            params={"limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_summary(self, since_seconds: float | None = None) -> dict[str, Any]:
        """Fetch aggregated metrics summary for this project."""
        params = {}
        if since_seconds is not None:
            params["since_seconds"] = since_seconds
        resp = self.session.get(
            f"{self.base_url}/api/v1/data/summary",
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def revoke_key(self) -> dict[str, Any]:
        """Revoke the current API key."""
        resp = self.session.post(
            f"{self.base_url}/api/v1/api-keys/revoke",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
