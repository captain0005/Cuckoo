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


@dataclass(slots=True)
class TextLayout:
    replacement: TextReplacement
    box: tuple[int, int, int, int]
    color: tuple[int, int, int]
    font: ImageFont.ImageFont
    lines: list[str]
    align: str
    line_spacing: float
    role: str


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
) -> list[TextReplacement]:
    image = Image.open(source_path).convert("RGB")
    layouts = _plan_text_layouts(image, replacements)
    repaired = _inpaint_layouts(image, layouts)
    draw = ImageDraw.Draw(repaired)

    for layout in layouts:
        _draw_text_block(draw, layout)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    repaired.save(output_path, quality=96)
    return [layout.replacement for layout in layouts]


def _plan_text_layouts(image: Image.Image, replacements: list[TextReplacement]) -> list[TextLayout]:
    layouts: list[TextLayout] = []
    for item in replacements:
        role = _region_role(item.region, image.size)
        if not _should_render_replacement(item, image.size, role):
            continue
        box = _layout_box(item.region, image.size, role)
        color = _estimate_text_color(image, item.region)
        font, lines = _fit_text(item.translated_text, box[2], box[3], role=role)
        layouts.append(
            TextLayout(
                replacement=item,
                box=box,
                color=color,
                font=font,
                lines=lines,
                align=_alignment_for_role(role),
                line_spacing=_line_spacing_for_role(role),
                role=role,
            )
        )
    return _resolve_text_collisions(layouts, image.size)


def _draw_text_block(draw: ImageDraw.ImageDraw, layout: TextLayout) -> None:
    x, y, width, height = layout.box
    line_height = _line_height(layout.font, layout.line_spacing)
    total_height = line_height * len(layout.lines)
    cursor_y = y if _uses_top_alignment(layout.role) else y + max(0, (height - total_height) // 2)
    for line in layout.lines:
        text_width = _text_width(line, layout.font)
        if layout.align == "left":
            cursor_x = x
        elif layout.align == "right":
            cursor_x = x + max(0, width - text_width)
        else:
            cursor_x = x + max(0, (width - text_width) // 2)
        draw.text((cursor_x, cursor_y), line, font=layout.font, fill=layout.color)
        cursor_y += line_height


def _uses_top_alignment(role: str) -> bool:
    return role in {"title", "subtitle"}


def _text_content_bounds(layout: TextLayout) -> tuple[int, int, int, int]:
    x, y, width, height = layout.box
    content_height = _line_height(layout.font, layout.line_spacing) * len(layout.lines)
    content_y = y if _uses_top_alignment(layout.role) else y + max(0, (height - content_height) // 2)
    content_width = max((_text_width(line, layout.font) for line in layout.lines), default=0)
    content_width = min(width, content_width)
    if layout.align == "right":
        content_x = x + max(0, width - content_width)
    elif layout.align == "center":
        content_x = x + max(0, (width - content_width) // 2)
    else:
        content_x = x
    return content_x, content_y, content_width, content_height


def _resolve_text_collisions(layouts: list[TextLayout], image_size: tuple[int, int]) -> list[TextLayout]:
    if not layouts:
        return layouts

    gap = max(3, int(image_size[1] * 0.006))
    occupied: list[tuple[int, int, int, int]] = []
    kept_ids: set[int] = set()

    for layout in sorted(layouts, key=_layout_priority_key):
        if _place_layout_without_collision(layout, occupied, image_size, gap):
            occupied.append(_padded_rect(_text_content_bounds(layout), gap, image_size))
            kept_ids.add(id(layout))

    return [layout for layout in layouts if id(layout) in kept_ids]


def _layout_priority_key(layout: TextLayout) -> tuple[int, int, int]:
    role_rank = {"title": 0, "subtitle": 1, "body": 2, "label": 3}
    return (
        role_rank.get(layout.role, 9),
        layout.replacement.region.y,
        layout.replacement.region.x,
    )


def _place_layout_without_collision(
    layout: TextLayout,
    occupied: list[tuple[int, int, int, int]],
    image_size: tuple[int, int],
    gap: int,
) -> bool:
    original_box = layout.box
    original_font = layout.font
    original_lines = list(layout.lines)

    for broad in (False, True):
        for box in _candidate_layout_boxes(layout, original_box, image_size, broad=broad):
            _apply_candidate_box(layout, box, image_size)
            content_rect = _text_content_bounds(layout)
            padded_rect = _padded_rect(content_rect, gap, image_size)
            if _rect_inside_image(content_rect, image_size) and not any(
                _rects_overlap(padded_rect, other) for other in occupied
            ):
                return True

    layout.box = original_box
    layout.font = original_font
    layout.lines = original_lines
    return False


def _candidate_layout_boxes(
    layout: TextLayout,
    origin_box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    broad: bool,
) -> list[tuple[int, int, int, int]]:
    image_width, image_height = image_size
    margin_x = max(2, int(image_width * 0.01))
    x, y, width, height = _clamp_box(origin_box, image_size, margin_x=margin_x)
    band_top, band_bottom = _placement_band(layout.role, (x, y, width, height), image_size, broad=broad)
    max_y = max(band_top, band_bottom - height)
    y_step = max(4, min(36, int(max(height, layout.replacement.region.height) * 0.65)))
    x_step = max(8, min(54, int(width * 0.18)))

    if layout.role in {"title", "subtitle"}:
        x_values = [x]
        prefer_positive_y = True
    else:
        max_x = max(margin_x, image_width - margin_x - width)
        x_values = _axis_candidates(x, x_step, margin_x, max_x, prefer_positive=True)
        prefer_positive_y = layout.role != "label"

    y_values = _axis_candidates(y, y_step, band_top, max_y, prefer_positive=prefer_positive_y)
    boxes: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for candidate_y in y_values:
        for candidate_x in x_values:
            box = _clamp_box((candidate_x, candidate_y, width, height), image_size, margin_x=margin_x)
            if box not in seen:
                seen.add(box)
                boxes.append(box)
    return boxes


def _placement_band(
    role: str,
    box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    broad: bool,
) -> tuple[int, int]:
    _, image_height = image_size
    _, y, _, height = box
    margin_y = max(2, int(image_height * 0.006))

    if broad:
        if role in {"title", "subtitle"}:
            return margin_y, max(int(image_height * 0.42), y + height)
        if role == "label":
            return max(margin_y, int(image_height * 0.68)), image_height - margin_y
        return margin_y, image_height - margin_y

    if role in {"title", "subtitle"}:
        return margin_y, max(int(image_height * 0.36), y + height)
    if role == "label":
        top = max(margin_y, int(image_height * 0.70), y - max(height * 2, int(image_height * 0.05)))
        return top, image_height - margin_y

    span = max(height * 3, int(image_height * 0.08))
    return max(margin_y, y - span), min(image_height - margin_y, y + height + span)


def _axis_candidates(
    base: int,
    step: int,
    minimum: int,
    maximum: int,
    *,
    prefer_positive: bool,
) -> list[int]:
    base = max(minimum, min(maximum, base))
    values = [base]
    seen = {base}
    max_delta = max(base - minimum, maximum - base)
    directions = (1, -1) if prefer_positive else (-1, 1)
    for delta in range(step, max_delta + step, step):
        for direction in directions:
            value = max(minimum, min(maximum, base + direction * delta))
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _apply_candidate_box(layout: TextLayout, box: tuple[int, int, int, int], image_size: tuple[int, int]) -> None:
    x, y, width, height = box
    layout.font, layout.lines = _fit_text(layout.replacement.translated_text, width, height, role=layout.role)
    content_height = _line_height(layout.font, layout.line_spacing) * len(layout.lines)
    layout.box = _clamp_box((x, y, width, max(height, content_height)), image_size)


def _clamp_box(
    box: tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    margin_x: int = 0,
) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    x, y, width, height = box
    width = max(1, min(width, max(1, image_width - margin_x * 2)))
    height = max(1, min(height, image_height))
    x = max(margin_x, min(max(margin_x, image_width - margin_x - width), x))
    y = max(0, min(max(0, image_height - height), y))
    return x, y, width, height


def _padded_rect(
    rect: tuple[int, int, int, int],
    padding: int,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    x, y, width, height = rect
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(image_width, x + width + padding)
    y2 = min(image_height, y + height + padding)
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _rect_inside_image(rect: tuple[int, int, int, int], image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    x, y, width, height = rect
    return x >= 0 and y >= 0 and x + width <= image_width and y + height <= image_height


def _rects_overlap(rect_a: tuple[int, int, int, int], rect_b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = rect_a
    bx, by, bw, bh = rect_b
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _inpaint_layouts(image: Image.Image, layouts: list[TextLayout]) -> Image.Image:
    if not layouts:
        return image.copy()

    try:
        import cv2  # type: ignore
    except Exception:
        return _fill_layout_regions_with_background(image, layouts)

    arr = np.array(image)
    mask = np.zeros(arr.shape[:2], dtype=np.uint8)
    for layout in layouts:
        role = _region_role(layout.replacement.region, image.size)
        x, y, width, height = _erase_box(layout.replacement.region, image.size, role)
        mask[y : y + height, x : x + width] = 255
    repaired = cv2.inpaint(arr, mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)
    return Image.fromarray(repaired)


def _fill_layout_regions_with_background(image: Image.Image, layouts: list[TextLayout]) -> Image.Image:
    result = image.copy()
    draw = ImageDraw.Draw(result)
    for layout in layouts:
        role = _region_role(layout.replacement.region, image.size)
        x, y, width, height = _erase_box(layout.replacement.region, image.size, role)
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


def _erase_box(region: TextRegion, image_size: tuple[int, int], role: str) -> tuple[int, int, int, int]:
    if role != "label":
        return _expanded_box(region, image_size)

    image_width, image_height = image_size
    margin_x = max(1, int(region.width * 0.04))
    margin_top = max(1, int(region.height * 0.08))
    x1 = max(0, region.x - margin_x)
    y1 = max(0, region.y - margin_top)
    x2 = min(image_width, region.x + region.width + margin_x)
    y2 = min(image_height, region.y + region.height)
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def _layout_box(region: TextRegion, image_size: tuple[int, int], role: str) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    x, y, width, height = _expanded_box(region, image_size)
    page_margin = max(18, int(image_width * 0.035))

    if role == "title":
        left = max(page_margin, min(x, int(image_width * 0.06)))
        right = min(image_width - page_margin, max(x + width, int(image_width * 0.74)))
        return left, y, max(1, right - left), height

    if role == "subtitle":
        left = max(page_margin, min(x, int(image_width * 0.06)))
        right = min(image_width - page_margin, max(x + width, int(image_width * 0.68)))
        return left, y, max(1, right - left), max(height, int(region.height * 1.35))

    if role == "label":
        label_width = max(width, int(image_width * 0.16))
        center_x = region.x + region.width // 2
        left = max(page_margin, min(image_width - page_margin - label_width, center_x - label_width // 2))
        return left, y, label_width, max(height, int(region.height * 1.25))

    return x, y, width, height


def _region_role(region: TextRegion, image_size: tuple[int, int]) -> str:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)

    if y_ratio > 0.78:
        return "label"
    if y_ratio < 0.28 and (height_ratio >= 0.05 or width_ratio >= 0.48):
        return "title"
    if y_ratio < 0.34 and width_ratio >= 0.32:
        return "subtitle"
    if (
        0.30 <= y_ratio <= 0.78
        and region.width < max(80, int(image_width * 0.11))
        and region.height < max(34, int(image_height * 0.028))
    ):
        return "micro"
    return "body"


def _should_render_replacement(item: TextReplacement, image_size: tuple[int, int], role: str) -> bool:
    if role == "micro":
        return False
    clean_text = " ".join(str(item.translated_text or "").split())
    if not clean_text:
        return False
    return True


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


def _fit_text(text: str, box_width: int, box_height: int, *, role: str = "body") -> tuple[ImageFont.ImageFont, list[str]]:
    clean_text = " ".join(str(text or "").split()) or " "
    max_size, min_size = _font_limits(role, box_height)
    max_lines = _max_lines_for_role(role)
    line_spacing = _line_spacing_for_role(role)
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size)
        lines = _wrap_text(clean_text, font, box_width, split_long_words=False)
        if _text_block_fits(lines, font, box_width, box_height, line_spacing, max_lines=max_lines):
            return font, lines
    font = _load_font(min_size)
    return font, _wrap_text(clean_text, font, box_width, split_long_words=True)


def _font_limits(role: str, box_height: int) -> tuple[int, int]:
    if role == "title":
        return max(16, min(58, int(box_height * 0.62))), 13
    if role == "subtitle":
        return max(10, min(28, int(box_height * 0.46))), 8
    if role == "label":
        return max(8, min(18, int(box_height * 0.42))), 7
    return max(8, min(36, int(box_height * 0.62))), 7


def _max_lines_for_role(role: str) -> int | None:
    if role in {"title", "subtitle", "label"}:
        return 2
    return 3


def _alignment_for_role(role: str) -> str:
    if role in {"title", "subtitle"}:
        return "left"
    return "center"


def _line_spacing_for_role(role: str) -> float:
    if role == "title":
        return 1.08
    if role == "label":
        return 1.04
    if role == "subtitle":
        return 1.1
    return 1.16


def _wrap_text(
    text: str,
    font: ImageFont.ImageFont,
    box_width: int,
    *,
    split_long_words: bool = True,
) -> list[str]:
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
            if split_long_words:
                pieces = _split_long_word(word, font, box_width)
                lines.extend(pieces[:-1])
                current = pieces[-1] if pieces else ""
            else:
                current = word
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


def _text_block_fits(
    lines: list[str],
    font: ImageFont.ImageFont,
    box_width: int,
    box_height: int,
    line_spacing: float,
    *,
    max_lines: int | None = None,
) -> bool:
    if not lines:
        return True
    if max_lines is not None and len(lines) > max_lines:
        return False
    if any(_text_width(line, font) > box_width for line in lines):
        return False
    return _line_height(font, line_spacing) * len(lines) <= box_height


def _text_width(text: str, font: ImageFont.ImageFont) -> int:
    left, top, right, bottom = font.getbbox(text)
    return right - left


def _line_height(font: ImageFont.ImageFont, spacing: float = 1.18) -> int:
    left, top, right, bottom = font.getbbox("Ag")
    return max(1, int((bottom - top) * spacing))
