# Cuckoo AI Service

Python FastAPI service for OCR, translation, image inpainting, and translated text rendering.

## Run

```powershell
cd ai-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 9000
```

## API

- `GET /health`
- `POST /api/translate-image`

The Go backend calls this service internally.
