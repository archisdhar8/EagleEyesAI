from __future__ import annotations

import os
import json
import re
import subprocess
import time
import base64
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException, Request
from dotenv import load_dotenv

from .database import ENV_PATH


load_dotenv(ENV_PATH, override=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None


_AUTH_CACHE_LOCK = threading.Lock()
_AUTH_CACHE: OrderedDict[str, tuple[float, AuthenticatedUser]] = OrderedDict()


def _token_cache_ttl(token: str) -> float:
    """Bound reuse of an already remotely verified token by both policy and JWT expiry."""
    configured = max(0.0, min(30.0, float(os.getenv("AUTH_VERIFIED_TOKEN_CACHE_SECONDS", "15"))))
    try:
        payload_segment = token.split(".")[1]
        payload_segment += "=" * (-len(payload_segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_segment.encode()))
        configured = min(configured, max(0.0, float(claims.get("exp", 0)) - time.time() - 2.0))
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return configured


def _cached_verified_user(token: str) -> AuthenticatedUser | None:
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    with _AUTH_CACHE_LOCK:
        cached = _AUTH_CACHE.get(key)
        if not cached or cached[0] <= now:
            _AUTH_CACHE.pop(key, None)
            return None
        _AUTH_CACHE.move_to_end(key)
        return cached[1]


def _cache_verified_user(token: str, user: AuthenticatedUser) -> None:
    ttl = _token_cache_ttl(token)
    if ttl <= 0:
        return
    key = hashlib.sha256(token.encode()).hexdigest()
    with _AUTH_CACHE_LOCK:
        _AUTH_CACHE[key] = (time.monotonic() + ttl, user)
        _AUTH_CACHE.move_to_end(key)
        while len(_AUTH_CACHE) > 256:
            _AUTH_CACHE.popitem(last=False)


def require_user(authorization: str | None = Header(default=None), request: Request = None) -> AuthenticatedUser:
    """Validate the Supabase access token without exposing a service key to the browser."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in is required")
    token = authorization.split(" ", 1)[1].strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", token):
        raise HTTPException(status_code=401, detail="Your session is invalid")
    auth_started = time.monotonic()
    cached_user = _cached_verified_user(token)
    if cached_user is not None:
        if request is not None:
            request.state.auth_latency_ms = round((time.monotonic() - auth_started) * 1000, 2)
            request.state.auth_cache_hit = True
        return cached_user
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    api_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    if not supabase_url or not api_key:
        raise HTTPException(status_code=503, detail="Supabase authentication is not configured on the API")
    payload = None
    status_code = 503
    try:
        response = httpx.get(
            f"{supabase_url}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": api_key},
            timeout=4,
        )
        status_code = response.status_code
        payload = response.json()
    except httpx.HTTPError:
        if os.getenv("APP_ENV", "development").strip().lower() == "production":
            raise HTTPException(status_code=503, detail="Authentication service is unavailable")
        # Some local macOS/sandbox combinations block Python DNS while the
        # system TLS client remains available. Feed credentials over stdin so
        # the access token never appears in process arguments.
        remaining = max(0.5, 8.0 - (time.monotonic() - auth_started))
        config = "\n".join([
            f'url = "{supabase_url}/auth/v1/user"',
            f'header = "Authorization: Bearer {token}"',
            f'header = "apikey: {api_key}"',
            'silent', 'show-error', f'max-time = {remaining:.2f}', 'write-out = "\\n%{http_code}"',
        ])
        try:
            result = subprocess.run(
                ["curl", "--config", "-"], input=config, capture_output=True,
                text=True, timeout=remaining + 0.5, check=False,
            )
            body, _, code = result.stdout.rpartition("\n")
            status_code = int(code) if code.isdigit() else 503
            payload = json.loads(body) if body else None
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            payload = None
    if status_code != 200:
        if status_code == 503:
            raise HTTPException(status_code=503, detail="Authentication service is unavailable")
        raise HTTPException(status_code=401, detail="Your session is invalid or expired")
    if not payload or not payload.get("id"):
        raise HTTPException(status_code=401, detail="Your session is invalid")
    if request is not None:
        request.state.auth_latency_ms = round((time.monotonic() - auth_started) * 1000, 2)
        request.state.auth_cache_hit = False
    user = AuthenticatedUser(id=str(payload["id"]), email=payload.get("email"))
    _cache_verified_user(token, user)
    return user


def optional_user(authorization: str | None = Header(default=None), request: Request = None) -> AuthenticatedUser | None:
    """Return no user for public endpoints, but fully validate any supplied session."""
    if not authorization:
        return None
    return require_user(authorization, request)
