from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
    )
    web = subprocess.Popen(["npm", "run", "dev"], cwd=ROOT)
    processes = [api, web]

    def stop(*_: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while all(process.poll() is None for process in processes):
            for process in processes:
                try:
                    process.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    return next((process.returncode or 0 for process in processes if process.returncode), 0)


if __name__ == "__main__":
    raise SystemExit(main())
