"""按次运行报告：startup_report（一键启动）+ run_report（发送消息步骤）（章节九十）。

- 文本 + JSONL 双份：logs/<name>_YYYYMMDD.txt 人类可读，同前缀 .jsonl 机器可解析
- 按天保留 KEEP_DAYS 天（自动清理过期报告）
- CLI 入口见 modules/report_cli.py（供 go-llm-tts.bat 一键启动脚本调用）
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

KEEP_DAYS = 7
REPORTS = ("startup_report", "run_report")

_lock = threading.Lock()
# Q13：清理节流——每小时最多执行一次，避免每次写入都全目录扫描
_last_cleanup_ts: float = 0.0


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _paths(report: str) -> tuple[Path, Path]:
    base = LOG_DIR / f"{report}_{_today()}"
    return base.with_suffix(".txt"), base.with_suffix(".jsonl")


def _cleanup(force: bool = False) -> None:
    """删除超过 KEEP_DAYS 天的报告文件（txt/jsonl），默认每小时至多执行一次（Q13）。"""
    global _last_cleanup_ts
    now_ts = datetime.now().timestamp()
    if not force and (now_ts - _last_cleanup_ts) < 3600:
        return
    _last_cleanup_ts = now_ts
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).timestamp()
    try:
        for f in LOG_DIR.glob("*.txt"):
            if f.name.startswith(REPORTS) and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        for f in LOG_DIR.glob("*.jsonl"):
            if f.name.startswith(REPORTS) and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def write_entry(report: str, step: str, status: str, detail: str = "", code: str = "") -> None:
    """追加一条报告步骤（文本 + JSONL 双份，线程安全）。

    Args:
        report: 报告名（startup_report / run_report）
        step: 步骤描述
        status: 状态（INFO / OK / WARN / FAIL）
        detail: 补充信息（可含耗时、错误详情）
        code: 错误码（失败时如 LLM-001）
    """
    if report not in REPORTS:
        report = REPORTS[1]
    status = (status or "INFO").upper()
    ts = _now()
    line_txt = f"[{ts}] [{status}] {step}" + (f" | {detail}" if detail else "")
    if code:
        line_txt += f" | [{code}]"
    entry = {
        "report": report,
        "time": ts,
        "step": step,
        "status": status,
        "detail": detail,
        "code": code,
    }
    with _lock:
        txt_path, json_path = _paths(report)
        try:
            with open(txt_path, "a", encoding="utf-8") as f:
                f.write(line_txt + "\n")
            with open(json_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:  # noqa: BLE001
            import sys

            print(f"[reporter] 报告写入失败: {e}", file=sys.stderr)
    _cleanup()


def read_report(report: str, date: str | None = None) -> list[dict]:
    """读取指定日期（YYYYMMDD，缺省今日）的报告 JSON 条目。"""
    date = date or _today()
    json_path = LOG_DIR / f"{report}_{date}.jsonl"
    entries = []
    if not json_path.exists():
        return entries
    try:
        for line in json_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return entries


def _cli(argv: list[str]) -> int:
    """CLI：python -m modules.report_cli <report> <status> <step> [--detail ...] [--code ...]"""
    if len(argv) < 3:
        import sys

        print(
            "用法: python -m modules.report_cli <report> <status> <step> "
            "[--detail ...] [--code ...]",
            file=sys.stderr,
        )
        return 2
    report, status, step = argv[0], argv[1], argv[2]
    detail = ""
    code = ""
    if "--detail" in argv:
        i = argv.index("--detail")
        if i + 1 < len(argv):
            detail = argv[i + 1]
    if "--code" in argv:
        i = argv.index("--code")
        if i + 1 < len(argv):
            code = argv[i + 1]
    write_entry(report, step, status, detail, code)
    return 0
