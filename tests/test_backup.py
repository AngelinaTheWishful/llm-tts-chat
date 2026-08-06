"""BackupManager 单元测试（Q8 / 章节九十一 自动备份）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.backup import BackupManager


def _make_project(tmp_path) -> Path:
    root = tmp_path / "proj"
    (root / "conversations").mkdir(parents=True)
    (root / "characters" / "角色A").mkdir(parents=True)
    (root / "memories").mkdir(parents=True)
    (root / "conversations" / "sess1" / "audio").mkdir(parents=True)
    (root / "conversations" / "sess1" / "messages.json").write_text(
        json.dumps([{"role": "user", "content": "hi"}]), encoding="utf-8"
    )
    (root / "conversations" / "sess1" / "audio" / "msg_0.wav").write_bytes(b"WAV")
    (root / "characters" / "角色A" / "character.json").write_text(
        json.dumps({"name": "角色A"}), encoding="utf-8"
    )
    (root / "config.json").write_text(json.dumps({"data_version": "1.0"}), encoding="utf-8")
    return root


def test_backup_now_copies_dirs(tmp_path):
    root = _make_project(tmp_path)
    mgr = BackupManager(root, backup_root=tmp_path / "backup", keep_count=2)
    dest = Path(mgr.backup_now())

    assert (dest / "conversations" / "sess1" / "messages.json").exists()
    # 音频跳过（.wav 默认排除，避免重复占用磁盘）
    assert not (dest / "conversations" / "sess1" / "audio" / "msg_0.wav").exists()
    assert (dest / "characters" / "角色A" / "character.json").exists()
    assert (dest / "config.json").exists()
    assert mgr.list_backups()[0]["name"].startswith("backup_")


def test_backup_keeps_only_keep_count(tmp_path):
    root = _make_project(tmp_path)
    mgr = BackupManager(root, backup_root=tmp_path / "backup", keep_count=2)
    mgr.backup_now()
    mgr.backup_now()
    mgr.backup_now()
    assert len(mgr.list_backups()) == 2


def test_backup_skip_missing_dir(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    mgr = BackupManager(root, backup_root=tmp_path / "backup", keep_count=2)
    dest = Path(mgr.backup_now())
    assert dest.exists()  # 缺目录也不抛错
