from __future__ import annotations

import re
import unicodedata


_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\u2060]")
_CONTROL_CHAR_RE = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F]")
_CJK_RE = re.compile(r"[\u3400-\u9FFF]")
_PUNCT_SPACE_RE = re.compile(r"\s+([,.;:!?%)]|[\u3002\uff0c\uff1b\uff1a\uff01\uff1f\uff09])")

_COMMON_OCR_REPLACEMENTS = {
    "叁数": "参数",
    "産品": "产品",
    "萤幕": "屏幕",
    "荧幕": "屏幕",
}


def normalize_ocr_text(value: str) -> str:
    """Normalize OCR text before filtering, translation, and display."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\ufeff", "").replace("\r", "\n")
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _CONTROL_CHAR_RE.sub("", text)

    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        line = re.sub(r"(?<=[\u3400-\u9FFF])\s+(?=[\u3400-\u9FFF])", "", line)
        line = _PUNCT_SPACE_RE.sub(r"\1", line)
        for source, target in _COMMON_OCR_REPLACEMENTS.items():
            line = line.replace(source, target)
        lines.append(line)
    return "\n".join(lines).strip()


def contains_cjk(value: str) -> bool:
    return bool(_CJK_RE.search(normalize_ocr_text(value)))


def is_translatable_ocr_text(value: str) -> bool:
    text = normalize_ocr_text(value)
    if not text:
        return False
    if not contains_cjk(text):
        return False
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"[\W_]+", compact, flags=re.UNICODE):
        return False
    cjk_count = len(_CJK_RE.findall(compact))
    if cjk_count <= 1 and re.search(r"[A-Za-z0-9]", compact):
        return False
    return True
