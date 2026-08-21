from __future__ import annotations

import signal
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.2)
        return connection.connect_ex((host, port)) != 0


def main() -> int:
    if not port_is_available("127.0.0.1", 8000):
        print(
            "Port 8000 is already in use. Stop the conflicting service before running "
            "`npm run local`, so Ask can reach the EagleEyes API.",
            file=sys.stderr,
        )
        return 1

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
