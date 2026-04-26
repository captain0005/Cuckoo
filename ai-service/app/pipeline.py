from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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
    ) -> ImageTranslationResult:
        regions = self.recognizer.recognize(input_path)
        translatable = [region for region in regions if is_translatable_ocr_text(region.text)]
        replacements: list[TextReplacement] = []
        entries: list[TranslationEntry] = []

        for region in translatable:
            translated_text = self.translator.translate(region.text, self.source_language, self.target_language)
            if not translated_text.strip():
                continue
            replacements.append(TextReplacement(region=region, translated_text=translated_text))
            entries.append(
                TranslationEntry(
                    source_text=region.text,
                    translated_text=translated_text,
                    confidence=region.confidence,
                    box=region.box,
                )
            )

        warnings: list[str] = []
        if not replacements:
            warnings.append("No Chinese OCR text regions were replaced.")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(input_path.read_bytes())
        else:
            render_replacements(
                source_path=input_path,
                output_path=output_path,
                replacements=replacements,
            )

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


class StaticOcrRecognizer:
    """Small test/helper recognizer for deterministic demos."""

    def __init__(self, regions: list[TextRegion]) -> None:
        self.regions = regions

    def recognize(self, image_path: Path) -> list[TextRegion]:
        return list(self.regions)
