#!/bin/sh
set -eu

export AI_SERVICE_URL="${AI_SERVICE_URL:-http://127.0.0.1:9000}"
export DATA_DIR="${DATA_DIR:-/app/data}"
export GIN_MODE="${GIN_MODE:-release}"
export PYTHONPATH="${PYTHONPATH:-/app/ai-service}"
export LAMA_MODEL_PATH="${LAMA_MODEL_PATH:-$DATA_DIR/models/big-lama/big-lama.pt}"

mkdir -p "$DATA_DIR"

if [ ! -f "$LAMA_MODEL_PATH" ] && [ -n "${LAMA_MODEL_URL:-}" ]; then
  mkdir -p "$(dirname "$LAMA_MODEL_PATH")"
  python - <<'PY'
import os
import urllib.request

url = os.environ["LAMA_MODEL_URL"]
destination = os.environ["LAMA_MODEL_PATH"]
print(f"Downloading LAMA model to {destination}")
urllib.request.urlretrieve(url, destination)
PY
fi

start_ai() {
  while true; do
    set +e
    uvicorn app.main:app --host 127.0.0.1 --port 9000 --app-dir /app/ai-service
    code="$?"
    set -e
    echo "AI service exited with status ${code}; restarting in 2s" >&2
    sleep 2
  done
}

start_ai &
AI_PID="$!"

cleanup() {
  kill "$AI_PID" 2>/dev/null || true
  wait "$AI_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

/app/server
