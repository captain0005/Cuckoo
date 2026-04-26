from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.config import settings
from app.retry import retry_with_backoff


LANGUAGE_NAME_MAP = {
    "ar": "Arabic",
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "zh": "Chinese",
}


class Translator(Protocol):
    def translate(self, text: str, source_language: str, target_language: str) -> str:
        """Translate one text fragment."""


def normalize_language(language: str) -> str:
    normalized = (language or "").strip()
    if not normalized:
        return normalized
    return LANGUAGE_NAME_MAP.get(normalized.lower(), normalized)


def extract_chat_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("translation response did not include choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [item.get("text", "").strip() for item in content if isinstance(item, dict)]
        return "\n".join(part for part in parts if part).strip()
    raise ValueError("translation response did not include assistant text")


class MockTranslator:
    """Development translator that makes the pipeline observable without an API key."""

    _dictionary = {
        "\u4e09\u5408\u4e00\u7535\u78c1\u8f90\u5c04\u68c0\u6d4b\u4eea": "3-in-1 EMF Radiation Detector",
        "\u4e09\u5408\u4e00": "3-in-1",
        "\u7535\u78c1\u8f90\u5c04": "EMF Radiation",
        "\u68c0\u6d4b\u4eea": "Detector",
        "\u4ea7\u54c1\u53c2\u6570": "Product Specifications",
        "\u4f7f\u7528\u65b9\u6cd5": "How to Use",
        "\u6ce8\u610f\u4e8b\u9879": "Precautions",
    }

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        if not text.strip():
            return text
        if target_language.lower() == "en":
            compact = "".join(text.split())
            if compact in self._dictionary:
                return self._dictionary[compact]
        return f"[{normalize_language(target_language) or target_language}] {text}"


class OpenAICompatibleTranslator:
    """OpenAI-compatible translation provider, including Qwen-MT style endpoints."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = (endpoint or settings.translate_endpoint).strip()
        self.api_key = (api_key or settings.translate_api_key).strip()
        self.model = (model or settings.translate_model).strip() or "qwen-mt-plus"
        self.timeout_seconds = timeout_seconds or settings.translate_timeout_seconds
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=self.timeout_seconds, write=10.0, pool=10.0)
        )

    def close(self) -> None:
        if self._owns_client and not self.client.is_closed:
            self.client.close()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        if not text.strip():
            return text
        if not self.endpoint:
            raise RuntimeError("TRANSLATE_ENDPOINT is not configured")
        if not self.api_key:
            raise RuntimeError("TRANSLATE_API_KEY is not configured")

        source = normalize_language(source_language)
        target = normalize_language(target_language)
        response = self.client.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": text}],
                "translation_options": {
                    "source_lang": source,
                    "target_lang": target,
                },
                "stream": False,
            },
        )
        response.raise_for_status()
        return extract_chat_message_text(response.json()) or text


class DeepLTranslator:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key or settings.deepl_api_key).strip()
        self.api_url = (api_url or settings.deepl_api_url).strip()
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        if self._owns_client and not self.client.is_closed:
            self.client.close()

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        if not text.strip():
            return text
        if not self.api_key:
            raise RuntimeError("DEEPL_API_KEY is not configured")
        response = self.client.post(
            self.api_url,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
            data={
                "text": text,
                "source_lang": source_language.upper(),
                "target_lang": target_language.upper(),
            },
        )
        response.raise_for_status()
        translations = response.json().get("translations") or []
        if not translations:
            return text
        return str(translations[0].get("text") or text).strip()


class CachedTranslator:
    def __init__(self, translator: Translator) -> None:
        self.translator = translator
        self.cache: dict[tuple[str, str, str], str] = {}

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        key = (text, source_language, target_language)
        if key not in self.cache:
            self.cache[key] = retry_with_backoff(
                lambda: self.translator.translate(text, source_language, target_language),
                max_retries=3,
                base_delay=0.5,
            )
        return self.cache[key]


def build_translator() -> Translator:
    provider = settings.translator_provider.strip().lower()
    if provider == "openai":
        return CachedTranslator(OpenAICompatibleTranslator())
    if provider == "deepl":
        return CachedTranslator(DeepLTranslator())
    if settings.translate_endpoint and settings.translate_api_key:
        return CachedTranslator(OpenAICompatibleTranslator())
    return CachedTranslator(MockTranslator())
