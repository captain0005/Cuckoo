from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.config import settings
from app.inpainting import lama_model_available
from app.pipeline import ImageTranslationPipeline, ManualRegion

app = FastAPI(title=f"{settings.app_name} AI Service", version="0.2.0")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ai-service",
        "ocr_engine": settings.ocr_engine,
        "translator_provider": settings.translator_provider,
        "inpaint_engine": settings.inpaint_engine,
        "lama_model_available": lama_model_available(),
    }


@app.post("/api/translate-image")
async def translate_image(
    file: UploadFile = File(...),
    source_language: str = Form(default=settings.source_language),
    target_language: str = Form(default=settings.target_language),
    manual_regions: str = Form(default=""),
    inpaint_engine: str = Form(default=settings.inpaint_engine),
):
    parsed_manual_regions = parse_manual_regions(manual_regions)
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
            manual_regions=parsed_manual_regions,
            inpaint_engine=inpaint_engine,
        )

        encoded_image = base64.b64encode(output_path.read_bytes()).decode("ascii")
        payload = result.to_dict()
        payload["output_image_base64"] = encoded_image
        payload["mime_type"] = "image/png"
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        for path in (input_path, output_path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def parse_manual_regions(raw: str) -> list[ManualRegion]:
    value = raw.strip()
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid manual_regions JSON") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="manual_regions must be a JSON array")

    regions: list[ManualRegion] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
            width = float(item.get("width", 0))
            height = float(item.get("height", 0))
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        regions.append(ManualRegion(x=x, y=y, width=width, height=height))
    return regions
