from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.ocr import TextRegion


@dataclass(slots=True)
class TextReplacement:
    region: TextRegion
    translated_text: str


FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]


def render_replacements(
    *,
    source_path: Path,
    output_path: Path,
    replacements: list[TextReplacement],
) -> None:
    image = Image.open(source_path).convert("RGB")
    styles = [(_expanded_box(item.region, image.size), _estimate_text_color(image, item.region)) for item in replacements]
    repaired = _inpaint_regions(image, [item.region for item in replacements])
    draw = ImageDraw.Draw(repaired)

    for item, (box, color) in zip(replacements, styles):
        x, y, width, height = box
        font, lines = _fit_text(item.translated_text, width, height)
        line_height = _line_height(font)
        total_height = line_height * len(lines)
        cursor_y = y + max(0, (height - total_height) // 2)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            cursor_x = x + max(0, (width - text_width) // 2)
            draw.text((cursor_x, cursor_y), line, font=font, fill=color)
            cursor_y += line_height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    repaired.save(output_path, quality=96)


def _inpaint_regions(image: Image.Image, regions: list[TextRegion]) -> Image.Image:
    if not regions:
        return image.copy()

    try:
        import cv2  # type: ignore
    except Exception:
        return _fill_regions_with_background(image, regions)

    arr = np.array(image)
    mask = np.zeros(arr.shape[:2], dtype=np.uint8)
    for region in regions:
        x, y, width, height = _expanded_box(region, image.size)
        mask[y : y + height, x : x + width] = 255
    repaired = cv2.inpaint(arr, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    return Image.fromarray(repaired)


def _fill_regions_with_background(image: Image.Image, regions: list[TextRegion]) -> Image.Image:
    result = image.copy()
    draw = ImageDraw.Draw(result)
    for region in regions:
        x, y, width, height = _expanded_box(region, image.size)
        color = _estimate_background_color(image.crop((x, y, x + width, y + height)))
        draw.rectangle((x, y, x + width, y + height), fill=color)
    return result


def _expanded_box(region: TextRegion, image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    margin_x = max(2, int(region.width * 0.08))
    margin_y = max(2, int(region.height * 0.16))
    x1 = max(0, region.x - margin_x)
    y1 = max(0, region.y - margin_y)
    x2 = min(image_width, region.x + region.width + margin_x)
    y2 = min(image_height, region.y + region.height + margin_y)
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _estimate_text_color(image: Image.Image, region: TextRegion) -> tuple[int, int, int]:
    x, y, width, height = _expanded_box(region, image.size)
    crop = image.crop((x, y, x + width, y + height)).convert("RGB")
    arr = np.array(crop, dtype=np.uint8)
    if arr.size == 0:
        return (20, 20, 20)
    luminance = (0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]).reshape(-1)
    median = float(np.median(luminance))
    if median >= 128:
        selected = arr.reshape(-1, 3)[luminance <= np.percentile(luminance, 25)]
    else:
        selected = arr.reshape(-1, 3)[luminance >= np.percentile(luminance, 75)]
    if selected.size == 0:
        return (20, 20, 20) if median >= 128 else (245, 245, 245)
    color = np.median(selected, axis=0)
    return tuple(int(max(0, min(255, value))) for value in color)


def _estimate_background_color(crop: Image.Image) -> tuple[int, int, int]:
    arr = np.array(crop.convert("RGB"), dtype=np.uint8).reshape(-1, 3)
    if arr.size == 0:
        return (255, 255, 255)
    return tuple(int(value) for value in np.median(arr, axis=0))


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _fit_text(text: str, box_width: int, box_height: int) -> tuple[ImageFont.ImageFont, list[str]]:
    clean_text = " ".join(str(text or "").split()) or " "
    max_size = max(9, min(64, int(box_height * 0.75)))
    min_size = 7
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size)
        lines = _wrap_text(clean_text, font, box_width)
        if _text_block_fits(lines, font, box_width, box_height):
            return font, lines
    font = _load_font(min_size)
    return font, _wrap_text(clean_text, font, box_width)


def _wrap_text(text: str, font: ImageFont.ImageFont, box_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_width(candidate, font) <= box_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if _text_width(word, font) <= box_width:
            current = word
        else:
            pieces = _split_long_word(word, font, box_width)
            lines.extend(pieces[:-1])
            current = pieces[-1] if pieces else ""
    if current:
        lines.append(current)
    return lines or [text]


def _split_long_word(word: str, font: ImageFont.ImageFont, box_width: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if current and _text_width(candidate, font) > box_width:
            pieces.append(current)
            current = char
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _text_block_fits(lines: list[str], font: ImageFont.ImageFont, box_width: int, box_height: int) -> bool:
    if not lines:
        return True
    if any(_text_width(line, font) > box_width for line in lines):
        return False
    return _line_height(font) * len(lines) <= box_height


def _text_width(text: str, font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = font.getbbox(text)
    return right - left


def _line_height(font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = font.getbbox("Ag")
    return max(1, int((bottom - top) * 1.18))
