from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.config import settings


class InpaintUnavailableError(RuntimeError):
    pass


def inpaint_with_lama(image: Image.Image, mask: np.ndarray) -> Image.Image:
    torch = _import_torch()
    model, device = _load_lama_model(torch)
    original_width, original_height = image.size

    image_tensor = _to_tensor(np.array(image.convert("RGB")), torch, device)
    mask_tensor = _to_tensor(mask, torch, device)
    mask_tensor = (mask_tensor > 0) * 1

    with torch.inference_mode():
        repaired = model(image_tensor, mask_tensor)

    arr = repaired[0].permute(1, 2, 0).detach().cpu().numpy()
    arr = np.clip(arr * 255, 0, 255).astype("uint8")
    arr = arr[:original_height, :original_width]
    return Image.fromarray(arr, mode="RGB")


def resolve_lama_model_path() -> Path:
    configured = str(settings.lama_model_path or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
        raise InpaintUnavailableError(f"LAMA model file was not found: {path}")

    root = Path(__file__).resolve().parents[2]
    candidates = [
        root / "ai-service" / "models" / "big-lama" / "big-lama.pt",
        root / "models" / "big-lama" / "big-lama.pt",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise InpaintUnavailableError(
        "LAMA model file was not found. Run scripts/install-lama-model.ps1 or set LAMA_MODEL_PATH to big-lama.pt."
    )


def lama_model_available() -> bool:
    try:
        resolve_lama_model_path()
    except InpaintUnavailableError:
        return False
    return True


def _import_torch() -> Any:
    try:
        import torch  # type: ignore
    except Exception as exc:
        raise InpaintUnavailableError("PyTorch is required for LAMA inpainting. Install ai-service/requirements-lama.txt.") from exc
    return torch


@lru_cache(maxsize=1)
def _load_lama_model(torch: Any) -> tuple[Any, Any]:
    device_name = settings.lama_device.strip().lower()
    if device_name in {"", "auto"}:
        device_name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device_name)
    model_path = resolve_lama_model_path()
    model = torch.jit.load(str(model_path), map_location=device)
    model.eval()
    return model, device


def _to_tensor(value: np.ndarray, torch: Any, device: Any) -> Any:
    if value.ndim == 3:
        arr = np.transpose(value, (2, 0, 1))
    elif value.ndim == 2:
        arr = value[np.newaxis, ...]
    else:
        raise ValueError("Expected an RGB image or a single-channel mask")

    arr = arr.astype(np.float32) / 255
    arr = _pad_to_modulo(arr, 8)
    return torch.from_numpy(arr).unsqueeze(0).to(device)


def _pad_to_modulo(arr: np.ndarray, modulo: int) -> np.ndarray:
    _, height, width = arr.shape
    padded_height = _ceil_modulo(height, modulo)
    padded_width = _ceil_modulo(width, modulo)
    return np.pad(
        arr,
        ((0, 0), (0, padded_height - height), (0, padded_width - width)),
        mode="symmetric",
    )


def _ceil_modulo(value: int, modulo: int) -> int:
    if value % modulo == 0:
        return value
    return (value // modulo + 1) * modulo
