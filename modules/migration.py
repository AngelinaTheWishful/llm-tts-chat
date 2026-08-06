"""MigrationManager：数据迁移框架（章节四十九）。

- 启动时检测 data_version
- 按顺序执行 migrations/vX_Y_to_vX_Y.py 迁移脚本
- 迁移前自动备份，失败自动回滚
"""

import importlib.util
import shutil
from datetime import datetime
from pathlib import Path

from modules.base_manager import BaseManager


def _parse_version(name: str) -> tuple[str, str] | None:
    """从迁移脚本名 'v0.9_to_v1.0' 解析 (from, to)。"""
    parts = name.replace(".py", "").split("_to_")
    if len(parts) != 2:
        return None
    return parts[0].lstrip("v"), parts[1].lstrip("v")


def _version_key(ver: str) -> tuple[int, ...]:
    """版本号转数值元组用于数字排序（避免 '10.0' < '9.0' 的字典序问题）。"""
    return tuple(int(p) if p.isdigit() else 0 for p in ver.split("."))


class MigrationManager(BaseManager):
    """数据迁移执行器。"""

    def __init__(
        self,
        config_mgr,
        migrations_dir: str | Path,
        backup_dir: str | Path | None = None,
        data_dir: Path | None = None,
    ):
        super().__init__("migration")
        self.config_mgr = config_mgr
        self.migrations_dir = Path(migrations_dir)
        self.data_dir = data_dir or Path(".")
        self.backup_dir = Path(backup_dir) if backup_dir else Path("backup")

    def needs_migration(self) -> bool:
        return not self.config_mgr.check_data_version()

    def run(self) -> tuple[bool, str]:
        """执行所需迁移，返回 (是否成功, 描述)。"""
        current = self.config_mgr.get("data_version", "0.9")

        scripts = sorted(
            (f for f in self.migrations_dir.glob("v*_to_v*.py") if _parse_version(f.name)),
            key=lambda f: _version_key(_parse_version(f.name)[0]),
        )

        # 链式迁移：从当前版本出发，按 from_ver == 上一 to_ver 依次衔接
        applicable = []
        chain_ver = current
        for script in scripts:
            from_ver, to_ver = _parse_version(script.name)
            if from_ver == chain_ver:
                applicable.append((script, to_ver))
                chain_ver = to_ver

        if not applicable:
            target_version = getattr(self.config_mgr, "DATA_VERSION", "1.0")
            if current != target_version:
                self.log("warning", f"没有适用于 v{current} 的迁移脚本（目标 v{target_version}）")
            return True, "无需迁移"

        # 备份
        backup_path = self.backup_dir / f"pre_migration_{datetime.now():%Y%m%d_%H%M%S}"
        backup_path.mkdir(parents=True, exist_ok=True)
        self._backup(backup_path)
        self.log("info", f"迁移前备份完成: {backup_path}")

        # 顺序执行
        for script, to_ver in applicable:
            try:
                module = self._load_script(script)
                self.config_mgr._config = module.migrate(self.config_mgr._config, self.data_dir)
                self.config_mgr._config["data_version"] = to_ver
                self.config_mgr.save()
                self.log("info", f"迁移完成: {script.name} → v{to_ver}")
            except Exception as e:
                self.log("error", f"迁移失败 {script.name}: {e}")
                self._restore(backup_path)
                self.config_mgr.load()
                return False, f"迁移失败已回滚: {e}"

        return True, f"已迁移到 v{self.config_mgr.get('data_version', '?')}"

    def _load_script(self, path: Path):
        spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _backup(self, backup_path: Path) -> None:
        """Q12：备份 config.json + 数据目录（characters/conversations/memories），失败不阻断。"""
        config_path = self.config_mgr.path
        if config_path.exists():
            shutil.copy2(config_path, backup_path / "config.json")

        # 数据目录（迁移脚本可能改动角色/会话/记忆数据）
        data_root = self.data_dir if self.data_dir and self.data_dir != Path(".") else None
        for sub in ("characters", "conversations", "memories"):
            src = (data_root or Path(".")) / sub
            if src.exists():
                dst = backup_path / sub
                try:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                except OSError as e:
                    self.log("warning", f"迁移备份跳过目录 {sub}: {e}")

    def _restore(self, backup_path: Path) -> None:
        """Q12：从备份还原 config.json 与数据目录（回滚时使用）。"""
        config_backup = backup_path / "config.json"
        if config_backup.exists():
            shutil.copy2(config_backup, self.config_mgr.path)
        data_root = self.data_dir if self.data_dir and self.data_dir != Path(".") else None
        for sub in ("characters", "conversations", "memories"):
            src = backup_path / sub
            if src.exists():
                dst = (data_root or Path(".")) / sub
                try:
                    if dst.exists():
                        shutil.rmtree(str(dst), ignore_errors=True)
                    shutil.copytree(src, dst)
                except OSError as e:
                    self.log("warning", f"迁移回滚失败 {sub}: {e}")
