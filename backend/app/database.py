import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool


load_dotenv()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return database_url


def get_service_name() -> str:
    service_name = os.getenv("SERVICE_NAME")

    if not service_name:
        raise RuntimeError("SERVICE_NAME is not configured")

    return service_name


pool = ConnectionPool(
    conninfo=get_database_url(),
    min_size=1,
    max_size=5,
    open=False,
)


def check_database_connection() -> bool:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

    return result == (1,)


def initialize_database() -> None:
    create_table_sql = """
        CREATE TABLE IF NOT EXISTS request_metrics (
            id BIGSERIAL PRIMARY KEY,
            service_name TEXT NOT NULL DEFAULT 'demo-service',
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            duration_ms DOUBLE PRECISION NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        ALTER TABLE request_metrics
        ADD COLUMN IF NOT EXISTS service_name TEXT;

        UPDATE request_metrics
        SET service_name = 'demo-service'
        WHERE service_name IS NULL;

        ALTER TABLE request_metrics
        ALTER COLUMN service_name SET DEFAULT 'demo-service';

        ALTER TABLE request_metrics
        ALTER COLUMN service_name SET NOT NULL;

        CREATE TABLE IF NOT EXISTS alert_rules (
            id BIGSERIAL PRIMARY KEY,
            service_name TEXT NOT NULL,
            metric TEXT NOT NULL,
            operator TEXT NOT NULL,
            threshold DOUBLE PRECISION NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS alert_history (
            id BIGSERIAL PRIMARY KEY,
            rule_id BIGINT NOT NULL REFERENCES alert_rules(id),
            service_name TEXT NOT NULL,
            metric TEXT NOT NULL,
            operator TEXT NOT NULL,
            threshold DOUBLE PRECISION NOT NULL,
            current_value DOUBLE PRECISION NOT NULL,
            triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status TEXT NOT NULL DEFAULT 'TRIGGERED',
            resolved_at TIMESTAMPTZ
        );
        ALTER TABLE alert_history
        ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'TRIGGERED';
        ALTER TABLE alert_history
        ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

        CREATE TABLE IF NOT EXISTS application_logs (
            id BIGSERIAL PRIMARY KEY,
            service_name TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE request_metrics
        ADD COLUMN IF NOT EXISTS request_id TEXT;

        ALTER TABLE application_logs
        ADD COLUMN IF NOT EXISTS request_id TEXT;

        CREATE TABLE IF NOT EXISTS trace_spans (
            id BIGSERIAL PRIMARY KEY,
            request_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            duration_ms DOUBLE PRECISION NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL
        );
        ALTER TABLE trace_spans
        ADD COLUMN IF NOT EXISTS parent_span_id BIGINT
        REFERENCES trace_spans(id);

        CREATE INDEX IF NOT EXISTS request_metrics_recorded_at_idx
        ON request_metrics (recorded_at);

        CREATE INDEX IF NOT EXISTS request_metrics_service_name_idx
        ON request_metrics (service_name);

        CREATE INDEX IF NOT EXISTS request_metrics_request_id_idx
        ON request_metrics (request_id);

        CREATE INDEX IF NOT EXISTS application_logs_recorded_at_idx
        ON application_logs (recorded_at);

        CREATE INDEX IF NOT EXISTS application_logs_service_name_idx
        ON application_logs (service_name);

        CREATE INDEX IF NOT EXISTS application_logs_request_id_idx
        ON application_logs (request_id);

        CREATE INDEX IF NOT EXISTS alert_history_triggered_at_idx
        ON alert_history (triggered_at);

        CREATE INDEX IF NOT EXISTS trace_spans_started_at_idx
        ON trace_spans (started_at);

        CREATE INDEX IF NOT EXISTS trace_spans_service_name_idx
        ON trace_spans (service_name);

        CREATE INDEX IF NOT EXISTS trace_spans_request_id_idx
        ON trace_spans (request_id);

        CREATE TABLE IF NOT EXISTS external_projects (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS external_api_keys (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES external_projects(id)
                ON DELETE CASCADE,
            key_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS external_metrics (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES external_projects(id)
                ON DELETE CASCADE,
            service_name TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            duration_ms DOUBLE PRECISION NOT NULL,
            request_id TEXT,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS external_logs (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES external_projects(id)
                ON DELETE CASCADE,
            service_name TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            request_id TEXT,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS external_traces (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES external_projects(id)
                ON DELETE CASCADE,
            request_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            duration_ms DOUBLE PRECISION NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            parent_span_id TEXT
        );

        CREATE INDEX IF NOT EXISTS external_metrics_project_idx
        ON external_metrics (project_id, recorded_at);
        CREATE INDEX IF NOT EXISTS external_logs_project_idx
        ON external_logs (project_id, recorded_at);
        CREATE INDEX IF NOT EXISTS external_traces_project_idx
        ON external_traces (project_id, started_at);
    """
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(create_table_sql)
        connection.commit()


def cleanup_old_telemetry(retention_days: int = 5) -> dict[str, int]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    delete_statements = {
        "metrics": "DELETE FROM request_metrics WHERE recorded_at < %s",
        "logs": "DELETE FROM application_logs WHERE recorded_at < %s",
        "traces": "DELETE FROM trace_spans WHERE started_at < %s",
        "alert_history": "DELETE FROM alert_history WHERE triggered_at < %s",
    }
    deleted: dict[str, int] = {}

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            for resource, statement in delete_statements.items():
                cursor.execute(statement, (cutoff,))
                deleted[resource] = cursor.rowcount
        connection.commit()

    return deleted


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_external_project(name: str) -> dict[str, str | int]:
    api_key = f"mdg_{secrets.token_urlsafe(32)}"
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO external_projects (name)
                VALUES (%s)
                RETURNING id, name, created_at
                """,
                (name,),
            )
            project_id, project_name, created_at = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO external_api_keys (project_id, key_hash)
                VALUES (%s, %s)
                """,
                (project_id, _hash_api_key(api_key)),
            )
        connection.commit()
    return {
        "id": project_id,
        "name": project_name,
        "api_key": api_key,
        "created_at": created_at.isoformat(),
    }


def get_external_project_id(api_key: str) -> int | None:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT project_id
                FROM external_api_keys
                WHERE key_hash = %s AND revoked_at IS NULL
                """,
                (_hash_api_key(api_key),),
            )
            row = cursor.fetchone()
    return int(row[0]) if row else None


def revoke_external_api_key(api_key: str) -> bool:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE external_api_keys
                SET revoked_at = NOW()
                WHERE key_hash = %s AND revoked_at IS NULL
                """,
                (_hash_api_key(api_key),),
            )
            updated = cursor.rowcount
        connection.commit()
    return updated == 1


def ingest_external_metric(
    project_id: int,
    service_name: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    request_id: str | None,
) -> int:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO external_metrics (
                    project_id, service_name, method, path, status_code,
                    duration_ms, request_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    project_id, service_name, method, path, status_code,
                    duration_ms, request_id,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    return int(row[0])


def ingest_external_log(
    project_id: int,
    service_name: str,
    level: str,
    message: str,
    request_id: str | None,
) -> int:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO external_logs (
                    project_id, service_name, level, message, request_id
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (project_id, service_name, level, message, request_id),
            )
            row = cursor.fetchone()
        connection.commit()
    return int(row[0])


def ingest_external_trace(
    project_id: int,
    request_id: str,
    service_name: str,
    operation: str,
    status_code: int,
    duration_ms: float,
    started_at: datetime,
    finished_at: datetime,
    parent_span_id: str | None,
) -> int:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO external_traces (
                    project_id, request_id, service_name, operation,
                    status_code, duration_ms, started_at, finished_at,
                    parent_span_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    project_id, request_id, service_name, operation,
                    status_code, duration_ms, started_at, finished_at,
                    parent_span_id,
                ),
            )
            row = cursor.fetchone()
        connection.commit()
    return int(row[0])


def fetch_external_metrics(project_id: int, limit: int = 100) -> list[dict]:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, service_name, method, path, status_code,
                       duration_ms, request_id, recorded_at
                FROM external_metrics
                WHERE project_id = %s
                ORDER BY recorded_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
            rows = cursor.fetchall()
    return [
        {
            "id": row[0], "service_name": row[1], "method": row[2],
            "path": row[3], "status_code": row[4], "duration_ms": float(row[5]),
            "request_id": row[6], "recorded_at": row[7].isoformat(),
        }
        for row in rows
    ]


def fetch_external_logs(project_id: int, limit: int = 100) -> list[dict]:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, service_name, level, message, request_id,
                       recorded_at
                FROM external_logs
                WHERE project_id = %s
                ORDER BY recorded_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
            rows = cursor.fetchall()
    return [
        {
            "id": row[0], "service_name": row[1], "level": row[2],
            "message": row[3], "request_id": row[4],
            "recorded_at": row[5].isoformat(),
        }
        for row in rows
    ]


def fetch_external_traces(project_id: int, limit: int = 100) -> list[dict]:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, request_id, service_name, operation,
                       status_code, duration_ms, started_at, finished_at,
                       parent_span_id
                FROM external_traces
                WHERE project_id = %s
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
            rows = cursor.fetchall()
    return [
        {
            "id": row[0], "request_id": row[1], "service_name": row[2],
            "operation": row[3], "status_code": row[4],
            "duration_ms": float(row[5]), "started_at": row[6].isoformat(),
            "finished_at": row[7].isoformat(), "parent_span_id": row[8],
        }
        for row in rows
    ]


def save_metric(
    service_name: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    request_id: str | None = None,
) -> None:
    insert_metric_sql = """
        INSERT INTO request_metrics (
            service_name,
            method,
            path,
            status_code,
            duration_ms,
            request_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                insert_metric_sql,
                (
                    service_name,
                    method,
                    path,
                    status_code,
                    duration_ms,
                    request_id,
                ),
            )
        connection.commit()


def fetch_metrics(
    since_seconds: float | None = None,
    service_name: str | None = None,
    request_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, str | int | float | None]]:
    query = """
        SELECT service_name, method, path, status_code,
               duration_ms, recorded_at, request_id
        FROM request_metrics
    """

    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("recorded_at >= %s")
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=since_seconds
        )
        parameters.append(cutoff)

    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)

    if request_id is not None:
        conditions.append("request_id = %s")
        parameters.append(request_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY recorded_at ASC LIMIT %s OFFSET %s"
    parameters.extend([limit, offset])

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()

    return [
        {
            "service_name": service_name_value,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "timestamp": recorded_at.timestamp(),
            "request_id": request_id,
        }
        for (
            service_name_value,
            method,
            path,
            status_code,
            duration_ms,
            recorded_at,
            request_id,
        ) in rows
    ]


def count_metrics(
    since_seconds: float | None = None,
    service_name: str | None = None,
    request_id: str | None = None,
) -> int:
    query = "SELECT COUNT(*) FROM request_metrics"
    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("recorded_at >= %s")
        parameters.append(
            datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        )
    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)
    if request_id is not None:
        conditions.append("request_id = %s")
        parameters.append(request_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchone()[0]

def fetch_metrics_summary(
    since_seconds: float | None = None,
    service_name: str | None = None,
) -> dict[str, float | int]:
    query = """
        SELECT
            COUNT(*) AS total_requests,
            COUNT(*) FILTER (WHERE status_code >= 500) AS error_count,
            COALESCE(AVG(duration_ms), 0) AS average_duration_ms,
            COALESCE(MAX(duration_ms), 0) AS max_duration_ms
        FROM request_metrics
    """
    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("recorded_at >= %s")
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=since_seconds
        )
        parameters.append(cutoff)

    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            row = cursor.fetchone()

    total_requests = int(row[0])
    error_count = int(row[1])
    average_duration_ms = float(row[2])
    max_duration_ms = float(row[3])

    return {
        "total_requests": total_requests,
        "error_count": error_count,
        "error_rate": (
            error_count / total_requests
            if total_requests > 0
            else 0.0
        ),
        "average_duration_ms": average_duration_ms,
        "max_duration_ms": max_duration_ms,
    }


def open_database_pool() -> None:
    pool.open(wait=True)


def close_database_pool() -> None:
    pool.close()

def create_alert_rule(
    service_name: str,
    metric: str,
    operator: str,
    threshold: float,
) -> dict[str, str | float | int | bool]:
    query = """
        INSERT INTO alert_rules (
            service_name,
            metric,
            operator,
            threshold
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id, service_name, metric, operator,
                  threshold, enabled, created_at
    """

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (service_name, metric, operator, threshold),
            )
            row = cursor.fetchone()
        connection.commit()

    return {
        "id": row[0],
        "service_name": row[1],
        "metric": row[2],
        "operator": row[3],
        "threshold": float(row[4]),
        "enabled": row[5],
        "created_at": row[6].isoformat(),
    }


def fetch_alert_rules() -> list[dict[str, str | float | int | bool]]:
    query = """
        SELECT id, service_name, metric, operator,
               threshold, enabled, created_at
        FROM alert_rules
        WHERE enabled = TRUE
        ORDER BY created_at ASC
    """

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "service_name": row[1],
            "metric": row[2],
            "operator": row[3],
            "threshold": float(row[4]),
            "enabled": row[5],
            "created_at": row[6].isoformat(),
        }
        for row in rows
    ]


def disable_alert_rule(rule_id: int) -> bool:
    query = """
        UPDATE alert_rules
        SET enabled = FALSE
        WHERE id = %s AND enabled = TRUE
    """
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (rule_id,))
            updated = cursor.rowcount
        connection.commit()
    return updated == 1


def evaluate_alert_rules() -> list[dict[str, str | float | int | bool]]:
    alert_rules = fetch_alert_rules()
    triggered_alerts: list[dict[str, str | float | int | bool]] = []

    for alert_rule in alert_rules:
        service_name = str(alert_rule["service_name"])
        metric_name = str(alert_rule["metric"])
        operator = str(alert_rule["operator"])
        threshold = float(alert_rule["threshold"])

        summary = fetch_metrics_summary(service_name=service_name)

        metric_values: dict[str, float] = {
            "total_requests": float(summary["total_requests"]),
            "error_count": float(summary["error_count"]),
            "error_rate": float(summary["error_rate"]),
            "average_duration_ms": float(
                summary["average_duration_ms"]
            ),
            "max_duration_ms": float(
                summary["max_duration_ms"]
            ),
        }

        if metric_name not in metric_values:
            continue

        current_value = metric_values[metric_name]

        is_triggered = (
            (operator == ">" and current_value > threshold)
            or (operator == ">=" and current_value >= threshold)
            or (operator == "<" and current_value < threshold)
            or (operator == "<=" and current_value <= threshold)
            or (operator == "==" and current_value == threshold)
        )

        if is_triggered:
            alert = {
                "id": int(alert_rule["id"]),
                "service_name": service_name,
                "metric": metric_name,
                "operator": operator,
                "threshold": threshold,
                "current_value": current_value,
                "triggered": True,
            }
            triggered_alerts.append(alert)
            open_history = fetch_open_alert_history(int(alert["id"]))
            if open_history is None:
                record_alert_history(alert)
            else:
                update_alert_history_value(
                    open_history["id"],
                    current_value,
                )
        else:
            open_history = fetch_open_alert_history(int(alert_rule["id"]))
            if open_history is not None:
                resolve_alert_history(open_history["id"], current_value)

    return triggered_alerts


def record_alert_history(
    alert: dict[str, str | float | int | bool],
) -> None:
    query = """
        INSERT INTO alert_history (
            rule_id, service_name, metric, operator,
            threshold, current_value, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'TRIGGERED')
    """
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    int(alert["id"]),
                    str(alert["service_name"]),
                    str(alert["metric"]),
                    str(alert["operator"]),
                    float(alert["threshold"]),
                    float(alert["current_value"]),
                ),
            )
        connection.commit()


def fetch_open_alert_history(
    rule_id: int,
) -> dict[str, int | float] | None:
    query = """
        SELECT id, current_value
        FROM alert_history
        WHERE rule_id = %s AND resolved_at IS NULL
        ORDER BY triggered_at DESC
        LIMIT 1
    """
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (rule_id,))
            row = cursor.fetchone()
    if row is None:
        return None
    return {"id": row[0], "current_value": float(row[1])}


def update_alert_history_value(history_id: int, current_value: float) -> None:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE alert_history
                SET current_value = %s
                WHERE id = %s AND resolved_at IS NULL
                """,
                (current_value, history_id),
            )
        connection.commit()


def resolve_alert_history(history_id: int, current_value: float) -> None:
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE alert_history
                SET current_value = %s,
                    status = 'RESOLVED',
                    resolved_at = NOW()
                WHERE id = %s AND resolved_at IS NULL
                """,
                (current_value, history_id),
            )
        connection.commit()


def fetch_alert_history(
    limit: int = 50,
) -> list[dict[str, str | float | int]]:
    query = """
        SELECT id, rule_id, service_name, metric, operator,
               threshold, current_value, triggered_at, status, resolved_at
        FROM alert_history
        ORDER BY triggered_at DESC
        LIMIT %s
    """
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "rule_id": row[1],
            "service_name": row[2],
            "metric": row[3],
            "operator": row[4],
            "threshold": float(row[5]),
            "current_value": float(row[6]),
            "triggered_at": row[7].isoformat(),
            "status": row[8],
            "resolved_at": row[9].isoformat() if row[9] else None,
        }
        for row in rows
    ]

def create_application_log(
    service_name: str,
    level: str,
    message: str,
    request_id: str | None = None,
) -> dict[str, str | int | None]:
    query = """
        INSERT INTO application_logs (
            service_name,
            level,
            message,
            request_id
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id, service_name, level, message,
                  recorded_at, request_id
    """

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (service_name, level, message, request_id),
            )
            row = cursor.fetchone()
        connection.commit()

    return {
        "id": row[0],
        "service_name": row[1],
        "level": row[2],
        "message": row[3],
        "recorded_at": row[4].isoformat(),
        "request_id": row[5],
    }


def fetch_application_logs(
    service_name: str | None = None,
    level: str | None = None,
    request_id: str | None = None,
    since_seconds: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, str | int | None]]:
    query = """
        SELECT id, service_name, level, message,
               recorded_at, request_id
        FROM application_logs
    """

    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("recorded_at >= %s")
        parameters.append(
            datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        )

    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)

    if level is not None:
        conditions.append("level = %s")
        parameters.append(level)

    if request_id is not None:
        conditions.append("request_id = %s")
        parameters.append(request_id)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY recorded_at DESC LIMIT %s OFFSET %s"
    parameters.extend([limit, offset])

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "service_name": row[1],
            "level": row[2],
            "message": row[3],
            "recorded_at": row[4].isoformat(),
            "request_id": row[5],
        }
        for row in rows
    ]


def count_application_logs(
    service_name: str | None = None,
    level: str | None = None,
    request_id: str | None = None,
    since_seconds: float | None = None,
) -> int:
    query = "SELECT COUNT(*) FROM application_logs"
    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("recorded_at >= %s")
        parameters.append(
            datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        )

    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)
    if level is not None:
        conditions.append("level = %s")
        parameters.append(level)
    if request_id is not None:
        conditions.append("request_id = %s")
        parameters.append(request_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchone()[0]


def create_trace_span(
    request_id: str,
    service_name: str,
    operation: str,
    status_code: int,
    duration_ms: float,
    started_at: datetime,
    finished_at: datetime,
    parent_span_id: int | None = None,
) -> dict[str, str | int | float]:
    query = """
        INSERT INTO trace_spans (
            request_id,
            service_name,
            operation,
            status_code,
            duration_ms,
            started_at,
            finished_at
            , parent_span_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, request_id, service_name, operation,
                  status_code, duration_ms, started_at, finished_at,
                  parent_span_id
    """

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                (
                    request_id,
                    service_name,
                    operation,
                    status_code,
                    duration_ms,
                    started_at,
                    finished_at,
                    parent_span_id,
                ),
            )
            row = cursor.fetchone()
        connection.commit()

    return {
        "id": row[0],
        "request_id": row[1],
        "service_name": row[2],
        "operation": row[3],
        "status_code": row[4],
        "duration_ms": float(row[5]),
        "started_at": row[6].isoformat(),
        "finished_at": row[7].isoformat(),
        "parent_span_id": row[8],
    }


def fetch_trace_spans(
    request_id: str | None = None,
    service_name: str | None = None,
    since_seconds: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, str | int | float]]:
    query = """
        SELECT id, request_id, service_name, operation,
               status_code, duration_ms, started_at, finished_at,
               parent_span_id
        FROM trace_spans
    """
    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("started_at >= %s")
        parameters.append(
            datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        )

    if request_id is not None:
        conditions.append("request_id = %s")
        parameters.append(request_id)

    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY started_at DESC LIMIT %s OFFSET %s"
    parameters.extend([limit, offset])

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "request_id": row[1],
            "service_name": row[2],
            "operation": row[3],
            "status_code": row[4],
            "duration_ms": float(row[5]),
            "started_at": row[6].isoformat(),
            "finished_at": row[7].isoformat(),
            "parent_span_id": row[8],
        }
        for row in rows
    ]


def count_trace_spans(
    request_id: str | None = None,
    service_name: str | None = None,
    since_seconds: float | None = None,
) -> int:
    query = "SELECT COUNT(*) FROM trace_spans"
    conditions: list[str] = []
    parameters: list[object] = []

    if since_seconds is not None:
        conditions.append("started_at >= %s")
        parameters.append(
            datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
        )

    if request_id is not None:
        conditions.append("request_id = %s")
        parameters.append(request_id)
    if service_name is not None:
        conditions.append("service_name = %s")
        parameters.append(service_name)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchone()[0]


def fetch_trace_summary(
    request_id: str,
) -> dict[str, str | int | float] | None:
    query = """
        SELECT request_id,
               COUNT(*) AS span_count,
               MAX(status_code) FILTER (WHERE parent_span_id IS NULL),
               MAX(operation) FILTER (WHERE parent_span_id IS NULL),
               MAX(duration_ms) FILTER (WHERE parent_span_id IS NULL),
               MIN(started_at),
               MAX(finished_at)
        FROM trace_spans
        WHERE request_id = %s
        GROUP BY request_id
    """
    with pool.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (request_id,))
            row = cursor.fetchone()

    if row is None:
        return None
    return {
        "request_id": row[0],
        "span_count": row[1],
        "status_code": row[2],
        "operation": row[3],
        "duration_ms": float(row[4]),
        "started_at": row[5].isoformat(),
        "finished_at": row[6].isoformat(),
    }
