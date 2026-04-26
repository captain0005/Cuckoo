from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.config import settings
from app.pipeline import ImageTranslationPipeline

app = FastAPI(title=f"{settings.app_name} AI Service", version="0.2.0")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ai-service",
        "ocr_engine": settings.ocr_engine,
        "translator_provider": settings.translator_provider,
    }


@app.post("/api/translate-image")
async def translate_image(
    file: UploadFile = File(...),
    source_language: str = Form(default=settings.source_language),
    target_language: str = Form(default=settings.target_language),
):
    suffix = Path(file.filename or "image.png").suffix or ".png"
    temp_input = tempfile.NamedTemporaryFile(prefix="cuckoo-input-", suffix=suffix, delete=False)
    temp_output = tempfile.NamedTemporaryFile(prefix="cuckoo-output-", suffix=".png", delete=False)
    input_path = Path(temp_input.name)
    output_path = Path(temp_output.name)
    temp_input.close()
    temp_output.close()

    try:
        with input_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        await file.close()

        pipeline = ImageTranslationPipeline(
            source_language=source_language,
            target_language=target_language,
        )
        result = pipeline.process_image(
            input_path=input_path,
            output_path=output_path,
            source_filename=file.filename or input_path.name,
        )

        encoded_image = base64.b64encode(output_path.read_bytes()).decode("ascii")
        payload = result.to_dict()
        payload["output_image_base64"] = encoded_image
        payload["mime_type"] = "image/png"
        return payload
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        for path in (input_path, output_path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
