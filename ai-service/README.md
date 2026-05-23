# Cuckoo AI Service

Python FastAPI service for OCR, translation, image inpainting, and translated text rendering.

## Run

```powershell
cd ai-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-lama.txt
copy .env.example .env
..\scripts\install-lama-model.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 9000
```

## API

- `GET /health`
- `POST /api/translate-image`

The Go backend calls this service internally.

## High-quality LAMA inpainting

Cuckoo looks for the LAMA model at `ai-service/models/big-lama/big-lama.pt` by default, or at `LAMA_MODEL_PATH` when that environment variable is set. The model is not committed because it is large.

To install it locally:

```powershell
..\scripts\install-lama-model.ps1 -Source C:\path\to\big-lama.pt
```

You can also download from a release/artifact URL when one is available:

```powershell
..\scripts\install-lama-model.ps1 -Url https://your-model-host/big-lama.pt
```

If you already have `video-subtitle-remover` on this machine, the script can copy its existing model automatically; Cuckoo does not depend on that project at runtime.
