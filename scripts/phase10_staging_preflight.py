#!/usr/bin/env python3
"""Fail-closed preflight for an EagleEyes staging release.

This command never connects to a database or API and never prints secret
values. It is intentionally stricter than the application runtime: a release
operator must name the exact revision and staging target before any mutation.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "STAGING_API_URL",
    "STAGING_FRONTEND_URL",
    "STAGING_DATABASE_URL",
    "STAGING_SUPABASE_URL",
    "STAGING_SUPABASE_PUBLISHABLE_KEY",
    "STAGING_USER_A_TOKEN",
    "STAGING_USER_B_TOKEN",
    "STAGING_CORS_ALLOWED_ORIGINS",
    "STAGING_ALERT_DESTINATION",
    "SENTRY_DSN",
    "EXPECTED_GIT_REVISION",
    "STAGING_TARGET_ID",
)
CONFIRMATION = "EAGLEEYES_STAGING_ONLY"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value and "your-" not in value.lower() and "example" not in value.lower())


def _https(name: str) -> bool:
    return urlparse(os.getenv(name, "")).scheme == "https"


def main() -> int:
    revision = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    checks: dict[str, bool] = {f"configured:{name}": _configured(name) for name in REQUIRED}
    checks.update({
        "confirmation": os.getenv("STAGING_RELEASE_CONFIRMATION") == CONFIRMATION,
        "clean_worktree": not dirty,
        "expected_revision_matches": os.getenv("EXPECTED_GIT_REVISION", "").strip() == revision,
        "distinct_user_tokens": bool(
            os.getenv("STAGING_USER_A_TOKEN")
            and os.getenv("STAGING_USER_B_TOKEN")
            and os.getenv("STAGING_USER_A_TOKEN") != os.getenv("STAGING_USER_B_TOKEN")
        ),
        "https_api": _https("STAGING_API_URL"),
        "https_frontend": _https("STAGING_FRONTEND_URL"),
        "https_supabase": _https("STAGING_SUPABASE_URL"),
        "database_not_production": bool(
            os.getenv("STAGING_DATABASE_URL")
            and (
                not os.getenv("PRODUCTION_DATABASE_URL")
                or os.getenv("STAGING_DATABASE_URL") != os.getenv("PRODUCTION_DATABASE_URL")
            )
        ),
        "api_not_production": bool(
            os.getenv("STAGING_API_URL")
            and (
                not os.getenv("PRODUCTION_API_URL")
                or os.getenv("STAGING_API_URL").rstrip("/") != os.getenv("PRODUCTION_API_URL").rstrip("/")
            )
        ),
    })
    failed = sorted(name for name, passed in checks.items() if not passed)
    print(json.dumps({
        "version": "phase10-staging-preflight-v1",
        "ready": not failed,
        "revision": revision,
        "dirty": dirty,
        "checks": checks,
        "failed_checks": failed,
        "secrets_printed": False,
    }, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
