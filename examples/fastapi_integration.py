"""Sample External FastAPI Application Instrumented with MiniDatadog.

Run this application to see real-time metrics, logs, and traces flowing
into MiniDatadog:

    python examples/fastapi_integration.py
"""

import os
from time import perf_counter
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
import uvicorn

# In actual projects, install or import minidatadog_client
from minidatadog_client import MiniDatadogClient

# Configure your MiniDatadog instance and project API key
MINIDATADOG_URL = os.getenv("MINIDATADOG_URL", "http://localhost:8000")
MINIDATADOG_API_KEY = os.getenv("MINIDATADOG_API_KEY", "mdg_replace_with_your_api_key")

client = MiniDatadogClient(
    api_key=MINIDATADOG_API_KEY,
    base_url=MINIDATADOG_URL,
    service_name="payment-service",
)

app = FastAPI(title="Payment Service Demo")


@app.middleware("http")
async def minidatadog_telemetry_middleware(request: Request, call_next):
    """Automatically captures latency, status code, logs, and trace spans."""
    request_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    start_time = perf_counter()

    try:
        response: Response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        # Send error log
        try:
            client.send_log(
                message=f"Unhandled exception during {request.method} {request.url.path}: {exc}",
                level="ERROR",
                request_id=request_id,
            )
        except Exception:
            pass
        raise exc from None

    duration_ms = (perf_counter() - start_time) * 1000
    finished_at = datetime.now(timezone.utc)

    # Attach tracing headers to response
    response.headers["X-Request-ID"] = request_id

    # Asynchronously or synchronously emit telemetry to MiniDatadog
    try:
        # 1. Send HTTP request metric
        client.send_metric(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )

        # 2. Send structured log
        level = "ERROR" if status_code >= 500 else ("WARNING" if status_code >= 400 else "INFO")
        client.send_log(
            message=f"{request.method} {request.url.path} finished with status {status_code} in {duration_ms:.2f}ms",
            level=level,
            request_id=request_id,
        )

        # 3. Send root trace span
        client.send_trace(
            operation=f"{request.method} {request.url.path}",
            status_code=status_code,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            request_id=request_id,
        )
    except Exception as err:
        # MiniDatadog client failures should never crash your primary application
        print(f"[MiniDatadog Telemetry Warning] Failed to send telemetry: {err}")

    return response


@app.get("/checkout")
def checkout():
    return {"status": "success", "order_id": "ord_987654"}


@app.get("/simulate-slow")
def simulate_slow():
    import time
    time.sleep(0.2)
    return {"status": "delayed", "latency": "200ms"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
