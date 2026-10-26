#!/usr/bin/env bash
# MiniDatadog Multi-Tenant Ingestion Examples
# Usage: ./examples/curl_examples.sh [BASE_URL]

set -e

BASE_URL="${1:-http://localhost:8000}"

echo "=========================================================="
echo "1. Creating an external project"
echo "=========================================================="
PROJECT_RESP=$(curl -s -X POST "${BASE_URL}/api/v1/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "ecommerce-service"}')

echo "Response: ${PROJECT_RESP}"

API_KEY=$(echo "${PROJECT_RESP}" | python3 -c "import sys, json; print(json.load(sys.stdin)['api_key'])")
echo "Extracted API Key: ${API_KEY}"
echo ""

echo "=========================================================="
echo "2. Listing projects"
echo "=========================================================="
curl -s "${BASE_URL}/api/v1/projects" | python3 -m json.tool
echo ""

echo "=========================================================="
echo "3. Ingesting single metric"
echo "=========================================================="
curl -s -X POST "${BASE_URL}/api/v1/ingest/metrics" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "checkout-api",
    "method": "POST",
    "path": "/api/v1/checkout",
    "status_code": 200,
    "duration_ms": 34.2,
    "request_id": "req-001"
  }' | python3 -m json.tool
echo ""

echo "=========================================================="
echo "4. Ingesting batch metrics"
echo "=========================================================="
curl -s -X POST "${BASE_URL}/api/v1/ingest/metrics/batch" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "metrics": [
      {
        "service_name": "checkout-api",
        "method": "GET",
        "path": "/cart",
        "status_code": 200,
        "duration_ms": 12.1,
        "request_id": "req-002"
      },
      {
        "service_name": "checkout-api",
        "method": "POST",
        "path": "/pay",
        "status_code": 500,
        "duration_ms": 145.8,
        "request_id": "req-003"
      }
    ]
  }' | python3 -m json.tool
echo ""

echo "=========================================================="
echo "5. Ingesting single log"
echo "=========================================================="
curl -s -X POST "${BASE_URL}/api/v1/ingest/logs" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "checkout-api",
    "level": "INFO",
    "message": "Cart loaded for customer #42981",
    "request_id": "req-002"
  }' | python3 -m json.tool
echo ""

echo "=========================================================="
echo "6. Ingesting batch logs"
echo "=========================================================="
curl -s -X POST "${BASE_URL}/api/v1/ingest/logs/batch" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "logs": [
      {
        "service_name": "checkout-api",
        "level": "WARNING",
        "message": "Payment gateway took longer than 100ms",
        "request_id": "req-003"
      },
      {
        "service_name": "checkout-api",
        "level": "ERROR",
        "message": "Payment declined by upstream card network",
        "request_id": "req-003"
      }
    ]
  }' | python3 -m json.tool
echo ""

echo "=========================================================="
echo "7. Ingesting trace span"
echo "=========================================================="
curl -s -X POST "${BASE_URL}/api/v1/ingest/traces" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "checkout-api",
    "request_id": "req-003",
    "operation": "POST /pay",
    "status_code": 500,
    "duration_ms": 145.8,
    "started_at": "2026-10-26T03:00:00Z",
    "finished_at": "2026-10-26T03:00:00.145800Z"
  }' | python3 -m json.tool
echo ""

echo "=========================================================="
echo "8. Fetching project metrics summary"
echo "=========================================================="
curl -s "${BASE_URL}/api/v1/data/summary" \
  -H "X-API-Key: ${API_KEY}" | python3 -m json.tool
echo ""

echo "=========================================================="
echo "9. Fetching project logs"
echo "=========================================================="
curl -s "${BASE_URL}/api/v1/data/logs" \
  -H "X-API-Key: ${API_KEY}" | python3 -m json.tool
echo ""

echo "=========================================================="
echo "10. Revoking the API Key"
echo "=========================================================="
curl -s -X POST "${BASE_URL}/api/v1/api-keys/revoke" \
  -H "X-API-Key: ${API_KEY}" | python3 -m json.tool
echo ""

echo "=========================================================="
echo "11. Verifying revoked key is rejected (should be HTTP 401)"
echo "=========================================================="
curl -i -s "${BASE_URL}/api/v1/data/metrics" \
  -H "X-API-Key: ${API_KEY}" | head -n 1
echo ""
echo "Done!"

