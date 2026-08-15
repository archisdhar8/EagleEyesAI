from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException
from dotenv import load_dotenv

from .database import ENV_PATH


load_dotenv(ENV_PATH, override=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None


def require_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    """Validate the Supabase access token without exposing a service key to the browser."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in is required")
    token = authorization.split(" ", 1)[1].strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", token):
        raise HTTPException(status_code=401, detail="Your session is invalid")
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
            timeout=8,
        )
        status_code = response.status_code
        payload = response.json()
    except httpx.HTTPError:
        # Some local macOS/sandbox combinations block Python DNS while the
        # system TLS client remains available. Feed credentials over stdin so
        # the access token never appears in process arguments.
        config = "\n".join([
            f'url = "{supabase_url}/auth/v1/user"',
            f'header = "Authorization: Bearer {token}"',
            f'header = "apikey: {api_key}"',
            'silent', 'show-error', 'max-time = 8', 'write-out = "\\n%{http_code}"',
        ])
        try:
            result = subprocess.run(
                ["curl", "--config", "-"], input=config, capture_output=True,
                text=True, timeout=10, check=False,
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
    return AuthenticatedUser(id=str(payload["id"]), email=payload.get("email"))
