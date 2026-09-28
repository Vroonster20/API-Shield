"""Start the three local demo processes; Ctrl+C stops the entire group."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if not (ROOT / "dist" / "index.html").is_file():
        print("Build the control panel first: npm run build", file=sys.stderr)
        return 1
    missing = [key for key in ("SHIELD_REGISTRY_FILE", "SHIELD_ADMIN_ORIGIN") if not os.environ.get(key)]
    if missing:
        print("Set the environment variables in README.md first: " + ", ".join(missing), file=sys.stderr)
        return 1
    processes: list[subprocess.Popen] = []
    try:
        for module, port in (("demo", 9000), ("main", 8081), ("gateway", 8080)):
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                f"{module}:app",
                "--app-dir",
                str(ROOT / "backend"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--workers",
                "1",
                "--no-proxy-headers",
                "--no-access-log",
                "--log-level",
                "warning",
            ]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            processes.append(subprocess.Popen(command, cwd=ROOT, creationflags=flags))
        print("Admin: http://admin.localhost:8081  Demo: http://api.localhost:8080", flush=True)
        print(
            "Use the hosts-file instructions if those hostnames do not resolve. Ctrl+C stops all services.",
            flush=True,
        )
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        print("A service stopped. Check migration/configuration and the messages above.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
