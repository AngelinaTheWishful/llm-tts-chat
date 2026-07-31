"""主题系统（章节七十四）。

三层配置：
- 浅色/深色内置主题
- 用户自定义颜色（theme_config.json 覆盖）
- 自定义 CSS 注入
"""

import json
from copy import deepcopy
from pathlib import Path

DEFAULT_THEME_PATH = Path(__file__).resolve().parent.parent / "theme_config.json"

LIGHT_THEME = {
    "mode": "light",
    "custom": {
        "primary_color": "#4A90D9",
        "background_color": "#F5F5F5",
        "user_bubble_color": "#95EC69",
        "ai_bubble_color": "#FFFFFF",
        "text_color": "#333333",
        "timestamp_color": "#999999",
        "font_size": "14px",
        "border_radius": "18px",
        "avatar_border_radius": "50%",
        "chat_background": {"type": "color", "value": "#F0F0F0"},
    },
    "custom_css": "",
}

DARK_THEME = {
    "mode": "dark",
    "custom": {
        "primary_color": "#61A5E0",
        "background_color": "#1F1F1F",
        "user_bubble_color": "#2E7D32",
        "ai_bubble_color": "#2D2D2D",
        "text_color": "#E0E0E0",
        "timestamp_color": "#888888",
        "font_size": "14px",
        "border_radius": "18px",
        "avatar_border_radius": "50%",
        "chat_background": {"type": "color", "value": "#262626"},
    },
    "custom_css": "",
}


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class Theme:
    """加载主题配置并生成 CSS。"""

    def __init__(self, theme_path: str | Path = DEFAULT_THEME_PATH):
        self.path = Path(theme_path)
        self.config: dict = self.load()

    def load(self) -> dict:
        if self.path.exists():
            try:
                user = json.loads(self.path.read_text(encoding="utf-8"))
                base = deepcopy(DARK_THEME if user.get("mode") == "dark" else LIGHT_THEME)
                return _deep_merge(base, user)
            except (json.JSONDecodeError, OSError):
                return deepcopy(LIGHT_THEME)
        return deepcopy(LIGHT_THEME)

    def reload(self) -> None:
        self.config = self.load()

    def to_css(self) -> str:
        """将主题配置转换为 CSS 字符串，注入 Gradio。"""
        c = self.config.get("custom", {})
        bg = c.get("chat_background", {}).get("value", "#F0F0F0")
        css = f"""
        :root {{
            --primary-color: {c.get('primary_color', '#4A90D9')};
            --bg-color: {c.get('background_color', '#F5F5F5')};
            --user-bubble: {c.get('user_bubble_color', '#95EC69')};
            --ai-bubble: {c.get('ai_bubble_color', '#FFFFFF')};
            --text-color: {c.get('text_color', '#333333')};
            --timestamp-color: {c.get('timestamp_color', '#999999')};
            --font-size: {c.get('font_size', '14px')};
            --border-radius: {c.get('border_radius', '18px')};
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-size: var(--font-size);
        }}
        .gradio-container {{
            background-color: {bg};
        }}
        """
        if c.get("avatar_border_radius"):
            css += f"""
        .avatar img {{
            border-radius: {c['avatar_border_radius']};
        }}
        """
        custom_css = self.config.get("custom_css", "")
        if custom_css:
            css += f"\n{custom_css}"
        return css

    def mode(self) -> str:
        return self.config.get("mode", "light")


theme = Theme()
