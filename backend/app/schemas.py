from typing import Literal

from pydantic import BaseModel, Field


class MetricResponse(BaseModel):
    service_name: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    timestamp: float
    request_id: str | None = None


class MetricsSummaryResponse(BaseModel):
    total_requests: int
    error_count: int
    error_rate: float
    average_duration_ms: float
    max_duration_ms: float

class AlertRuleCreate(BaseModel):
    service_name: str = Field(min_length=1)
    metric: Literal[
        "total_requests",
        "error_count",
        "error_rate",
        "average_duration_ms",
        "max_duration_ms",
    ]
    operator: Literal[">", ">=", "<", "<=", "=="]
    threshold: float = Field(ge=0)


class AlertRuleResponse(BaseModel):
    id: int
    service_name: str
    metric: str
    operator: str
    threshold: float
    enabled: bool
    created_at: str

class TriggeredAlertResponse(BaseModel):
    id: int
    service_name: str
    metric: str
    operator: str
    threshold: float
    current_value: float
    triggered: bool


class AlertHistoryResponse(BaseModel):
    id: int
    rule_id: int
    service_name: str
    metric: str
    operator: str
    threshold: float
    current_value: float
    triggered_at: str
    status: Literal["TRIGGERED", "RESOLVED"]
    resolved_at: str | None = None

class ApplicationLogCreate(BaseModel):
    service_name: str = Field(min_length=1)
    level: Literal["INFO", "WARNING", "ERROR"]
    message: str = Field(min_length=1)


class ApplicationLogResponse(BaseModel):
    id: int
    service_name: str
    level: str
    message: str
    recorded_at: str
    request_id: str | None = None


class TraceSpanResponse(BaseModel):
    id: int
    request_id: str
    service_name: str
    operation: str
    status_code: int
    duration_ms: float
    started_at: str
    finished_at: str
    parent_span_id: int | None = None


class TraceSummaryResponse(BaseModel):
    request_id: str
    span_count: int
    status_code: int
    operation: str
    duration_ms: float
    started_at: str
    finished_at: str