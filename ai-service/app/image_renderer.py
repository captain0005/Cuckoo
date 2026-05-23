from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.inpainting import InpaintUnavailableError, inpaint_with_lama
from app.ocr import TextRegion


@dataclass(slots=True)
class TextReplacement:
    region: TextRegion
    translated_text: str
    force: bool = False
    erase_regions: list[TextRegion] | None = None
    role_hint: str | None = None


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


REGULAR_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]

BOLD_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]

BOLD_ROLES = {"title", "center_title", "section_title", "feature_bar", "tag", "table_key", "label", "manual"}
TITLE_ROLES = {"title", "center_title", "section_title"}
SKIP_ROLES = {"micro", "icon_badge", "decorative_badge", "product_detail"}
TABLE_ROLES = {"table_key", "table_value"}


def render_replacements(
    *,
    source_path: Path,
    output_path: Path,
    replacements: list[TextReplacement],
    inpaint_engine: str | None = None,
    warnings: list[str] | None = None,
) -> list[TextReplacement]:
    image = Image.open(source_path).convert("RGB")
    layouts = _plan_text_layouts(image, replacements)
    repaired = _inpaint_layouts(image, layouts, engine=inpaint_engine or settings.inpaint_engine, warnings=warnings)
    draw = ImageDraw.Draw(repaired)

    for layout in layouts:
        _draw_text_block(draw, layout)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    repaired.save(output_path, quality=96)
    return [layout.replacement for layout in layouts]


def _plan_text_layouts(image: Image.Image, replacements: list[TextReplacement]) -> list[TextLayout]:
    layouts: list[TextLayout] = []
    for item in replacements:
        role = item.role_hint or _region_role(item.region, image.size, image=image)
        if item.force and role in SKIP_ROLES:
            role = "manual"
        if not _should_render_replacement(item, image.size, role):
            continue
        box = _layout_box(item.region, image.size, role, image=image)
        color = _estimate_text_color(image, item.region, role)
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
    layouts = _stabilize_bottom_label_columns(layouts, image.size)
    return _resolve_text_collisions(layouts, image.size)


def classify_region_role(
    region: TextRegion,
    image_size: tuple[int, int],
    *,
    image: Image.Image | None = None,
) -> str:
    return _region_role(region, image_size, image=image)


def _stabilize_bottom_label_columns(layouts: list[TextLayout], image_size: tuple[int, int]) -> list[TextLayout]:
    image_width, image_height = image_size
    bottom_labels = [
        layout
        for layout in layouts
        if layout.role == "label" and layout.replacement.region.y / max(1, image_height) > 0.82
    ]
    if len(bottom_labels) < 2:
        return layouts

    labels = sorted(bottom_labels, key=lambda layout: layout.replacement.region.x + layout.replacement.region.width / 2)
    page_margin = max(18, int(image_width * 0.035))
    column_gap = max(4, int(image_width * 0.008))
    centers = [layout.replacement.region.x + layout.replacement.region.width / 2 for layout in labels]
    boundaries = [float(page_margin)]
    boundaries.extend((left + right) / 2 for left, right in zip(centers, centers[1:]))
    boundaries.append(float(image_width - page_margin))

    for index, layout in enumerate(labels):
        left_bound = boundaries[index] + column_gap
        right_bound = boundaries[index + 1] - column_gap
        width = max(1, int(right_bound - left_bound))
        region = layout.replacement.region
        height = max(region.height, int(region.height * 1.55), int(image_height * 0.036))
        top = max(0, min(image_height - height, region.y - (height - region.height) // 2))
        _apply_candidate_box(layout, (int(left_bound), top, width, height), image_size)

    return layouts


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
    return role in {*TITLE_ROLES, "subtitle"}


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
    role_rank = {
        "title": 0,
        "center_title": 0,
        "section_title": 1,
        "subtitle": 2,
        "feature_bar": 3,
        "tag": 4,
        "table_key": 5,
        "table_value": 5,
        "body": 6,
        "label": 7,
    }
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
    if layout.role in TABLE_ROLES:
        return [(x, y, width, height)]

    band_top, band_bottom = _placement_band(layout.role, (x, y, width, height), image_size, broad=broad)
    max_y = max(band_top, band_bottom - height)
    y_step = max(4, min(36, int(max(height, layout.replacement.region.height) * 0.65)))
    x_step = max(8, min(54, int(width * 0.18)))

    if layout.role in {*TITLE_ROLES, "subtitle", "feature_bar", "tag"}:
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
        if role in {"title", "center_title", "subtitle"}:
            return margin_y, max(int(image_height * 0.26), y + height)
        if role == "section_title":
            return max(margin_y, y - int(image_height * 0.08)), min(image_height - margin_y, y + height + int(image_height * 0.10))
        if role == "label":
            return max(margin_y, int(image_height * 0.68)), image_height - margin_y
        if role == "feature_bar":
            return max(margin_y, y - height), min(image_height - margin_y, y + height * 2)
        if role == "tag":
            return max(margin_y, y - height), min(image_height - margin_y, y + height * 2)
        return margin_y, image_height - margin_y

        if role in {"title", "center_title", "subtitle"}:
            return margin_y, max(int(image_height * 0.22), y + height)
    if role == "section_title":
        return max(margin_y, y - int(image_height * 0.035)), min(image_height - margin_y, y + height + int(image_height * 0.05))
    if role == "label":
        top = max(margin_y, int(image_height * 0.70), y - max(height * 2, int(image_height * 0.05)))
        return top, image_height - margin_y
    if role == "feature_bar":
        return max(margin_y, y - max(4, height // 2)), min(image_height - margin_y, y + height + max(4, height // 2))
    if role == "tag":
        return max(margin_y, y - max(4, height // 2)), min(image_height - margin_y, y + height + max(4, height // 2))

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


def _inpaint_layouts(
    image: Image.Image,
    layouts: list[TextLayout],
    *,
    engine: str = "lama",
    warnings: list[str] | None = None,
) -> Image.Image:
    if not layouts:
        return image.copy()

    mask = _build_inpaint_mask(image, layouts)
    requested_engine = (engine or "lama").strip().lower()
    if requested_engine in {"lama", "auto"}:
        try:
            repaired = _inpaint_masked_area_with_lama(image, mask)
            return _refill_flat_regions(image, repaired, layouts)
        except InpaintUnavailableError as exc:
            if warnings is not None:
                warnings.append(f"LAMA inpainting unavailable; used OpenCV fallback. {exc}")
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"LAMA inpainting failed; used OpenCV fallback. {exc}")

    try:
        import cv2  # type: ignore
    except Exception:
        return _fill_layout_regions_with_background(image, layouts)

    arr = np.array(image)
    repaired = Image.fromarray(cv2.inpaint(arr, mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA))
    return _refill_flat_regions(image, repaired, layouts)


def _inpaint_masked_area_with_lama(image: Image.Image, mask: np.ndarray) -> Image.Image:
    bounds = _mask_bounds(mask)
    if bounds is None:
        return image.copy()

    if _should_split_lama_mask(image, bounds, mask):
        components = _mask_component_bounds(mask)
        if 1 < len(components) <= 14:
            repaired = image.copy()
            for component_bounds in components:
                component_mask = np.zeros_like(mask)
                left, top, right, bottom = component_bounds
                component_mask[top:bottom, left:right] = mask[top:bottom, left:right]
                repaired = _inpaint_single_lama_bounds(repaired, component_mask, component_bounds)
            return repaired

    return _inpaint_single_lama_bounds(image, mask, bounds)


def _inpaint_single_lama_bounds(image: Image.Image, mask: np.ndarray, bounds: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    padding = max(32, int(max(width, height) * 0.18))
    crop_box = (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )

    crop_width = crop_box[2] - crop_box[0]
    crop_height = crop_box[3] - crop_box[1]
    crop_area = crop_width * crop_height
    image_area = image.width * image.height
    if crop_area >= image_area * 0.92:
        return inpaint_with_lama(image, mask)

    crop = image.crop(crop_box)
    mask_crop = mask[crop_box[1] : crop_box[3], crop_box[0] : crop_box[2]]
    repaired_crop = inpaint_with_lama(crop, mask_crop)
    repaired = image.copy()
    repaired.paste(repaired_crop, crop_box[:2])
    return repaired


def _should_split_lama_mask(image: Image.Image, bounds: tuple[int, int, int, int], mask: np.ndarray) -> bool:
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    crop_area = width * height
    image_area = image.width * image.height
    configured_limit = max(0, int(settings.lama_max_pixels or 0))
    if configured_limit > 0 and crop_area > configured_limit:
        return True
    return crop_area >= image_area * 0.45 and np.count_nonzero(mask) < crop_area * 0.25


def _mask_component_bounds(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    try:
        import cv2  # type: ignore
    except Exception:
        bounds = _mask_bounds(mask)
        return [bounds] if bounds else []

    component_count, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    bounds: list[tuple[int, int, int, int]] = []
    for index in range(1, component_count):
        x, y, width, height, area = stats[index]
        if int(area) <= 0:
            continue
        bounds.append((int(x), int(y), int(x + width), int(y + height)))
    return sorted(bounds, key=lambda item: (item[1], item[0]))


def _mask_bounds(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _build_inpaint_mask(image: Image.Image, layouts: list[TextLayout]) -> np.ndarray:
    mask = np.zeros((image.height, image.width), dtype=np.uint8)
    for layout in layouts:
        for x, y, width, height in _erase_boxes_for_layout(layout, image.size):
            mask[y : y + height, x : x + width] = 255
    return mask


def _refill_flat_regions(
    source: Image.Image,
    repaired: Image.Image,
    layouts: list[TextLayout],
) -> Image.Image:
    result = repaired.copy()
    draw = ImageDraw.Draw(result)
    for layout in layouts:
        if layout.role in TABLE_ROLES:
            for rect in _erase_boxes_for_layout(layout, source.size):
                _fill_table_region_with_local_background(result, source, rect)
            continue
        if layout.role not in {"label", "feature_bar", "tag"}:
            continue
        for x, y, width, height in _erase_boxes_for_layout(layout, source.size):
            color = _estimate_background_color(source.crop((x, y, x + width, y + height)))
            draw.rectangle((x, y, x + width, y + height), fill=color)
    return result


def _fill_table_region_with_local_background(
    target: Image.Image,
    source: Image.Image,
    rect: tuple[int, int, int, int],
) -> None:
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        return

    source_arr = np.array(source.convert("RGB"), dtype=np.float32)
    target_arr = np.array(target.convert("RGB"), dtype=np.uint8)
    image_height, image_width = target_arr.shape[:2]
    x2 = min(image_width, x + width)
    y2 = min(image_height, y + height)
    x = max(0, x)
    y = max(0, y)
    if x2 <= x or y2 <= y:
        return

    strip_width = max(3, min(14, max(1, width // 10)))
    left_strip = source_arr[y:y2, max(0, x - strip_width) : x]
    right_strip = source_arr[y:y2, x2 : min(image_width, x2 + strip_width)]
    if left_strip.size == 0 and right_strip.size == 0:
        color = np.array(_estimate_background_color(source.crop((x, y, x2, y2))), dtype=np.uint8)
        target_arr[y:y2, x:x2] = color
        target.paste(Image.fromarray(target_arr))
        return

    if left_strip.size == 0:
        left_colors = np.median(right_strip, axis=1)
    else:
        left_colors = np.median(left_strip, axis=1)
    if right_strip.size == 0:
        right_colors = left_colors
    else:
        right_colors = np.median(right_strip, axis=1)

    steps = np.linspace(0.0, 1.0, max(1, x2 - x), dtype=np.float32)[None, :, None]
    fill = left_colors[:, None, :] * (1.0 - steps) + right_colors[:, None, :] * steps
    target_arr[y:y2, x:x2] = np.clip(fill, 0, 255).astype(np.uint8)
    target.paste(Image.fromarray(target_arr))


def _fill_layout_regions_with_background(image: Image.Image, layouts: list[TextLayout]) -> Image.Image:
    result = image.copy()
    draw = ImageDraw.Draw(result)
    for layout in layouts:
        for x, y, width, height in _erase_boxes_for_layout(layout, image.size):
            color = _estimate_background_color(image.crop((x, y, x + width, y + height)))
            draw.rectangle((x, y, x + width, y + height), fill=color)
    return result


def _erase_boxes_for_layout(layout: TextLayout, image_size: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    erase_regions = layout.replacement.erase_regions or [layout.replacement.region]
    role = "manual" if layout.replacement.erase_regions else layout.role
    return [_erase_box(region, image_size, role) for region in erase_regions]


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
    if role in TABLE_ROLES:
        image_width, image_height = image_size
        margin_x = max(4, int(region.width * 0.16))
        margin_y = max(2, int(region.height * 0.12))
        x1 = max(0, region.x - margin_x)
        y1 = max(0, region.y - margin_y)
        x2 = min(image_width, region.x + region.width + margin_x)
        y2 = min(image_height, region.y + region.height + margin_y)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

    if role == "manual":
        image_width, image_height = image_size
        margin_x = max(1, int(region.width * 0.025))
        margin_y = max(1, int(region.height * 0.06))
        x1 = max(0, region.x - margin_x)
        y1 = max(0, region.y - margin_y)
        x2 = min(image_width, region.x + region.width + margin_x)
        y2 = min(image_height, region.y + region.height + margin_y)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

    if role in {"feature_bar", "tag"}:
        image_width, image_height = image_size
        margin_x = max(1, int(region.width * (0.025 if role == "feature_bar" else 0.05)))
        margin_y = max(1, int(region.height * (0.10 if role == "feature_bar" else 0.14)))
        x1 = max(0, region.x - margin_x)
        y1 = max(0, region.y - margin_y)
        x2 = min(image_width, region.x + region.width + margin_x)
        y2 = min(image_height, region.y + region.height + margin_y)
        return x1, y1, max(1, x2 - x1), max(1, y2 - y1)

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


def _layout_box(
    region: TextRegion,
    image_size: tuple[int, int],
    role: str,
    *,
    image: Image.Image | None = None,
) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    x, y, width, height = _expanded_box(region, image_size)
    page_margin = max(18, int(image_width * 0.035))

    if role == "manual":
        return _clamp_box((region.x, region.y, region.width, region.height), image_size)

    if role == "center_title":
        left = max(page_margin, min(x, int(image_width * 0.08)))
        right = min(image_width - page_margin, max(x + width, int(image_width * 0.92)))
        title_height = max(height, int(region.height * 1.45), int(image_height * 0.075))
        return left, y, max(1, right - left), title_height

    if role == "title":
        left = max(page_margin, min(x, int(image_width * 0.06)))
        right = min(image_width - page_margin, max(x + width, int(image_width * 0.90)))
        title_height = max(height, int(region.height * 1.45), int(image_height * 0.075))
        return left, y, max(1, right - left), title_height

    if role == "subtitle":
        left = max(page_margin, min(x, int(image_width * 0.06)))
        right = min(image_width - page_margin, max(x + width, int(image_width * 0.82)))
        subtitle_height = max(height, int(region.height * 1.8), int(image_height * 0.035))
        return left, y, max(1, right - left), subtitle_height

    if role == "section_title":
        left = max(page_margin, min(x, int(image_width * 0.06)))
        right = min(image_width - page_margin, max(x + width, int(image_width * 0.90)))
        title_height = max(height, int(region.height * 1.35), int(image_height * 0.060))
        return left, y, max(1, right - left), title_height

    if role in TABLE_ROLES:
        divider_x = int(image_width * 0.32)
        table_left = max(page_margin, int(image_width * 0.055))
        table_right = image_width - page_margin
        if role == "table_key":
            left = table_left
            right = max(left + 1, divider_x)
        else:
            left = max(page_margin, int(image_width * 0.335))
            right = table_right
        cell_height = max(height, int(region.height * 1.45), int(image_height * 0.028))
        top = max(0, min(image_height - cell_height, region.y - (cell_height - region.height) // 2))
        return left, top, max(1, right - left), cell_height

    if role == "feature_bar":
        background_box = _colored_background_bounds(image, region, image_size, prefer_blue=True) if image is not None else None
        if background_box is not None:
            bg_x, bg_y, bg_width, bg_height = background_box
            inset_x = max(4, int(bg_width * 0.06))
            inset_y = max(2, int(bg_height * 0.10))
            left = max(region.x, bg_x + inset_x)
            right = min(image_width - page_margin, bg_x + bg_width - inset_x)
            top = max(0, min(image_height - max(1, bg_height - inset_y * 2), bg_y + inset_y))
            return left, top, max(1, right - left), max(1, bg_height - inset_y * 2)
        left = max(page_margin, region.x)
        right = min(image_width - page_margin, region.x + region.width)
        feature_height = max(region.height, int(region.height * 1.35), int(image_height * 0.042))
        top = max(0, min(image_height - feature_height, region.y - (feature_height - region.height) // 2))
        return left, top, max(1, right - left), feature_height

    if role == "tag":
        background_box = _colored_background_bounds(image, region, image_size, prefer_blue=False) if image is not None else None
        if background_box is not None:
            bg_x, bg_y, bg_width, bg_height = background_box
            inset_x = max(3, int(bg_width * 0.04))
            inset_y = max(1, int(bg_height * 0.08))
            return (
                bg_x + inset_x,
                bg_y + inset_y,
                max(1, bg_width - inset_x * 2),
                max(1, bg_height - inset_y * 2),
            )
        tag_width = min(
            image_width - page_margin * 2,
            max(width, int(region.width * 1.12)),
        )
        tag_height = max(height, int(region.height * 1.45), int(image_height * 0.032))
        center_x = region.x + region.width // 2
        left = max(page_margin, min(image_width - page_margin - tag_width, center_x - tag_width // 2))
        top = max(0, min(image_height - tag_height, region.y - (tag_height - region.height) // 2))
        return left, top, tag_width, tag_height

    if role == "label":
        background_box = _colored_background_bounds(image, region, image_size, prefer_blue=True) if image is not None else None
        if background_box is not None and background_box[2] <= image_width * 0.45:
            bg_x, bg_y, bg_width, bg_height = background_box
            inset_x = max(4, int(bg_width * 0.06))
            inset_y = max(1, int(bg_height * 0.08))
            return (
                bg_x + inset_x,
                bg_y + inset_y,
                max(1, bg_width - inset_x * 2),
                max(1, bg_height - inset_y * 2),
            )
        label_width = min(
            image_width - page_margin * 2,
            max(width, int(region.width * 2.4), int(image_width * 0.25)),
        )
        label_height = max(height, int(region.height * 1.8), int(image_height * 0.04))
        center_x = region.x + region.width // 2
        left = max(page_margin, min(image_width - page_margin - label_width, center_x - label_width // 2))
        top = max(0, min(image_height - label_height, region.y - (label_height - region.height) // 2))
        return left, top, label_width, label_height

    return x, y, width, height


def _region_role(region: TextRegion, image_size: tuple[int, int], image: Image.Image | None = None) -> str:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    center_x_ratio = (region.x + region.width / 2) / max(1, image_width)

    if _is_micro_or_embedded_text(region, image_size):
        return "micro"

    if _looks_like_icon_badge(region, image_size):
        return "icon_badge"
    if _looks_like_decorative_badge(region, image_size):
        return "decorative_badge"
    if _looks_like_feature_bar(region, image_size, image):
        return "feature_bar"
    if _looks_like_colored_tag(region, image_size, image):
        return "tag"
    if _looks_like_product_detail_text(region, image_size, image):
        return "product_detail"
    if y_ratio > 0.78 and _looks_like_bottom_caption(region, image_size):
        return "label"
    if (
        y_ratio < 0.22
        and 0.40 <= center_x_ratio <= 0.60
        and height_ratio >= 0.035
    ):
        return "center_title"
    if y_ratio < 0.22 and (height_ratio >= 0.035 or (y_ratio < 0.10 and width_ratio >= 0.36)):
        return "title"
    if height_ratio >= 0.038 and width_ratio >= 0.18:
        return "section_title"
    if y_ratio < 0.34 and width_ratio >= 0.28:
        return "subtitle"
    if _looks_like_table_cell_text(region, image_size, image):
        return "table_key" if center_x_ratio < 0.34 else "table_value"
    if 0.10 <= y_ratio <= 0.62 and height_ratio >= 0.018 and center_x_ratio < 0.34:
        return "table_key"
    if (
        0.30 <= y_ratio <= 0.78
        and region.width < max(80, int(image_width * 0.11))
        and region.height < max(34, int(image_height * 0.028))
    ):
        return "micro"
    return "body"


def _looks_like_table_cell_text(
    region: TextRegion,
    image_size: tuple[int, int],
    image: Image.Image | None,
) -> bool:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    height_ratio = region.height / max(1, image_height)
    if image is None or not (0.10 <= y_ratio <= 0.62 and height_ratio >= 0.016):
        return False
    top = max(0, region.y - max(16, int(region.height * 0.75)))
    bottom = min(image_height, region.y + region.height + max(16, int(region.height * 0.75)))
    if bottom <= top:
        return False
    strip = image.crop((0, top, image_width, bottom)).convert("L")
    arr = np.array(strip, dtype=np.uint8)
    if arr.size == 0:
        return False
    row_dark_ratio = np.mean(arr < 145, axis=1)
    return float(np.max(row_dark_ratio)) >= 0.45


def _looks_like_icon_badge(region: TextRegion, image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    text = str(region.text or "").strip()
    compact_cjk_count = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    return 0 < compact_cjk_count <= 1 and width_ratio <= 0.075 and height_ratio <= 0.075


def _looks_like_decorative_badge(region: TextRegion, image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    return y_ratio >= 0.78 and width_ratio >= 0.075 and height_ratio >= 0.045


def _looks_like_feature_bar(
    region: TextRegion,
    image_size: tuple[int, int],
    image: Image.Image | None,
) -> bool:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    center_x_ratio = (region.x + region.width / 2) / max(1, image_width)
    if not (0.34 <= y_ratio <= 0.92 and 0.10 <= width_ratio <= 0.55 and 0.018 <= height_ratio <= 0.065):
        return False
    if center_x_ratio > 0.50:
        return False
    if image is None:
        return False
    return _dominant_blue_ratio(image, region, image_size) >= 0.22


def _looks_like_colored_tag(
    region: TextRegion,
    image_size: tuple[int, int],
    image: Image.Image | None,
) -> bool:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    if not (0.25 <= y_ratio <= 0.74 and 0.055 <= width_ratio <= 0.35 and 0.018 <= height_ratio <= 0.065):
        return False
    if image is None:
        return False
    return _saturated_background_ratio(image, region, image_size) >= 0.18


def _looks_like_product_detail_text(
    region: TextRegion,
    image_size: tuple[int, int],
    image: Image.Image | None,
) -> bool:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    if not (0.28 <= y_ratio <= 0.82 and width_ratio <= 0.18 and height_ratio <= 0.035):
        return False
    if image is None:
        return False
    crop = _region_crop(image, region, image_size, margin_x=1.0, margin_y=0.9)
    if crop is None:
        return False
    arr = np.array(crop.convert("RGB"), dtype=np.uint8)
    if arr.size == 0:
        return False
    luminance = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
    saturated = (
        (arr[:, :, 1] > 135)
        & (arr[:, :, 1] > arr[:, :, 0] * 1.25)
        & (arr[:, :, 1] > arr[:, :, 2] * 1.08)
    ) | (
        (arr[:, :, 2] > 135)
        & (arr[:, :, 2] > arr[:, :, 0] * 1.20)
        & (arr[:, :, 2] > arr[:, :, 1] * 1.02)
    )
    return float(np.mean(luminance < 95)) > 0.35 and float(np.mean(saturated)) > 0.08


def _saturated_background_ratio(image: Image.Image, region: TextRegion, image_size: tuple[int, int]) -> float:
    crop = _region_crop(image, region, image_size, margin_x=0.35, margin_y=0.35)
    if crop is None:
        return 0.0
    arr = np.array(crop.convert("RGB"), dtype=np.uint8)
    if arr.size == 0:
        return 0.0
    max_channel = arr.max(axis=2).astype(np.int16)
    min_channel = arr.min(axis=2).astype(np.int16)
    saturated = (max_channel - min_channel > 70) & (max_channel > 135)
    return float(np.mean(saturated))


def _colored_background_bounds(
    image: Image.Image,
    region: TextRegion,
    image_size: tuple[int, int],
    *,
    prefer_blue: bool,
) -> tuple[int, int, int, int] | None:
    crop_box = _region_crop_box(image_size, region, margin_x=2.3, margin_y=1.3)
    if crop_box is None:
        return None

    x1, y1, x2, y2 = crop_box
    crop = image.crop(crop_box).convert("RGB")
    arr = np.array(crop, dtype=np.uint8)
    if arr.size == 0:
        return None

    red = arr[:, :, 0].astype(np.int16)
    green = arr[:, :, 1].astype(np.int16)
    blue = arr[:, :, 2].astype(np.int16)
    max_channel = np.maximum(np.maximum(red, green), blue)
    min_channel = np.minimum(np.minimum(red, green), blue)
    if prefer_blue:
        mask = (blue > 130) & (blue > red * 1.18) & (blue >= green * 0.92)
    else:
        mask = (max_channel - min_channel > 55) & (max_channel > 120)

    if float(np.mean(mask)) < 0.035:
        return None

    ys, xs = np.where(mask)
    if xs.size == 0 or ys.size == 0:
        return None

    left = int(xs.min()) + x1
    top = int(ys.min()) + y1
    right = int(xs.max()) + x1 + 1
    bottom = int(ys.max()) + y1 + 1
    width = right - left
    height = bottom - top
    if width < max(region.width, 12) or height < max(region.height * 0.8, 8):
        return None

    image_width, image_height = image_size
    width = min(width, int(image_width * 0.72))
    left = max(0, min(image_width - width, left))
    top = max(0, top)
    bottom = min(image_height, bottom)
    return left, top, max(1, width), max(1, bottom - top)


def _region_crop_box(
    image_size: tuple[int, int],
    region: TextRegion,
    *,
    margin_x: float,
    margin_y: float,
) -> tuple[int, int, int, int] | None:
    image_width, image_height = image_size
    pad_x = max(2, int(region.width * margin_x))
    pad_y = max(2, int(region.height * margin_y))
    x1 = max(0, region.x - pad_x)
    y1 = max(0, region.y - pad_y)
    x2 = min(image_width, region.x + region.width + pad_x)
    y2 = min(image_height, region.y + region.height + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2




def _dominant_blue_ratio(image: Image.Image, region: TextRegion, image_size: tuple[int, int]) -> float:
    crop = _region_crop(image, region, image_size, margin_x=1.35, margin_y=0.55)
    if crop is None:
        return 0.0
    arr = np.array(crop.convert("RGB"), dtype=np.uint8)
    if arr.size == 0:
        return 0.0
    blue_pixels = (
        (arr[:, :, 2] > 145)
        & (arr[:, :, 2] > arr[:, :, 0] * 1.25)
        & (arr[:, :, 2] > arr[:, :, 1] * 1.08)
    )
    return float(np.mean(blue_pixels))


def _region_crop(
    image: Image.Image,
    region: TextRegion,
    image_size: tuple[int, int],
    *,
    margin_x: float,
    margin_y: float,
) -> Image.Image | None:
    crop_box = _region_crop_box(image_size, region, margin_x=margin_x, margin_y=margin_y)
    if crop_box is None:
        return None
    return image.crop(crop_box)


def _is_micro_or_embedded_text(region: TextRegion, image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    y_ratio = region.y / max(1, image_height)
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    aspect = region.height / max(1, region.width)

    if region.height < max(16, int(image_height * 0.014)):
        return True
    if width_ratio < 0.045 and aspect >= 2.7:
        return True
    if (
        0.30 <= y_ratio <= 0.82
        and region.width < max(80, int(image_width * 0.11))
        and region.height < max(26, int(image_height * 0.020))
    ):
        return True
    return False


def _looks_like_bottom_caption(region: TextRegion, image_size: tuple[int, int]) -> bool:
    image_width, image_height = image_size
    width_ratio = region.width / max(1, image_width)
    height_ratio = region.height / max(1, image_height)
    return height_ratio >= 0.018 and width_ratio >= 0.055


def _should_render_replacement(item: TextReplacement, image_size: tuple[int, int], role: str) -> bool:
    if role in SKIP_ROLES and not item.force:
        return False
    clean_text = " ".join(str(item.translated_text or "").split())
    if not clean_text:
        return False
    if role == "feature_bar":
        available_chars = max(12, int(item.region.width / max(6, item.region.height * 0.32)) * 7)
        if len(clean_text) > available_chars * 2.2:
            return False
    return True


def _estimate_text_color(image: Image.Image, region: TextRegion, role: str = "body") -> tuple[int, int, int]:
    if role == "feature_bar":
        return (255, 255, 255)
    if role in {"title", "center_title", "section_title"} and _dominant_blue_ratio(image, region, image.size) >= 0.08:
        return _dominant_foreground_color(image, region, prefer="blue") or (0, 83, 245)
    x, y, width, height = _expanded_box(region, image.size)
    crop = image.crop((x, y, x + width, y + height)).convert("RGB")
    arr = np.array(crop, dtype=np.uint8)
    if arr.size == 0:
        return (20, 20, 20)
    luminance = (0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]).reshape(-1)
    median = float(np.median(luminance))
    if role == "label" and median < 128:
        return (255, 255, 255)
    if median >= 128:
        selected = arr.reshape(-1, 3)[luminance <= np.percentile(luminance, 12)]
    else:
        selected = arr.reshape(-1, 3)[luminance >= np.percentile(luminance, 88)]
    if selected.size == 0:
        return (20, 20, 20) if median >= 128 else (245, 245, 245)
    color = np.median(selected, axis=0)
    selected_luminance = float(0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2])
    if median >= 128 and selected_luminance > min(185, median - 10):
        return (24, 24, 24)
    return tuple(int(max(0, min(255, value))) for value in color)


def _dominant_foreground_color(
    image: Image.Image,
    region: TextRegion,
    *,
    prefer: str,
) -> tuple[int, int, int] | None:
    crop = _region_crop(image, region, image.size, margin_x=0.08, margin_y=0.12)
    if crop is None:
        return None
    arr = np.array(crop.convert("RGB"), dtype=np.uint8)
    if arr.size == 0:
        return None
    red = arr[:, :, 0].astype(np.int16)
    green = arr[:, :, 1].astype(np.int16)
    blue = arr[:, :, 2].astype(np.int16)
    if prefer == "blue":
        mask = (blue > 120) & (blue > red * 1.18) & (blue >= green * 0.92)
    else:
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        mask = luminance < 140
    if not np.any(mask):
        return None
    color = np.median(arr[mask], axis=0)
    return tuple(int(max(0, min(255, value))) for value in color)


def _estimate_background_color(crop: Image.Image) -> tuple[int, int, int]:
    arr = np.array(crop.convert("RGB"), dtype=np.uint8).reshape(-1, 3)
    if arr.size == 0:
        return (255, 255, 255)
    return tuple(int(value) for value in np.median(arr, axis=0))


def _load_font(size: int, role: str = "body") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = BOLD_FONT_CANDIDATES + REGULAR_FONT_CANDIDATES if role in BOLD_ROLES else REGULAR_FONT_CANDIDATES
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _fit_text(text: str, box_width: int, box_height: int, *, role: str = "body") -> tuple[ImageFont.ImageFont, list[str]]:
    clean_text = " ".join(str(text or "").split()) or " "
    max_size, min_size = _font_limits(role, box_height)
    max_lines = _max_lines_for_role(role)
    line_spacing = _line_spacing_for_role(role)
    if role == "label":
        small_one_line: tuple[ImageFont.ImageFont, list[str]] | None = None
        readable_one_line_size = max(min_size, min(max_size, 18))
        for size in range(max_size, min_size - 1, -1):
            font = _load_font(size, role)
            lines = _wrap_text(clean_text, font, box_width, split_long_words=False)
            if _text_block_fits(lines, font, box_width, box_height, line_spacing, max_lines=1):
                if size >= readable_one_line_size:
                    return font, lines
                small_one_line = (font, lines)
                break
        for size in range(max_size, min_size - 1, -1):
            font = _load_font(size, role)
            lines = _wrap_text(clean_text, font, box_width, split_long_words=False)
            if _text_block_fits(lines, font, box_width, box_height, line_spacing, max_lines=max_lines):
                return font, lines
        if small_one_line is not None:
            return small_one_line
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size, role)
        lines = _wrap_text(clean_text, font, box_width, split_long_words=False)
        if _text_block_fits(lines, font, box_width, box_height, line_spacing, max_lines=max_lines):
            return font, lines
    font = _load_font(min_size, role)
    return font, _wrap_text(clean_text, font, box_width, split_long_words=True)


def _font_limits(role: str, box_height: int) -> tuple[int, int]:
    if role in {"title", "center_title"}:
        return max(28, min(56, int(box_height * 0.66))), 14
    if role == "section_title":
        return max(24, min(52, int(box_height * 0.60))), 13
    if role == "subtitle":
        return max(10, min(22, int(box_height * 0.48))), 8
    if role == "feature_bar":
        return max(10, min(24, int(box_height * 0.58))), 7
    if role == "tag":
        return max(9, min(18, int(box_height * 0.54))), 7
    if role == "label":
        return max(12, min(32, int(box_height * 0.66))), 8
    if role == "manual":
        return max(12, min(44, int(box_height * 0.68))), 8
    if role == "table_key":
        return max(9, min(20, int(box_height * 0.56))), 7
    if role == "table_value":
        return max(8, min(20, int(box_height * 0.54))), 7
    return max(8, min(36, int(box_height * 0.62))), 7


def _max_lines_for_role(role: str) -> int | None:
    if role in {"title", "center_title", "section_title"}:
        return 3
    if role == "subtitle":
        return 3
    if role == "label":
        return 2
    if role == "feature_bar":
        return 2
    if role == "tag":
        return 2
    if role == "manual":
        return 3
    if role in TABLE_ROLES:
        return 2
    return 3


def _alignment_for_role(role: str) -> str:
    if role in {"title", "section_title", "subtitle", "feature_bar"}:
        return "left"
    if role == "center_title":
        return "center"
    return "center"


def _line_spacing_for_role(role: str) -> float:
    if role in {"title", "center_title", "section_title"}:
        return 0.98
    if role == "feature_bar":
        return 0.98
    if role == "tag":
        return 0.95
    if role == "label":
        return 0.96
    if role == "subtitle":
        return 1.1
    if role in TABLE_ROLES:
        return 0.96
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
