"""reporter 报告系统单元测试（章节九十，文本 + JSONL 双份 + 按天清理）。"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.reporter as reporter  # noqa: E402


@pytest.fixture
def repdir(tmp_path, monkeypatch):
    monkeypatch.setattr(reporter, "LOG_DIR", tmp_path)
    return tmp_path


def test_write_entry_creates_both_files(repdir):
    reporter.write_entry("run_report", "步骤A", "OK", detail="耗时1s", code="")
    txt = list(repdir.glob("run_report_*.txt"))
    jsonl = list(repdir.glob("run_report_*.jsonl"))
    assert txt and jsonl
    assert "步骤A" in txt[0].read_text(encoding="utf-8")
    entry = json.loads(jsonl[0].read_text(encoding="utf-8"))
    assert entry["report"] == "run_report"
    assert entry["step"] == "步骤A"
    assert entry["status"] == "OK"
    assert entry["code"] == ""


def test_write_entry_with_code(repdir):
    reporter.write_entry("run_report", "LLM 调用", "FAIL", code="LLM-004", detail="x")
    txt = list(repdir.glob("run_report_*.txt"))[0].read_text(encoding="utf-8")
    assert "[LLM-004]" in txt
    entry = json.loads(list(repdir.glob("run_report_*.jsonl"))[0].read_text(encoding="utf-8"))
    assert entry["code"] == "LLM-004"


def test_read_report_returns_entries(repdir):
    reporter.write_entry("run_report", "a", "OK")
    reporter.write_entry("run_report", "b", "FAIL", code="TTS-003")
    entries = reporter.read_report("run_report")
    assert [e["step"] for e in entries] == ["a", "b"]
    assert entries[-1]["code"] == "TTS-003"


def test_cleanup_removes_old_reports(repdir):
    today = datetime.now().strftime("%Y%m%d")
    old = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
    old_ts = (datetime.now() - timedelta(days=10)).timestamp()
    for ext in (".txt", ".jsonl"):
        p = repdir / f"run_report_{old}{ext}"
        p.write_text("old", encoding="utf-8")
        os.utime(p, (old_ts, old_ts))
    fresh = repdir / f"run_report_{today}.txt"
    fresh.write_text("new", encoding="utf-8")
    reporter._cleanup()
    assert not (repdir / f"run_report_{old}.txt").exists()
    assert not (repdir / f"run_report_{old}.jsonl").exists()
    assert fresh.exists()


def test_cli_entrypoint(repdir):
    rc = reporter._cli(["run_report", "WARN", "TTS 合成", "--code", "TTS-003", "--detail", "超时"])
    assert rc == 0
    entry = json.loads(list(repdir.glob("run_report_*.jsonl"))[0].read_text(encoding="utf-8"))
    assert entry["code"] == "TTS-003"
    assert entry["status"] == "WARN"
    assert entry["step"] == "TTS 合成"
