r"""path_resolver：GPT-SoVITS 根路径（gsv_root）统一自动探测（章节九十四）。

TTS 相关的绝对路径中，唯一需要检测/存储/刷新的是 `gsv_root` 单一根路径：
GPT/SoVITS 权重与参考音频一律由 gsv_root（或角色目录）在运行时推导，不另存绝对路径。

探测优先级（三级）：
  1. config 已存值且目录有效（含 api_v2.py）→ 直接使用
  2. 读 `logs/startup_report_*.jsonl`（go-llm-tts.bat 写入），提取已探测目录
  3. 只读同级扫描 上级目录\GPT-SoVITS*（含 api_v2.py）

本模块对 GPT-SoVITS 目录只读探测，不做任何文件创建/编辑/删除；不改动 go-llm-tts.bat。
"""

import json
from pathlib import Path

STARTUP_REPORT_GLOB = "startup_report_*.jsonl"
SIBLING_PATTERN = "GPT-SoVITS*"


def gsv_root_valid(root: str | Path) -> bool:
    """校验 gsv_root 是否有效：目录存在且包含 api_v2.py。"""
    if not root:
        return False
    p = Path(root)
    return p.is_dir() and (p / "api_v2.py").is_file()


def detect_from_startup_report(project_root: str | Path) -> str:
    """从启动报告 JSONL 提取 go-llm-tts.bat 已探测到的 GPT-SoVITS 目录。

    匹配步骤名含「GPT-SoVITS」且状态为 OK 的条目，取 detail 作为候选目录，
    通过有效性校验后返回（最新日期的报告优先）。
    """
    logs_dir = Path(project_root) / "logs"
    if not logs_dir.is_dir():
        return ""
    reports = sorted(
        logs_dir.glob(STARTUP_REPORT_GLOB),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for report in reports:
        try:
            for line in report.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                step = str(entry.get("step", "") or "")
                detail = str(entry.get("detail", "") or "").strip()
                if entry.get("status") == "OK" and "GPT-SoVITS" in step and detail:
                    if gsv_root_valid(detail):
                        return detail
        except (OSError, json.JSONDecodeError):
            continue
    return ""


def detect_from_siblings(project_root: str | Path) -> str:
    """只读扫描项目上级目录中 `GPT-SoVITS*` 文件夹（含 api_v2.py）。

    与 go-llm-tts.bat 的同级探测逻辑一致；多个候选时取最新修改的目录。
    """
    parent = Path(project_root).resolve().parent
    if not parent.is_dir():
        return ""
    candidates = [d for d in parent.glob(SIBLING_PATTERN) if d.is_dir() and gsv_root_valid(d)]
    if not candidates:
        return ""
    candidates.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return str(candidates[0])


def resolve_gsv_root(project_root: str | Path, configured: str = "") -> tuple[str, str]:
    """三级探测 gsv_root，返回 (路径或空串, 来源)。

    来源取值：`config`（配置已存且有效） / `startup_report` / `scan` / `""`（全部失败）。
    """
    if gsv_root_valid(configured):
        return str(configured), "config"
    found = detect_from_startup_report(project_root)
    if found:
        return found, "startup_report"
    found = detect_from_siblings(project_root)
    if found:
        return found, "scan"
    return "", ""
