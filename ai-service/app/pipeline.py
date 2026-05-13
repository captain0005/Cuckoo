from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.image_renderer import TextReplacement, render_replacements
from app.ocr import OcrRecognizer, TextRegion, build_ocr_recognizer
from app.text_utils import is_translatable_ocr_text
from app.translation import Translator, build_translator


@dataclass(slots=True)
class TranslationEntry:
    source_text: str
    translated_text: str
    confidence: float
    box: tuple[int, int, int, int]

    def to_dict(self) -> dict[str, object]:
        x, y, width, height = self.box
        return {
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "confidence": self.confidence,
            "box": {"x": x, "y": y, "width": width, "height": height},
        }


@dataclass(slots=True)
class ManualRegion:
    x: float
    y: float
    width: float
    height: float

    def to_pixel_box(self, image_size: tuple[int, int]) -> tuple[int, int, int, int]:
        image_width, image_height = image_size
        x1 = int(round(max(0.0, min(1.0, self.x)) * image_width))
        y1 = int(round(max(0.0, min(1.0, self.y)) * image_height))
        x2 = int(round(max(0.0, min(1.0, self.x + self.width)) * image_width))
        y2 = int(round(max(0.0, min(1.0, self.y + self.height)) * image_height))
        x1, x2 = sorted((max(0, min(image_width, x1)), max(0, min(image_width, x2))))
        y1, y2 = sorted((max(0, min(image_height, y1)), max(0, min(image_height, y2))))
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


@dataclass(slots=True)
class ImageTranslationResult:
    source_filename: str
    output_filename: str
    input_path: Path
    output_path: Path
    regions_detected: int
    regions_replaced: int
    entries: list[TranslationEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, file_url: str | None = None) -> dict[str, object]:
        return {
            "source_filename": self.source_filename,
            "output_filename": self.output_filename,
            "file_url": file_url,
            "regions_detected": self.regions_detected,
            "regions_replaced": self.regions_replaced,
            "entries": [entry.to_dict() for entry in self.entries],
            "warnings": self.warnings,
        }


class ImageTranslationPipeline:
    def __init__(
        self,
        *,
        recognizer: OcrRecognizer | None = None,
        translator: Translator | None = None,
        source_language: str = "zh",
        target_language: str = "en",
    ) -> None:
        self.recognizer = recognizer or build_ocr_recognizer()
        self.translator = translator or build_translator()
        self.source_language = source_language
        self.target_language = target_language

    def process_image(
        self,
        *,
        input_path: Path,
        output_path: Path,
        source_filename: str,
        manual_regions: list[ManualRegion] | None = None,
        inpaint_engine: str | None = None,
    ) -> ImageTranslationResult:
        regions = self.recognizer.recognize(input_path)
        warnings: list[str] = []
        replacements = self._build_replacements(input_path, regions, manual_regions or [])

        if not replacements:
            if manual_regions:
                warnings.append("No Chinese OCR text regions were found inside the selected translation area.")
            else:
                warnings.append("No Chinese OCR text regions were replaced.")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(input_path.read_bytes())
        else:
            candidate_count = len(replacements)
            replacements = render_replacements(
                source_path=input_path,
                output_path=output_path,
                replacements=replacements,
                inpaint_engine=inpaint_engine,
                warnings=warnings,
            )
            skipped_count = candidate_count - len(replacements)
            if skipped_count:
                warnings.append(f"Skipped {skipped_count} small OCR text region(s) or protected design element(s).")
            if not replacements:
                warnings.append("Chinese OCR text was found, but no translated regions were large enough to replace.")

        entries = [
            TranslationEntry(
                source_text=item.region.text,
                translated_text=item.translated_text,
                confidence=item.region.confidence,
                box=item.region.box,
            )
            for item in replacements
        ]

        return ImageTranslationResult(
            source_filename=source_filename,
            output_filename=output_path.name,
            input_path=input_path,
            output_path=output_path,
            regions_detected=len(regions),
            regions_replaced=len(replacements),
            entries=entries,
            warnings=warnings,
        )

    def _build_replacements(
        self,
        input_path: Path,
        regions: list[TextRegion],
        manual_regions: list[ManualRegion],
    ) -> list[TextReplacement]:
        translatable = [region for region in regions if is_translatable_ocr_text(region.text)]
        if manual_regions:
            with Image.open(input_path) as image:
                image_size = image.size
            return self._build_manual_replacements(translatable, manual_regions, image_size)

        replacements: list[TextReplacement] = []
        for region in translatable:
            translated_text = self.translator.translate(region.text, self.source_language, self.target_language)
            if translated_text.strip():
                replacements.append(TextReplacement(region=region, translated_text=translated_text))
        return replacements

    def _build_manual_replacements(
        self,
        regions: list[TextRegion],
        manual_regions: list[ManualRegion],
        image_size: tuple[int, int],
    ) -> list[TextReplacement]:
        replacements: list[TextReplacement] = []
        consumed: set[int] = set()

        for manual_region in manual_regions:
            manual_box = manual_region.to_pixel_box(image_size)
            grouped = [
                (index, region)
                for index, region in enumerate(regions)
                if index not in consumed and _region_intersects_box(region, manual_box)
            ]
            if not grouped:
                continue

            for index, _ in grouped:
                consumed.add(index)
            selected_regions = [region for _, region in grouped]
            if _should_split_manual_group(selected_regions, manual_box):
                for region in _reading_order(selected_regions):
                    translated_text = self.translator.translate(region.text, self.source_language, self.target_language)
                    if translated_text.strip():
                        replacements.append(TextReplacement(region=region, translated_text=translated_text, force=True))
                continue

            source_text = " ".join(region.text.strip() for region in _reading_order(selected_regions) if region.text.strip())
            if not source_text:
                continue

            translated_text = self.translator.translate(source_text, self.source_language, self.target_language)
            if not translated_text.strip():
                continue

            x, y, width, height = manual_box
            combined_region = TextRegion(
                text=source_text,
                confidence=min(region.confidence for region in selected_regions),
                x=x,
                y=y,
                width=width,
                height=height,
                polygon=[(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
            )
            replacements.append(TextReplacement(region=combined_region, translated_text=translated_text, force=True))

        return replacements


def _should_split_manual_group(regions: list[TextRegion], manual_box: tuple[int, int, int, int]) -> bool:
    if len(regions) < 3:
        return False

    _, _, box_width, box_height = manual_box
    if len(regions) >= 6 or box_height > box_width * 1.25:
        return True

    ordered = _reading_order(regions)
    heights = sorted(max(1, region.height) for region in ordered)
    median_height = heights[len(heights) // 2]
    centers = sorted(region.y + region.height / 2 for region in ordered)
    gaps = [bottom - top for top, bottom in zip(centers, centers[1:])]
    row_like_gaps = [gap for gap in gaps if gap > median_height * 0.65]
    return len(ordered) >= 4 and len(row_like_gaps) >= len(ordered) - 2


def _reading_order(regions: list[TextRegion]) -> list[TextRegion]:
    return sorted(regions, key=lambda region: (region.y + region.height // 2, region.x))


def _region_intersects_box(region: TextRegion, box: tuple[int, int, int, int]) -> bool:
    left, top, width, height = box
    right = left + width
    bottom = top + height
    region_left = region.x
    region_top = region.y
    region_right = region.x + region.width
    region_bottom = region.y + region.height
    if region_right <= left or region_left >= right or region_bottom <= top or region_top >= bottom:
        return False

    center_x = region.x + region.width / 2
    center_y = region.y + region.height / 2
    if left <= center_x <= right and top <= center_y <= bottom:
        return True

    overlap_width = min(region_right, right) - max(region_left, left)
    overlap_height = min(region_bottom, bottom) - max(region_top, top)
    overlap_area = max(0, overlap_width) * max(0, overlap_height)
    region_area = max(1, region.width * region.height)
    return overlap_area / region_area >= 0.35


class StaticOcrRecognizer:
    """Small test/helper recognizer for deterministic demos."""

    def __init__(self, regions: list[TextRegion]) -> None:
        self.regions = regions

    def recognize(self, image_path: Path) -> list[TextRegion]:
        return list(self.regions)
