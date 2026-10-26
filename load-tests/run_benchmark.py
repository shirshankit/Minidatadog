#!/usr/bin/env python3
"""MiniDatadog Headless Benchmark Runner

A standalone benchmark script that runs concurrent workloads against a MiniDatadog
instance without requiring external tools. Measures Requests Per Second (RPS) and
latency percentiles (P50, P90, P95, P99).

Usage:
    .venv/bin/python load-tests/run_benchmark.py --url http://127.0.0.1:8000 --users 10 --duration 10
"""

import argparse
import concurrent.futures
import math
import random
import sys
import time
from uuid import uuid4
import httpx


def percentile(data: list[float], p: float) -> float:
    """Calculate the p-th percentile of a list of floats."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def worker_loop(
    base_url: str,
    api_key: str,
    end_time: float,
    worker_id: int,
) -> list[tuple[str, int, float]]:
    """Worker task sending randomized requests until end_time."""
    results: list[tuple[str, int, float]] = []
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        while time.monotonic() < end_time:
            task_type = random.choices(
                ["health", "products", "summary", "ingest_metric", "ingest_batch", "ingest_log"],
                weights=[25, 20, 15, 20, 10, 10],
                k=1,
            )[0]

            start_t = time.perf_counter()
            status_code = 0

            try:
                if task_type == "health":
                    resp = client.get("/health")
                    status_code = resp.status_code
                elif task_type == "products":
                    resp = client.get("/products")
                    status_code = resp.status_code
                elif task_type == "summary":
                    resp = client.get("/metrics/summary")
                    status_code = resp.status_code
                elif task_type == "ingest_metric":
                    resp = client.post(
                        "/api/v1/ingest/metrics",
                        headers=headers,
                        json={
                            "service_name": "benchmark-service",
                            "method": "GET",
                            "path": "/api/v1/items",
                            "status_code": 200,
                            "duration_ms": random.uniform(5.0, 45.0),
                            "request_id": str(uuid4()),
                        },
                    )
                    status_code = resp.status_code
                elif task_type == "ingest_batch":
                    resp = client.post(
                        "/api/v1/ingest/metrics/batch",
                        headers=headers,
                        json={
                            "metrics": [
                                {
                                    "service_name": "benchmark-service",
                                    "method": "POST",
                                    "path": "/api/v1/checkout",
                                    "status_code": 200,
                                    "duration_ms": random.uniform(10.0, 60.0),
                                    "request_id": str(uuid4()),
                                },
                                {
                                    "service_name": "benchmark-service",
                                    "method": "GET",
                                    "path": "/api/v1/status",
                                    "status_code": 200,
                                    "duration_ms": random.uniform(2.0, 15.0),
                                    "request_id": str(uuid4()),
                                },
                            ]
                        },
                    )
                    status_code = resp.status_code
                elif task_type == "ingest_log":
                    resp = client.post(
                        "/api/v1/ingest/logs",
                        headers=headers,
                        json={
                            "service_name": "benchmark-service",
                            "level": "INFO",
                            "message": f"Benchmark worker {worker_id} executed action",
                            "request_id": str(uuid4()),
                        },
                    )
                    status_code = resp.status_code

            except Exception:
                status_code = 0

            duration_ms = (time.perf_counter() - start_t) * 1000.0
            results.append((task_type, status_code, duration_ms))

    return results


def run_benchmark(
    base_url: str,
    concurrency: int = 10,
    duration: float = 10.0,
    api_key: str | None = None,
) -> None:
    print(f"\n=======================================================")
    print(f" MiniDatadog Benchmark: {base_url}")
    print(f" Concurrency: {concurrency} workers | Duration: {duration}s")
    print(f"=======================================================")

    # Create temporary benchmark project if api_key not supplied
    if not api_key:
        print("Registering benchmark project and API key...")
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post(
                    "/api/v1/projects",
                    json={"name": f"bench-{uuid4().hex[:6]}"},
                )
                if resp.status_code != 200:
                    print(f"Failed to create project: {resp.status_code} {resp.text}")
                    sys.exit(1)
                api_key = resp.json()["api_key"]
                print(f"Obtained API Key: {api_key[:12]}...")
        except Exception as exc:
            print(f"Error connecting to target: {exc}")
            sys.exit(1)

    print(f"\nRunning benchmark for {duration} seconds with {concurrency} concurrent workers...")
    bench_start = time.perf_counter()
    end_time = time.monotonic() + duration

    all_results: list[tuple[str, int, float]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(worker_loop, base_url, api_key, end_time, i)
            for i in range(concurrency)
        ]
        for f in concurrent.futures.as_completed(futures):
            all_results.extend(f.result())

    total_time = time.perf_counter() - bench_start
    total_requests = len(all_results)
    if total_requests == 0:
        print("No requests were completed.")
        return

    rps = total_requests / total_time
    success_count = sum(1 for _, code, _ in all_results if 200 <= code < 400)
    error_count = total_requests - success_count
    error_rate = (error_count / total_requests) * 100.0

    all_latencies = [lat for _, _, lat in all_results]
    p50 = percentile(all_latencies, 50)
    p90 = percentile(all_latencies, 90)
    p95 = percentile(all_latencies, 95)
    p99 = percentile(all_latencies, 99)
    avg_lat = sum(all_latencies) / len(all_latencies)

    print("\n-------------------------------------------------------")
    print(" Benchmark Results Summary")
    print("-------------------------------------------------------")
    print(f" Total Requests Completed: {total_requests}")
    print(f" Elapsed Time:             {total_time:.2f} seconds")
    print(f" Throughput:               {rps:.2f} req/sec")
    print(f" Success Rate:             {(success_count / total_requests) * 100:.2f}% ({success_count} passed)")
    print(f" Error Rate:               {error_rate:.2f}% ({error_count} failed)")
    print("-------------------------------------------------------")
    print(" Latency Percentiles (ms)")
    print("-------------------------------------------------------")
    print(f"  Average:                 {avg_lat:.2f} ms")
    print(f"  P50 (Median):            {p50:.2f} ms")
    print(f"  P90:                     {p90:.2f} ms")
    print(f"  P95:                     {p95:.2f} ms")
    print(f"  P99:                     {p99:.2f} ms")
    print(f"  Max Latency:             {max(all_latencies):.2f} ms")

    # Endpoint Breakdown
    print("\n-------------------------------------------------------")
    print(" Endpoint Breakdown")
    print("-------------------------------------------------------")
    print(f"{'Endpoint':<18} | {'Requests':<8} | {'Avg (ms)':<9} | {'P95 (ms)':<9} | {'Errors':<6}")
    print("-" * 59)
    endpoints = set(t for t, _, _ in all_results)
    for ep in sorted(endpoints):
        ep_results = [lat for t, _, lat in all_results if t == ep]
        ep_errors = sum(1 for t, code, _ in all_results if t == ep and (code < 200 or code >= 400))
        ep_avg = sum(ep_results) / len(ep_results)
        ep_p95 = percentile(ep_results, 95)
        print(f"{ep:<18} | {len(ep_results):<8} | {ep_avg:<9.2f} | {ep_p95:<9.2f} | {ep_errors:<6}")
    print("=======================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniDatadog Headless Benchmark Runner")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL of MiniDatadog instance")
    parser.add_argument("--users", type=int, default=10, help="Number of concurrent users")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds")
    parser.add_argument("--api-key", default=None, help="Existing API key (optional)")
    args = parser.parse_args()

    run_benchmark(
        base_url=args.url,
        concurrency=args.users,
        duration=args.duration,
        api_key=args.api_key,
    )
