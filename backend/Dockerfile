FROM golang:1.25-alpine AS builder

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /app/server ./cmd/server

FROM alpine:3.22

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app
COPY --from=builder /app/server /app/server

ENV GIN_MODE=release
ENV DATA_DIR=/app/data
ENV PORT=8080

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["/app/server"]
