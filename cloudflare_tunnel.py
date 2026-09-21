"""Maintain a free Cloudflare Quick Tunnel and publish its HTTPS URL."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
URL_PATH = BASE_DIR / "data" / "tunnel-url.txt"
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def update_env(url: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    replacement = f"DASHBOARD_URL={url}"
    updated = []
    replaced = False
    for line in lines:
        if line.startswith("DASHBOARD_URL="):
            updated.append(replacement)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(replacement)
    temp_path = ENV_PATH.with_suffix(".tmp")
    temp_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(ENV_PATH)


def main() -> int:
    URL_PATH.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--url",
            "http://127.0.0.1:8000",
        ],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    announced = ""
    for line in process.stdout:
        print(line, end="", flush=True)
        match = URL_PATTERN.search(line)
        if not match or match.group(0) == announced:
            continue
        announced = match.group(0)
        update_env(announced)
        URL_PATH.write_text(announced + "\n", encoding="utf-8")
        print(f"[tunnel] HTTPS dashboard: {announced}", flush=True)
        subprocess.run(
            ["pm2", "restart", "stock-bot", "--update-env"],
            cwd=BASE_DIR,
            check=False,
        )
    return process.wait()


if __name__ == "__main__":
    sys.exit(main())
