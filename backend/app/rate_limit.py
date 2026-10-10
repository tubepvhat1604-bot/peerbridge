from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.limit = max(1, requests_per_minute)
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        authorization = request.headers.get("authorization", "")
        identity = authorization[-24:] if authorization else client
        key = f"{identity}:{request.url.path.split('/')[3:5]}"
        now = monotonic()
        with self.lock:
            bucket = self.requests[key]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            limit = min(self.limit, 10) if request.url.path.startswith("/api/v1/auth/") else self.limit
            if len(bucket) >= limit:
                retry_after = max(1, int(60 - (now - bucket[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Bạn thao tác quá nhanh. Vui lòng thử lại sau."},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)
        return await call_next(request)
