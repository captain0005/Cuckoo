#!/bin/sh
set -eu

export AI_SERVICE_URL="${AI_SERVICE_URL:-http://127.0.0.1:9000}"
export DATA_DIR="${DATA_DIR:-/app/data}"
export GIN_MODE="${GIN_MODE:-release}"
export PYTHONPATH="${PYTHONPATH:-/app/ai-service}"
export LAMA_MODEL_PATH="${LAMA_MODEL_PATH:-$DATA_DIR/models/big-lama/big-lama.pt}"
export LAMA_MODEL_URL="${LAMA_MODEL_URL:-https://huggingface.co/fashn-ai/LaMa/resolve/main/big-lama.pt?download=true}"
export LAMA_MODEL_SHA256="${LAMA_MODEL_SHA256:-7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c}"

mkdir -p "$DATA_DIR"

if [ ! -f "$LAMA_MODEL_PATH" ] && [ -n "${LAMA_MODEL_URL:-}" ]; then
  mkdir -p "$(dirname "$LAMA_MODEL_PATH")"
  python - <<'PY'
import hashlib
import os
import urllib.request

url = os.environ["LAMA_MODEL_URL"]
destination = os.environ["LAMA_MODEL_PATH"]
expected_sha256 = os.environ.get("LAMA_MODEL_SHA256", "").strip().lower()
temp_destination = destination + ".download"
print(f"Downloading LAMA model to {destination}")
try:
    os.remove(temp_destination)
except FileNotFoundError:
    pass
urllib.request.urlretrieve(url, temp_destination)
if expected_sha256:
    digest = hashlib.sha256()
    with open(temp_destination, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        os.remove(temp_destination)
        raise RuntimeError(f"LAMA model SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}")
os.replace(temp_destination, destination)
print("LAMA model download complete")
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
