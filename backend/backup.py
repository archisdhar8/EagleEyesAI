from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from .database import DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a recoverable EagleEyes database backup")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--execute", action="store_true", help="Required before any backup is written")
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    mode = "postgres" if os.getenv("DATABASE_URL") else "sqlite"
    if not args.execute:
        print(f"dry-run mode={mode} destination={destination} timestamp={stamp}")
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    if mode == "postgres":
        target = destination / f"eagleeyes-{stamp}.dump"
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(target), os.environ["DATABASE_URL"]], check=True)
    else:
        target = destination / f"eagleeyes-{stamp}.sqlite3"
        shutil.copy2(DB_PATH.resolve(), target)
    print(f"backup_created={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
