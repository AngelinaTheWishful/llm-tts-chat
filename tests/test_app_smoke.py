"""CI 冒烟测试：启动 app 校验 HTTP 200 与关键端点（不依赖 GPT-SoVITS/真实 LLM）。

- 运行于临时副本目录，不污染真实数据
- 用法：venv\\Scripts\\python.exe -m pytest tests/test_app_smoke.py -q
"""

import shutil
import socket
import subprocess
import time
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parent.parent
VENV_PY = PROJECT / "venv" / "Scripts" / "python.exe"

COPY_DIRS = ["modules", "locales", "migrations", "characters"]
COPY_FILES = ["app.py", "theme_config.json", "config.example.json"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_workdir(tmp_path: Path) -> Path:
    work = tmp_path / "app"
    work.mkdir()
    for d in COPY_DIRS:
        shutil.copytree(PROJECT / d, work / d)
    for f in COPY_FILES:
        shutil.copy2(PROJECT / f, work / f)
    for d in ("conversations", "logs", "temp_audio", "trash"):
        (work / d).mkdir()
    return work


def test_app_starts_and_serves(tmp_path):
    work = _make_workdir(tmp_path)
    port = _free_port()
    py = VENV_PY if VENV_PY.exists() else "python"
    proc = subprocess.Popen(
        [str(py), "app.py", "--port", str(port)],
        cwd=str(work),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        base = f"http://127.0.0.1:{port}"
        up = False
        for _ in range(40):
            try:
                if requests.get(base, timeout=3).status_code == 200:
                    up = True
                    break
            except Exception:
                pass
            time.sleep(1)
        assert up, "app 未在预期时间内返回 HTTP 200"

        info = requests.get(f"{base}/info", timeout=10).json()
        named = info.get("named_endpoints") or {}
        for key in ("/send_message_handler", "/save_settings_handler", "/export_session_handler"):
            assert f"/{key.lstrip('/')}" in named or key in named
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
