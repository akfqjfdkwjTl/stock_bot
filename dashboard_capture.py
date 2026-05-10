"""추천 대시보드용 JSON 생성과 웹페이지 캡처를 담당합니다."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
from contextlib import closing
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from config import SETTINGS
from market_data import build_market_payload


EDGE_CANDIDATES = (
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def _find_edge_executable() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Microsoft Edge 실행 파일을 찾지 못했습니다.")


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def save_dashboard_data(
    mode: str,
    generated_at: str,
    grade_a_items: list[dict[str, Any]],
    watch_items: list[dict[str, Any]],
) -> Path:
    """웹페이지가 읽을 추천 결과 JSON을 저장합니다."""
    payload = {
        "mode": mode,
        "generated_at": generated_at,
        "grade_a": grade_a_items,
        "watch": watch_items,
        "sector_rule": "같은 섹터 중복 제거 적용",
    }
    output_path = Path(SETTINGS.dashboard_json_path)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def refresh_market_json() -> Path:
    """시장 지표 JSON을 갱신합니다."""
    payload = build_market_payload()
    output_path = Path(SETTINGS.market_json_path)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def capture_dashboard(output_path: str | None = None) -> Path:
    """index.html을 렌더링해 스크린샷을 저장합니다."""
    output = Path(output_path or SETTINGS.dashboard_capture_path)
    edge_path = _find_edge_executable()
    port = _find_free_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(Path.cwd()))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        target_url = f"http://127.0.0.1:{port}/index.html?ts={int(datetime.now().timestamp())}"
        command = [
            str(edge_path),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=5000",
            "--window-size=1440,2400",
            f"--screenshot={output.resolve()}",
            target_url,
        ]
        subprocess.run(command, check=True, timeout=30)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    if not output.exists():
        raise FileNotFoundError(f"캡처 파일이 생성되지 않았습니다: {output}")
    return output
