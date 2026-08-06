"""自动备份（Q8 / 章节九十一）：定期备份用户数据到 backup/。

备份内容：
- conversations/（会话 messages.json + summary，音频 .wav 默认跳过以节省空间）
- characters/（角色配置 + 头像，跳过运行时注入文件）
- config.json / theme_config.json
- memories/

策略：按天+毫秒命名 backup/backup_YYYYMMDD_HHMMSS_SSS/，保留最近 N 份（默认 3），
超期自动清理最旧目录。线程安全，失败不阻断应用。
"""

import shutil
import threading
from datetime import datetime
from pathlib import Path

from modules.base_manager import BaseManager

_BACKUP_LOCK = threading.Lock()


class BackupManager(BaseManager):
    """用户数据定期备份。"""

    def __init__(
        self,
        project_root: str | Path,
        backup_root: str | Path | None = None,
        keep_count: int = 3,
    ):
        super().__init__("backup")
        self.project_root = Path(project_root)
        self.backup_root = Path(backup_root) if backup_root else (self.project_root / "backup")
        self.keep_count = max(1, int(keep_count or 3))

    def _copy_dir(self, src: Path, dst: Path, skip_suffixes: tuple = (".wav",)) -> None:
        """复制目录，忽略临时/运行时文件。"""
        if not src.exists():
            return
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.name in (".git", "__pycache__"):
                continue
            target = dst / item.name
            if item.is_dir():
                self._copy_dir(item, target, skip_suffixes)
            elif item.is_file() and item.suffix.lower() not in skip_suffixes:
                try:
                    shutil.copy2(item, target)
                except OSError as e:
                    self.log("warning", f"备份跳过文件 {item}: {e}")

    def backup_now(self) -> str:
        """执行一次备份，返回备份目录路径（失败抛异常）。"""
        with _BACKUP_LOCK:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            dest = self.backup_root / f"backup_{stamp}"
            dest.mkdir(parents=True, exist_ok=True)

            self._copy_dir(self.project_root / "conversations", dest / "conversations")
            self._copy_dir(self.project_root / "characters", dest / "characters")
            self._copy_dir(self.project_root / "memories", dest / "memories")

            for fname in ("config.json", "theme_config.json"):
                src = self.project_root / fname
                if src.exists():
                    try:
                        shutil.copy2(src, dest / fname)
                    except OSError as e:
                        self.log("warning", f"备份跳过文件 {fname}: {e}")

            self._cleanup_old()
            self.log("info", f"数据备份完成: {dest}")
            return str(dest)

    def _cleanup_old(self) -> None:
        """清理超过保留份数的旧备份。"""
        backups = sorted(self.backup_root.glob("backup_*")) if self.backup_root.exists() else []
        while len(backups) > self.keep_count:
            oldest = backups.pop(0)
            shutil.rmtree(str(oldest), ignore_errors=True)
            self.log("info", f"清理旧备份: {oldest}")

    def list_backups(self) -> list[dict]:
        if not self.backup_root.exists():
            return []
        return [
            {"name": d.name, "path": str(d)}
            for d in sorted(self.backup_root.glob("backup_*"), reverse=True)
        ]
