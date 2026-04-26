# Cuckoo Backend

Go + Gin backend for upload tasks, database persistence, AI service orchestration, and result downloads.

## Run

```powershell
cd backend
copy .env.example .env
go mod tidy
go run ./cmd/server
```

The backend expects the Python AI service at `AI_SERVICE_URL`, defaulting to `http://127.0.0.1:9000`.
