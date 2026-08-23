from __future__ import annotations

import os
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
import psycopg

from .operational_monitoring import record_metric, structured_log


_lock = threading.Lock()
_requests: dict[str, deque[float]] = defaultdict(deque)


def _identity(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


async def production_guard(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    request.state.request_id = request_id
    request.state.request_started_monotonic = started
    request.state.request_started_at = time.time()
    max_body = int(os.getenv("MAX_REQUEST_BYTES", "1048576"))
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_body:
        return JSONResponse({"detail": "Request body is too large", "request_id": request_id}, status_code=413)
    if request.method != "OPTIONS" and request.url.path not in {"/api/health", "/api/health/readiness"}:
        limit = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "240"))
        key = f"{_identity(request)}:{request.url.path.split('/', 3)[:3]}"
        now = time.monotonic()
        with _lock:
            bucket = _requests[key]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                record_metric("api.rate_limited", tags={"path": request.url.path})
                return JSONResponse({"detail": "Too many requests; retry shortly", "request_id": request_id}, status_code=429, headers={"Retry-After": "60"})
            bucket.append(now)
    try:
        response = await call_next(request)
    except (psycopg.OperationalError, psycopg.errors.QueryCanceled, TimeoutError) as exc:
        duration = round((time.perf_counter() - started) * 1000, 2)
        record_metric("api.dependency_timeout", duration, tags={"path": request.url.path, "error_type": type(exc).__name__}, persist=True)
        structured_log("dependency_unavailable", request_id=request_id, method=request.method, path=request.url.path, error_type=type(exc).__name__)
        return JSONResponse(
            {"detail": "A data service is temporarily unavailable. Retry shortly.", "request_id": request_id},
            status_code=503,
            headers={"Retry-After": "2", "Cache-Control": "no-store"},
        )
    except Exception:
        record_metric("api.unhandled_error", tags={"path": request.url.path}, persist=True)
        structured_log("request_failed", request_id=request_id, method=request.method, path=request.url.path)
        raise
    duration = round((time.perf_counter() - started) * 1000, 2)
    route_group = request.url.path.split("/")[2] if request.url.path.startswith("/api/") and len(request.url.path.split("/")) > 2 else "other"
    record_metric("api.latency_ms", duration, tags={"group": route_group, "status": response.status_code})
    if response.status_code in {401, 403, 404}:
        record_metric("access.boundary_failure", tags={"status": response.status_code, "group": route_group})
    response.headers["X-Request-ID"] = request_id
    response.headers["Server-Timing"] = f'app;dur={duration}'
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    cacheable = request.method == "GET" and request.url.path.startswith(("/api/home", "/api/research", "/api/scenarios"))
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=30" if cacheable and response.status_code == 200 else "no-store"
    structured_log("request_complete", request_id=request_id, method=request.method, path=request.url.path, status=response.status_code, duration_ms=duration)
    return response
