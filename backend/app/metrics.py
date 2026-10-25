from dataclasses import dataclass
from time import time


@dataclass(frozen=True)
class RequestMetric:
    method: str
    path: str
    status_code: int
    duration_ms: float
    timestamp: float


_metrics: list[RequestMetric] = []


def record_metric(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> None:
    _metrics.append(
        RequestMetric(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            timestamp=time(),
        )
    )


def get_metrics() -> list[RequestMetric]:
    return list(_metrics)

def get_metrics_summary(
    since_seconds: float | None = None,
) -> dict[str, float | int]:
    metrics = get_metrics()

    if since_seconds is not None:
        cutoff = time() - since_seconds
        metrics = [
            metric for metric in metrics if metric.timestamp >= cutoff
        ]
    if not metrics:
        return {
            "total_requests": 0,
            "error_count": 0,
            "error_rate": 0.0,
            "average_duration_ms": 0.0,
            "max_duration_ms": 0.0,
        }

    error_count = sum(
        1 for metric in metrics if metric.status_code >= 500
    )
    total_requests = len(metrics)
    durations = [metric.duration_ms for metric in metrics]

    return {
        "total_requests": total_requests,
        "error_count": error_count,
        "error_rate": error_count / total_requests,
        "average_duration_ms": sum(durations) / total_requests,
        "max_duration_ms": max(durations),
    }