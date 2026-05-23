from __future__ import annotations

import gc
from pathlib import Path
import threading
from typing import Any

import numpy as np
from PIL import Image

from app.config import settings


class InpaintUnavailableError(RuntimeError):
    pass


_model_lock = threading.Lock()
_inference_lock = threading.Lock()
_cached_model: Any | None = None
_cached_device: Any | None = None
_cached_model_key: tuple[str, str] | None = None
_torch_threads_configured = False


def inpaint_with_lama(image: Image.Image, mask: np.ndarray) -> Image.Image:
    _ensure_lama_runtime_safe(image)
    torch = _import_torch()
    model, device = _load_lama_model(torch)
    original_width, original_height = image.size

    image_tensor = _to_tensor(np.array(image.convert("RGB")), torch, device)
    mask_tensor = _to_tensor(mask, torch, device)
    mask_tensor = (mask_tensor > 0) * 1

    with _inference_lock, torch.inference_mode():
        repaired = model(image_tensor, mask_tensor)

    arr = repaired[0].permute(1, 2, 0).detach().cpu().numpy()
    arr = np.clip(arr * 255, 0, 255).astype("uint8")
    arr = arr[:original_height, :original_width]
    result = Image.fromarray(arr, mode="RGB")
    del image_tensor, mask_tensor, repaired
    gc.collect()
    return result


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


def lama_runtime_status() -> dict[str, object]:
    model_error = ""
    try:
        model_path = str(resolve_lama_model_path())
    except InpaintUnavailableError as exc:
        model_path = ""
        model_error = str(exc)

    available_mb = _available_memory_mb()
    safe_memory = (
        settings.lama_min_available_mb <= 0
        or available_mb is None
        or available_mb >= settings.lama_min_available_mb
    )
    return {
        "model_available": not model_error,
        "model_error": model_error,
        "model_path": model_path,
        "max_pixels": settings.lama_max_pixels,
        "min_available_mb": settings.lama_min_available_mb,
        "available_mb": available_mb,
        "memory_safe": safe_memory,
        "cached": _cached_model is not None,
    }


def _import_torch() -> Any:
    try:
        import torch  # type: ignore
    except Exception as exc:
        raise InpaintUnavailableError("PyTorch is required for LAMA inpainting. Install ai-service/requirements-lama.txt.") from exc
    return torch


def _load_lama_model(torch: Any) -> tuple[Any, Any]:
    global _cached_device, _cached_model, _cached_model_key, _torch_threads_configured

    device_name = settings.lama_device.strip().lower()
    if device_name in {"", "auto"}:
        device_name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device_name)
    model_path = resolve_lama_model_path()
    cache_key = (str(model_path), str(device))

    with _model_lock:
        if _cached_model is not None and _cached_model_key == cache_key:
            return _cached_model, _cached_device
        if not _torch_threads_configured:
            try:
                torch.set_num_threads(settings.lama_torch_threads)
            except Exception:
                pass
            _torch_threads_configured = True
        model = torch.jit.load(str(model_path), map_location=device)
        model.eval()
        _cached_model = model
        _cached_device = device
        _cached_model_key = cache_key
        return model, device


def _ensure_lama_runtime_safe(image: Image.Image) -> None:
    max_pixels = settings.lama_max_pixels
    pixel_count = image.width * image.height
    if max_pixels > 0 and pixel_count > max_pixels:
        raise InpaintUnavailableError(
            f"LAMA crop is too large for this service ({pixel_count} pixels > {max_pixels}); used fallback."
        )

    min_available_mb = settings.lama_min_available_mb
    available_mb = _available_memory_mb()
    if min_available_mb > 0 and available_mb is not None and available_mb < min_available_mb:
        raise InpaintUnavailableError(
            f"LAMA requires at least {min_available_mb} MB available memory; only {available_mb} MB is available."
        )


def _available_memory_mb() -> int | None:
    cgroup_value = _cgroup_available_memory_mb()
    if cgroup_value is not None:
        return cgroup_value

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(int(parts[1]) / 1024)
        except OSError:
            return None
    return None


def _cgroup_available_memory_mb() -> int | None:
    # cgroup v2
    current = _read_int_file(Path("/sys/fs/cgroup/memory.current"))
    maximum = _read_cgroup_limit(Path("/sys/fs/cgroup/memory.max"))
    if current is not None and maximum is not None:
        return max(0, int((maximum - current) / (1024 * 1024)))

    # cgroup v1
    current = _read_int_file(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"))
    maximum = _read_cgroup_limit(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
    if current is not None and maximum is not None:
        return max(0, int((maximum - current) / (1024 * 1024)))
    return None


def _read_int_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_cgroup_limit(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    # Some runtimes expose an effectively unlimited sentinel near int64 max.
    if value <= 0 or value > 1 << 60:
        return None
    return value


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
