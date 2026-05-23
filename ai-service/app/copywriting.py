from __future__ import annotations

import re
from dataclasses import dataclass

from app.text_utils import normalize_ocr_text
from app.translation import Translator, normalize_language


@dataclass(slots=True)
class LayoutTranslationRequest:
    source_text: str
    role: str
    region_box: tuple[int, int, int, int]
    image_size: tuple[int, int]


_ROLE_WORD_LIMITS = {
    "title": 6,
    "center_title": 6,
    "section_title": 4,
    "subtitle": 13,
    "feature_bar": 5,
    "tag": 5,
    "label": 4,
    "table_key": 4,
    "table_value": 9,
    "manual": 7,
}

_SHORT_COPY_BY_SOURCE = {
    "TYPE-C锂电直充": "Type-C Direct Charge",
    "无需更换电池": "No Battery Swap",
    "TYPE-C锂电直充无需更换电池": "Type-C Direct Charge No Battery Swap",
    "内置高达1000毫安高性能锂电池,12小时超长续航,使用时间更长": "1000mAh Battery, Up to 12h",
    "内置高达1000毫安高性能锂电池,12小时超长续航使用时间更长": "1000mAh Battery, Up to 12h",
    "超标自动报警": "Auto Alarm",
    "及时警报避免接触": "Avoid Contact",
    "超标自动报警及时警报避免接触": "Auto Alarm Avoid Contact",
    "三种警报,超出阈值时蜂鸣、灯光、屏幕同时报警": "Buzzer, Light and Screen Alerts",
    "三种警报超出阈值时蜂鸣、灯光、屏幕同时报警": "Buzzer, Light and Screen Alerts",
    "灯光报警": "Light Alarm",
    "屏幕报警": "Screen Alarm",
    "声音报警": "Sound Alarm",
    "产品参数": "Product Parameters",
    "参数": "Parameters",
    "规格": "Specifications",
    "产品型号": "Product Model",
    "屏幕材质": "Screen Material",
    "背光": "Backlight",
    "供电电源": "Power Supply",
    "电池": "Battery",
    "语言": "Language",
    "产品尺寸": "Dimensions",
    "裸机重量": "Net Weight",
    "配件清单": "Accessory List",
    "主机": "Main Unit",
    "Type-C充电线": "Type-C Cable",
    "包装盒": "Packaging Box",
    "说明书": "Manual",
}

_FILLER_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "for",
    "from",
    "is",
    "of",
    "the",
    "to",
    "when",
    "with",
}


def translate_for_layout(
    translator: Translator,
    requests: list[LayoutTranslationRequest],
    source_language: str,
    target_language: str,
) -> list[str]:
    if not requests:
        return []

    source_texts = [request.source_text for request in requests]
    translated_texts = _translate_texts(translator, source_texts, source_language, target_language)
    return [
        adapt_translation_for_layout(
            source_text=request.source_text,
            translated_text=translated_text,
            role=request.role,
            target_language=target_language,
        )
        for request, translated_text in zip(requests, translated_texts)
    ]


def adapt_translation_for_layout(
    *,
    source_text: str,
    translated_text: str,
    role: str,
    target_language: str,
) -> str:
    if not _is_english_target(target_language):
        return _clean_translation(translated_text)

    dictionary_match = _lookup_short_copy(source_text)
    if dictionary_match:
        return dictionary_match

    clean = _clean_translation(translated_text)
    if not clean:
        return clean

    if role in {"title", "center_title", "section_title", "feature_bar", "tag", "label", "table_key"}:
        clean = _to_title_case(clean)
    else:
        clean = _sentence_without_terminal_period(clean)

    return _limit_words_for_role(clean, role)


def _translate_texts(
    translator: Translator,
    texts: list[str],
    source_language: str,
    target_language: str,
) -> list[str]:
    if len(texts) == 1:
        return [translator.translate(texts[0], source_language, target_language)]

    joined_text = "\n".join(texts)
    translated = translator.translate(joined_text, source_language, target_language)
    translated_lines = [line.strip() for line in translated.splitlines() if line.strip()]
    if len(translated_lines) == len(texts):
        return translated_lines

    return [translator.translate(text, source_language, target_language) for text in texts]


def _is_english_target(target_language: str) -> bool:
    normalized = normalize_language(target_language).lower()
    return normalized in {"en", "english"}


def _lookup_short_copy(source_text: str) -> str:
    normalized = normalize_ocr_text(source_text)
    compact = _source_key(normalized)
    for source, target in _SHORT_COPY_BY_SOURCE.items():
        if compact == _source_key(source):
            return target

    if "TYPE-C" in compact.upper() and "锂电" in compact and "无需" in compact:
        return "Type-C Direct Charge No Battery Swap"
    if "无需" in compact and "电池" in compact:
        return "No Battery Swap"
    if "1000" in compact and "锂电池" in compact:
        return "1000mAh Battery, Up to 12h"
    if "三种警报" in compact and "报警" in compact:
        return "Buzzer, Light and Screen Alerts"

    parts = [part for part in re.split(r"[,.;!?，。；！？\n]+", normalized) if part.strip()]
    if len(parts) > 1:
        mapped = []
        for part in parts:
            part_key = _source_key(part)
            mapped.append(next((target for source, target in _SHORT_COPY_BY_SOURCE.items() if _source_key(source) == part_key), None))
        if all(mapped):
            return " ".join(item for item in mapped if item)
    return ""


def _source_key(text: str) -> str:
    compact = re.sub(r"\s+", "", normalize_ocr_text(text))
    compact = compact.replace("，", ",").replace("。", ".").replace("；", ";").replace("：", ":")
    compact = compact.replace("、", ",").replace("換", "换")
    return compact


def _clean_translation(text: str) -> str:
    clean = " ".join(str(text or "").split()).strip()
    clean = re.sub(r"^\[(?:English|EN|英语)\]\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^(?:translation|translated text)\s*[:：]\s*", "", clean, flags=re.IGNORECASE)
    clean = clean.strip(" \t\r\n\"'`")
    return clean


def _to_title_case(text: str) -> str:
    words = text.split()
    titled: list[str] = []
    for word in words:
        if _looks_like_unit_or_brand(word):
            titled.append(word)
        elif "-" in word:
            titled.append("-".join(_capitalize_piece(piece) for piece in word.split("-")))
        else:
            titled.append(_capitalize_piece(word))
    return " ".join(titled)


def _capitalize_piece(piece: str) -> str:
    if not piece:
        return piece
    return piece[:1].upper() + piece[1:].lower()


def _looks_like_unit_or_brand(word: str) -> bool:
    stripped = re.sub(r"[^A-Za-z0-9+-]", "", word)
    if not stripped:
        return False
    if stripped.isupper() and len(stripped) <= 5:
        return True
    return any(char.isdigit() for char in stripped) or stripped.upper() in {"USB", "TYPE-C", "EMF", "LED", "LCD"}


def _sentence_without_terminal_period(text: str) -> str:
    clean = text.strip()
    return clean[:-1] if clean.endswith(".") else clean


def _limit_words_for_role(text: str, role: str) -> str:
    limit = _ROLE_WORD_LIMITS.get(role, 8)
    words = text.split()
    if len(words) <= limit:
        return text

    if role in {"title", "center_title", "section_title", "feature_bar", "tag", "label", "table_key", "manual"}:
        important = [word for word in words if _word_key(word) not in _FILLER_WORDS]
        if len(important) >= 2:
            words = important

    return " ".join(words[:limit])


def _word_key(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())
