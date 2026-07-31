"""I18n 单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.config_manager import ConfigManager
from modules.i18n import SUPPORTED_LOCALES, I18n

LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"


def test_language_persists_via_config(tmp_path):
    """界面语言以 locale 码持久化，重载后可恢复（回归：曾存中文显示名导致失效）。"""
    cm = ConfigManager(tmp_path / "config.json")
    cm.replace(
        {
            "data_version": "1.0",
            "llm": {"active_provider": "x", "fallback_enabled": True},
            "llm_providers": {"x": {"base_url": "http://x", "api_key": "", "model": "m"}},
            "tts": {"api_base_url": "http://127.0.0.1:9880"},
            "app": {"language": "ja_JP"},
        }
    )

    i18n = I18n(LOCALE_DIR)
    i18n.switch(cm.get("app", {}).get("language", "zh_CN"))
    assert i18n.current_lang == "ja_JP"
    assert i18n.t("发送") == "送信"


def test_supported_locales():
    assert SUPPORTED_LOCALES == ["zh_CN", "ja_JP", "en_US"]


def test_default_chinese():
    i18n = I18n(LOCALE_DIR)
    assert i18n.t("发送") == "发送"  # 中文回退


def test_switch_japanese():
    i18n = I18n(LOCALE_DIR)
    i18n.switch("ja_JP")
    assert i18n.t("发送") == "送信"
    assert i18n.t("角色") == "キャラクター"


def test_switch_english():
    i18n = I18n(LOCALE_DIR)
    i18n.switch("en_US")
    assert i18n.t("发送") == "Send"
    assert i18n.t("输入消息") == "Message input"


def test_missing_key_falls_back():
    i18n = I18n(LOCALE_DIR)
    i18n.switch("en_US")
    assert i18n.t("不存在的中文键") == "不存在的中文键"


def test_invalid_lang_falls_back():
    i18n = I18n(LOCALE_DIR)
    i18n.switch("xx_XX")
    assert i18n.current_lang == "zh_CN"
