"""Theme 单元测试。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.theme import DARK_THEME, LIGHT_THEME, Theme


def test_default_light_theme(tmp_path):
    theme = Theme(tmp_path / "nonexistent.json")
    assert theme.mode() == "light"
    assert theme.config["custom"]["user_bubble_color"] == LIGHT_THEME["custom"]["user_bubble_color"]


def test_dark_theme_from_config(tmp_path):
    cfg = tmp_path / "theme_config.json"
    cfg.write_text(json.dumps({"mode": "dark"}), encoding="utf-8")
    theme = Theme(cfg)
    assert theme.mode() == "dark"
    assert theme.config["custom"]["background_color"] == DARK_THEME["custom"]["background_color"]


def test_custom_color_override(tmp_path):
    cfg = tmp_path / "theme_config.json"
    cfg.write_text(
        json.dumps({"mode": "light", "custom": {"user_bubble_color": "#FF0000"}}),
        encoding="utf-8",
    )
    theme = Theme(cfg)
    assert theme.config["custom"]["user_bubble_color"] == "#FF0000"
    # 其他字段保留默认
    assert theme.config["custom"]["ai_bubble_color"] == LIGHT_THEME["custom"]["ai_bubble_color"]


def test_custom_css_injected(tmp_path):
    cfg = tmp_path / "theme_config.json"
    cfg.write_text(
        json.dumps({"mode": "light", "custom_css": ".user-message { box-shadow: 0 1px; }"}),
        encoding="utf-8",
    )
    theme = Theme(cfg)
    css = theme.to_css()
    assert "box-shadow" in css
    assert "user-bubble" in css


def test_to_css_contains_variables():
    theme = Theme(Path(__file__).resolve().parent.parent / "theme_config.json")
    css = theme.to_css()
    assert "--primary-color" in css
    assert "gradio-container" in css


def test_invalid_json_uses_light(tmp_path):
    cfg = tmp_path / "theme_config.json"
    cfg.write_text("{not valid", encoding="utf-8")
    theme = Theme(cfg)
    assert theme.mode() == "light"


def test_chat_overlay_defaults(tmp_path):
    theme = Theme(tmp_path / "nonexistent.json")
    ov = theme.overlay()
    assert ov["enabled"] is True
    assert ov["opacity"] == 0.4
    assert ov["color"] is None


def test_chat_overlay_partial_merge(tmp_path):
    cfg = tmp_path / "theme_config.json"
    cfg.write_text(json.dumps({"chat_overlay": {"opacity": 0.7}}), encoding="utf-8")
    theme = Theme(cfg)
    ov = theme.overlay()
    assert ov["opacity"] == 0.7
    assert ov["enabled"] is True
    assert ov["color"] is None


def test_chat_overlay_manual_color_used_in_css(tmp_path):
    cfg = tmp_path / "theme_config.json"
    cfg.write_text(
        json.dumps({"mode": "light", "chat_overlay": {"color": "#123456", "opacity": 0.5}}),
        encoding="utf-8",
    )
    theme = Theme(cfg)
    css = theme.to_css()
    assert "--chat-overlay-color: #123456" in css
    assert "--chat-overlay-opacity: 0.5" in css


def test_chat_overlay_save_persists(tmp_path):
    cfg = tmp_path / "theme_config.json"
    theme = Theme(cfg)
    theme.config["chat_overlay"] = {"enabled": False, "opacity": 0.2, "color": None}
    theme.save()
    reloaded = Theme(cfg)
    assert reloaded.overlay()["enabled"] is False
    assert reloaded.overlay()["opacity"] == 0.2
