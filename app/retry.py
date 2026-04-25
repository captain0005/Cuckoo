from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def retry_with_backoff(
    func: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Run a callable with bounded exponential backoff."""

    last_exception: Exception | None = None
    attempts = max(1, max_retries)
    for attempt in range(attempts):
        try:
            return func()
        except retry_exceptions as exc:
            last_exception = exc
            if attempt >= attempts - 1:
                break
            time.sleep(base_delay * (2**attempt))
    assert last_exception is not None
    raise last_exception
