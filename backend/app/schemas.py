from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    request_id: str | None = Field(default=None, min_length=1)


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


class ExternalProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ExternalProjectResponse(BaseModel):
    id: int
    name: str
    api_key: str
    created_at: str


class ExternalMetricCreate(BaseModel):
    service_name: str = Field(min_length=1, max_length=120)
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
    path: str = Field(min_length=1, max_length=500)
    status_code: int = Field(ge=100, le=599)
    duration_ms: float = Field(ge=0)
    request_id: str | None = Field(default=None, min_length=1)


class ExternalLogCreate(BaseModel):
    service_name: str = Field(min_length=1, max_length=120)
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    message: str = Field(min_length=1, max_length=10000)
    request_id: str | None = Field(default=None, min_length=1)


class ExternalTraceCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=120)
    service_name: str = Field(min_length=1, max_length=120)
    operation: str = Field(min_length=1, max_length=500)
    status_code: int = Field(ge=100, le=599)
    duration_ms: float = Field(ge=0)
    started_at: datetime
    finished_at: datetime
    parent_span_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_span_timestamps(self) -> "ExternalTraceCreate":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be after or equal to started_at")
        return self


class ExternalIngestResponse(BaseModel):
    id: int
    status: Literal["accepted"] = "accepted"


class ExternalMetricsBatchCreate(BaseModel):
    metrics: list[ExternalMetricCreate] = Field(min_length=1, max_length=500)


class ExternalLogsBatchCreate(BaseModel):
    logs: list[ExternalLogCreate] = Field(min_length=1, max_length=500)


class ExternalTracesBatchCreate(BaseModel):
    traces: list[ExternalTraceCreate] = Field(min_length=1, max_length=500)


class ExternalBatchIngestResponse(BaseModel):
    count: int
    status: Literal["accepted"] = "accepted"


class ExternalProjectListItem(BaseModel):
    id: int
    name: str
    created_at: str
    key_prefix: str | None = None
    metric_count: int = 0


class ExternalProjectSummaryResponse(BaseModel):
    project_id: int
    project_name: str | None = None
    total_requests: int
    error_count: int
    error_rate: float
    average_duration_ms: float
    max_duration_ms: float


class RevokeApiKeyRequest(BaseModel):
    api_key: str | None = None


class RevokeApiKeyResponse(BaseModel):
    status: Literal["revoked"] = "revoked"
    message: str = "API key successfully revoked"