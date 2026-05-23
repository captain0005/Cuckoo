FROM golang:1.25-bookworm AS backend-builder

WORKDIR /src/backend

COPY backend/go.mod backend/go.sum ./
RUN go mod download

COPY backend/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      libgomp1 \
      libglib2.0-0 \
      libgl1 \
      libsm6 \
      libxext6 \
      libxrender1 \
      fontconfig \
      fonts-dejavu-core \
      tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=backend-builder /out/server /app/server
COPY ai-service/requirements.txt /tmp/ai-requirements.txt
COPY ai-service/requirements-lama.txt /tmp/ai-requirements-lama.txt
RUN pip install --no-cache-dir -r /tmp/ai-requirements.txt -r /tmp/ai-requirements-lama.txt
COPY ai-service /app/ai-service
COPY scripts/start-railway.sh /app/start-railway.sh

ENV GIN_MODE=release
ENV DATA_DIR=/app/data
ENV BACKEND_PORT=8080
ENV SERVER_ADDR=0.0.0.0:8080
ENV DATABASE_FALLBACK_SQLITE=true
ENV AI_SERVICE_URL=http://127.0.0.1:9000
ENV PYTHONPATH=/app/ai-service
ENV TRANSLATOR_PROVIDER=openai
ENV TRANSLATE_ENDPOINT=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
ENV TRANSLATE_MODEL=qwen-mt-plus

RUN mkdir -p /app/data && chmod +x /app/start-railway.sh

EXPOSE 8080

CMD ["/app/start-railway.sh"]
