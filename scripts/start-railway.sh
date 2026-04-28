#!/bin/sh
set -eu

export AI_SERVICE_URL="${AI_SERVICE_URL:-http://127.0.0.1:9000}"
export DATA_DIR="${DATA_DIR:-/app/data}"
export GIN_MODE="${GIN_MODE:-release}"
export PYTHONPATH="${PYTHONPATH:-/app/ai-service}"

mkdir -p "$DATA_DIR"

uvicorn app.main:app --host 127.0.0.1 --port 9000 --app-dir /app/ai-service &
AI_PID="$!"

cleanup() {
  kill "$AI_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

/app/server
