from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import database


RETENTION_VERSION = "database-retention-v1"
DEFAULT_ARCHIVE_ROOT = database.APP_DIR / "data" / "archives"


def retention_report() -> dict[str, Any]:
    """Report safely removable/cache data without changing the database."""
    if not database.DATABASE_URL:
        return {"version": RETENTION_VERSION, "storage": "sqlite", "candidates": {}}
    with database.postgres_connection() as conn:
        row = conn.execute(
            """SELECT
            (SELECT count(*) FROM public.dashboard_widget_cache WHERE expires_at < now()) AS expired_widget_cache,
            (SELECT count(*) FROM public.briefing_snapshots WHERE created_at < now()-interval '180 days') AS old_briefings,
            (SELECT count(*) FROM public.price_bars older
              WHERE older.ts < now()-interval '2 years'
              AND EXISTS (
                SELECT 1 FROM public.price_bars preferred
                WHERE preferred.security_id=older.security_id
                  AND preferred.interval=older.interval AND preferred.ts=older.ts
                  AND preferred.provider='tiingo' AND older.provider<>'tiingo'
              )) AS overlapping_price_bars,
            pg_database_size(current_database()) AS database_bytes"""
        ).fetchone()
    return {
        "version": RETENTION_VERSION, "storage": "supabase",
        "database_bytes": int(row["database_bytes"]),
        "candidates": {
            "expired_widget_cache": int(row["expired_widget_cache"]),
            "old_briefings": int(row["old_briefings"]),
            "overlapping_price_bars": int(row["overlapping_price_bars"]),
        },
        "preserved": [
            "All ALFRED point-in-time macro vintages",
            "All immutable dashboard and validation runs",
            "All canonical Tiingo adjusted-price observations",
            "All user portfolios, goals, policies, conversations, and saved layouts",
        ],
    }


def archive_and_prune(archive_root: Path = DEFAULT_ARCHIVE_ROOT, execute: bool = False) -> dict[str, Any]:
    report = retention_report()
    if not execute or not database.DATABASE_URL:
        return {**report, "executed": False}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = archive_root.resolve() / stamp
    target.mkdir(parents=True, exist_ok=False)
    with database.postgres_connection() as conn:
        rows = conn.execute(
            """SELECT older.id,s.ticker,older.provider,older.interval,older.ts,
              older.open,older.high,older.low,older.close,older.adjusted_close,
              older.volume,older.vwap,older.transactions,older.fetched_at
            FROM public.price_bars older
            JOIN public.securities s ON s.id=older.security_id
            WHERE older.ts < now()-interval '2 years'
              AND EXISTS (
                SELECT 1 FROM public.price_bars preferred
                WHERE preferred.security_id=older.security_id
                  AND preferred.interval=older.interval AND preferred.ts=older.ts
                  AND preferred.provider='tiingo' AND older.provider<>'tiingo'
              ) ORDER BY older.id"""
        ).fetchall()
        frame = pd.DataFrame([dict(row) for row in rows])
        archive_file = target / "overlapping_price_bars.parquet"
        frame.to_parquet(archive_file, compression="zstd", index=False)
        digest = hashlib.sha256(archive_file.read_bytes()).hexdigest()
        manifest = {
            "version": RETENTION_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "archive": archive_file.name, "rows": len(frame), "sha256": digest,
            "policy": "Non-Tiingo price rows older than two years only when a same-session Tiingo adjusted row exists.",
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2))
        if len(frame):
            conn.execute("DELETE FROM public.price_bars WHERE id=ANY(%s)", (frame["id"].astype(int).tolist(),))
        expired = conn.execute("DELETE FROM public.dashboard_widget_cache WHERE expires_at < now()").rowcount
        briefings = conn.execute("DELETE FROM public.briefing_snapshots WHERE created_at < now()-interval '180 days'").rowcount
    return {
        **report, "executed": True, "archive_directory": str(target),
        "archived_price_bars": len(frame), "expired_widget_cache_deleted": expired,
        "old_briefings_deleted": briefings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive redundant EagleEyes history before bounded retention")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--execute", action="store_true", help="Write a verified zstd Parquet archive and prune only archived/cache rows")
    args = parser.parse_args()
    print(json.dumps(archive_and_prune(args.archive_dir, args.execute), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
