from __future__ import annotations

import gc
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from app.config import settings
from app.text_utils import is_translatable_ocr_text, normalize_ocr_text


@dataclass(slots=True)
class TextRegion:
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    polygon: list[tuple[int, int]]

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "box": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
            "polygon": self.polygon,
        }


class OcrRecognizer(Protocol):
    def recognize(self, image_path: Path) -> list[TextRegion]:
        """Recognize text regions in an image."""


class PaddleOcrImageRecognizer:
    _shared_ocr_instances: dict[tuple[str, str, str], object] = {}

    def __init__(
        self,
        *,
        lang: str | None = None,
        min_confidence: float | None = None,
        text_detection_model_name: str | None = None,
        text_recognition_model_name: str | None = None,
    ) -> None:
        self.lang = lang or settings.ocr_lang
        self.min_confidence = settings.ocr_min_confidence if min_confidence is None else min_confidence
        self.text_detection_model_name = text_detection_model_name or settings.paddle_text_detection_model
        self.text_recognition_model_name = text_recognition_model_name or settings.paddle_text_recognition_model

    def recognize(self, image_path: Path) -> list[TextRegion]:
        image = Image.open(image_path).convert("RGB")
        payloads = self._predict_payloads(image)
        return self._regions_from_payloads(payloads, x_offset=0, y_offset=0)

    def recognize_crops(self, image_path: Path, crop_boxes: list[tuple[int, int, int, int]]) -> list[TextRegion]:
        image = Image.open(image_path).convert("RGB")
        image_width, image_height = image.size
        regions: list[TextRegion] = []
        for x, y, width, height in crop_boxes:
            x1 = max(0, min(image_width, x))
            y1 = max(0, min(image_height, y))
            x2 = max(x1, min(image_width, x + width))
            y2 = max(y1, min(image_height, y + height))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image.crop((x1, y1, x2, y2))
            payloads = self._predict_payloads(crop)
            regions.extend(self._regions_from_payloads(payloads, x_offset=x1, y_offset=y1))
        return regions

    def _regions_from_payloads(self, payloads: list[dict[str, Any]], *, x_offset: int, y_offset: int) -> list[TextRegion]:
        regions: list[TextRegion] = []
        for payload in payloads:
            regions.extend(self._regions_from_payload(payload, x_offset=x_offset, y_offset=y_offset))
        return [region for region in regions if region.confidence >= self.min_confidence]

    def _predict_payloads(self, image: Image.Image) -> list[dict[str, Any]]:
        ocr = self._get_ocr()
        result = ocr.predict(np.array(image))
        if not result:
            return []

        payloads: list[dict[str, Any]] = []
        for item in result:
            if isinstance(item, dict):
                payloads.append(item.get("res") or item)
                continue
            json_payload = getattr(item, "json", {}) or {}
            payload = json_payload.get("res") or json_payload
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    def _regions_from_payload(self, payload: dict[str, Any], *, x_offset: int = 0, y_offset: int = 0) -> list[TextRegion]:
        texts = _first_present(payload, "rec_texts", "texts")
        scores = _first_present(payload, "rec_scores", "scores")
        raw_boxes = _first_present(payload, "rec_boxes", "dt_polys", "rec_polys")

        regions: list[TextRegion] = []
        for index, raw_text in enumerate(texts):
            text = normalize_ocr_text(str(raw_text))
            if not is_translatable_ocr_text(text):
                continue
            confidence = self._score_at(scores, index)
            polygon = self._polygon_at(raw_boxes, index)
            if not polygon:
                continue
            x_values = [point[0] for point in polygon]
            y_values = [point[1] for point in polygon]
            x1, x2 = min(x_values), max(x_values)
            y1, y2 = min(y_values), max(y_values)
            shifted_polygon = [(x + x_offset, y + y_offset) for x, y in polygon]
            regions.append(
                TextRegion(
                    text=text,
                    confidence=confidence,
                    x=max(0, int(round(x1)) + x_offset),
                    y=max(0, int(round(y1)) + y_offset),
                    width=max(1, int(round(x2 - x1))),
                    height=max(1, int(round(y2 - y1))),
                    polygon=shifted_polygon,
                )
            )
        return regions

    def _score_at(self, scores: Any, index: int) -> float:
        try:
            return float(scores[index])
        except (IndexError, TypeError, ValueError):
            return 1.0

    def _polygon_at(self, raw_boxes: Any, index: int) -> list[tuple[int, int]]:
        try:
            raw_box = raw_boxes[index]
        except (IndexError, TypeError):
            return []

        if isinstance(raw_box, np.ndarray):
            raw_box = raw_box.tolist()

        if (
            isinstance(raw_box, (list, tuple))
            and len(raw_box) == 4
            and all(isinstance(value, (int, float, np.integer, np.floating)) for value in raw_box)
        ):
            x1, y1, x2, y2 = [int(round(float(value))) for value in raw_box]
            return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]

        points: list[tuple[int, int]] = []
        if isinstance(raw_box, (list, tuple)):
            for point in raw_box:
                if isinstance(point, np.ndarray):
                    point = point.tolist()
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    try:
                        points.append((int(round(float(point[0]))), int(round(float(point[1])))))
                    except (TypeError, ValueError):
                        continue
        return points

    def _get_ocr(self):  # pragma: no cover
        cache_key = (self.lang, self.text_detection_model_name, self.text_recognition_model_name)
        cached = self._shared_ocr_instances.get(cache_key)
        if cached is not None:
            return cached

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR  # type: ignore

        cached = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name=self.text_detection_model_name,
            text_recognition_model_name=self.text_recognition_model_name,
            lang=self.lang,
        )
        self._shared_ocr_instances[cache_key] = cached
        return cached


def build_ocr_recognizer() -> OcrRecognizer:
    engine = settings.ocr_engine.strip().lower()
    if engine != "paddle":
        raise RuntimeError(f"unsupported OCR_ENGINE: {settings.ocr_engine}")
    return PaddleOcrImageRecognizer()


def release_ocr_resources() -> None:
    PaddleOcrImageRecognizer._shared_ocr_instances.clear()
    gc.collect()


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            if len(value) == 0:
                continue
        except TypeError:
            pass
        return value
    return []
