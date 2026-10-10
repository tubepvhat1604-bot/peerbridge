import time
from threading import Lock
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < time.monotonic():
                self._items.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int = 30) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + ttl_seconds, value)

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in [item for item in self._items if item.startswith(prefix)]:
                self._items.pop(key, None)


cache = TTLCache()

