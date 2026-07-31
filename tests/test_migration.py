"""MigrationManager 单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.config_manager import ConfigManager
from modules.migration import MigrationManager

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def test_migrate_v09_to_10(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.replace(
        {
            "data_version": "0.9",
            "llm": {"base_url": "http://x", "api_key": "sk-test", "model": "m"},
            "tts": {"api_base_url": "http://127.0.0.1:9880"},
        }
    )

    assert cm.check_data_version() is False  # 需要迁移
    mig = MigrationManager(cm, MIGRATIONS_DIR, backup_dir=tmp_path / "backup")
    ok, msg = mig.run()

    assert ok is True
    assert cm.get("data_version") == "1.0"
    config = cm.get_raw()
    assert "llm_providers" in config
    assert config["llm_providers"]["default"]["base_url"] == "http://x"
    assert cm.check_data_version() is True


def test_no_migration_needed(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.replace(
        {
            "data_version": "1.0",
            "llm": {"active_provider": "x", "fallback_enabled": True},
            "llm_providers": {"x": {"base_url": "http://x", "api_key": "", "model": "m"}},
            "tts": {"api_base_url": "http://127.0.0.1:9880"},
        }
    )

    mig = MigrationManager(cm, MIGRATIONS_DIR, backup_dir=tmp_path / "backup")
    ok, msg = mig.run()
    assert ok is True
    assert cm.get("data_version") == "1.0"
    # 未改变配置
    assert cm.get_active_provider_config()["base_url"] == "http://x"


def test_migration_backup_created(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.replace({"data_version": "0.9", "llm": {"base_url": "http://x"}})

    backup_dir = tmp_path / "backup"
    mig = MigrationManager(cm, MIGRATIONS_DIR, backup_dir=backup_dir)
    mig.run()

    backups = list(backup_dir.glob("pre_migration_*"))
    assert len(backups) == 1
    assert (backups[0] / "config.json").exists()
