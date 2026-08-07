"""path_resolver 单元测试（章节九十四：gsv_root 统一自动探测）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import path_resolver
from modules.config_manager import ConfigManager


def _make_gsv(root: Path, name: str = "GPT-SoVITS-v2pro-test") -> Path:
    gsv = root / name
    gsv.mkdir(parents=True, exist_ok=True)
    (gsv / "api_v2.py").write_text("", encoding="utf-8")
    return gsv


def _project(tmp_path: Path, logs: bool = False) -> Path:
    """构造项目根（含可选 logs 目录），其父目录即同级扫描范围。"""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    if logs:
        (project / "logs").mkdir(exist_ok=True)
    return project


def test_gsv_root_valid(tmp_path):
    gsv = _make_gsv(tmp_path)
    assert path_resolver.gsv_root_valid(gsv) is True
    assert path_resolver.gsv_root_valid(tmp_path) is False  # 无 api_v2.py
    assert path_resolver.gsv_root_valid("") is False
    assert path_resolver.gsv_root_valid(tmp_path / "不存在") is False


def test_resolve_config_valid_first(tmp_path):
    gsv = _make_gsv(tmp_path)
    project = _project(tmp_path)
    path, source = path_resolver.resolve_gsv_root(project, configured=str(gsv))
    assert source == "config"
    assert path == str(gsv)


def test_resolve_invalid_config_ignored(tmp_path):
    # config 指向无效路径 → 走第二/三级（此处无报告、无同级）→ 失败
    project = _project(tmp_path)
    bad = tmp_path / "bad" / "gsv"
    path, source = path_resolver.resolve_gsv_root(project, configured=str(bad))
    assert path == ""
    assert source == ""


def test_resolve_from_startup_report(tmp_path):
    gsv = _make_gsv(tmp_path)  # 作为 project 的同级目录
    project = _project(tmp_path, logs=True)
    entry = {
        "report": "startup_report",
        "time": "2026-08-07 12:00:00",
        "step": "探测 GPT-SoVITS 目录",
        "status": "OK",
        "detail": str(gsv),
        "code": "",
    }
    (project / "logs" / "startup_report_20260807.jsonl").write_text(
        json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    path, source = path_resolver.resolve_gsv_root(project, configured="")
    assert source == "startup_report"
    assert path == str(gsv)


def test_resolve_from_siblings(tmp_path):
    gsv = _make_gsv(tmp_path)
    project = _project(tmp_path)
    path, source = path_resolver.resolve_gsv_root(project, configured="")
    assert source == "scan"
    assert path == str(gsv)


def test_resolve_all_fail(tmp_path):
    project = _project(tmp_path)
    path, source = path_resolver.resolve_gsv_root(project, configured="")
    assert path == ""
    assert source == ""


def test_config_write_back_on_resolve(tmp_path):
    gsv = _make_gsv(tmp_path)
    project = _project(tmp_path)
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(cfg_path)
    mgr.set_top_level("gsv_root", "")
    path, source = mgr.resolve_gsv_root(project_root=project, write_back=True)
    assert source == "scan"
    assert path == str(gsv)
    loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert loaded["gsv_root"] == str(gsv)


def test_config_resolve_no_writeback_when_config_valid(tmp_path):
    gsv = _make_gsv(tmp_path)
    project = _project(tmp_path)
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(cfg_path)
    mgr.set_top_level("gsv_root", str(gsv))
    path, source = mgr.resolve_gsv_root(project_root=project, write_back=True)
    assert source == "config"
    assert path == str(gsv)


def test_config_resolve_fail_keeps_old_value(tmp_path):
    project = _project(tmp_path)
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(cfg_path)
    mgr.set_top_level("gsv_root", "C:/旧值/不存在的路径")
    path, source = mgr.resolve_gsv_root(project_root=project, write_back=True)
    assert path == ""
    assert source == ""
    loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert loaded["gsv_root"] == "C:/旧值/不存在的路径"  # 保留旧值


def test_effective_gsv_root_linkage(tmp_path):
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(cfg_path)
    mgr.set_top_level("gsv_root", "C:/mock/gsv/main")
    # 训练未填 → 继承主 gsv_root
    assert mgr.get_effective_gsv_root() == "C:/mock/gsv/main"
    # 训练已填 → 用训练值
    mgr.update("gsv_training", "gsv_root", "C:/mock/gsv/train")
    assert mgr.get_effective_gsv_root() == "C:/mock/gsv/train"
    # 训练清空 → 回退主 gsv_root
    mgr.update("gsv_training", "gsv_root", "")
    assert mgr.get_effective_gsv_root() == "C:/mock/gsv/main"
