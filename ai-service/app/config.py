from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Cuckoo"
    data_dir: Path = Path("data")
    max_batch_size: int = Field(default=30, ge=1, le=100)
    max_upload_mb: int = Field(default=30, ge=1, le=500)

    translator_provider: str = "mock"
    source_language: str = "zh"
    target_language: str = "en"

    translate_endpoint: str = ""
    translate_api_key: str = ""
    translate_model: str = "qwen-mt-plus"
    translate_timeout_seconds: float = 45.0

    deepl_api_key: str = ""
    deepl_api_url: str = "https://api-free.deepl.com/v2/translate"

    ocr_engine: str = "paddle"
    ocr_lang: str = "ch"
    ocr_min_confidence: float = Field(default=0.55, ge=0, le=1)
    paddle_text_detection_model: str = "PP-OCRv5_mobile_det"
    paddle_text_recognition_model: str = "PP-OCRv5_mobile_rec"
    inpaint_engine: str = "lama"
    lama_model_path: str = ""
    lama_device: str = "auto"
    lama_max_pixels: int = Field(default=350_000, ge=0)
    lama_min_available_mb: int = Field(default=1600, ge=0)
    lama_torch_threads: int = Field(default=1, ge=1, le=32)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"


settings = Settings()
