"""主题系统（章节七十四）。

三层配置：
- 浅色/深色内置主题
- 用户自定义颜色（theme_config.json 覆盖）
- 自定义 CSS 注入
"""

import json
import threading
from copy import deepcopy
from pathlib import Path

DEFAULT_THEME_PATH = Path(__file__).resolve().parent.parent / "theme_config.json"

# 章节九十二：角色聊天背景遮罩（chat_overlay）默认配置
DEFAULT_CHAT_OVERLAY = {
    "enabled": True,
    "opacity": 0.4,
    "color": None,
}

# 章节九十三：聊天窗口头像（chat_avatar）默认配置
DEFAULT_CHAT_AVATAR = {
    "size": 128,
}

# theme_config.json 写入锁：主题切换与「聊天背景」折叠栏共用，防并发丢更新（92.7 #3）
THEME_WRITE_LOCK = threading.Lock()

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
                merged = _deep_merge(base, user)
            except (json.JSONDecodeError, OSError):
                merged = deepcopy(LIGHT_THEME)
        else:
            merged = deepcopy(LIGHT_THEME)
        # 章节九十二：chat_overlay 顶层节，与 custom 平级，缺失时补默认
        overlay = deepcopy(DEFAULT_CHAT_OVERLAY)
        if isinstance(merged.get("chat_overlay"), dict):
            _deep_merge(overlay, merged["chat_overlay"])
        merged["chat_overlay"] = overlay
        # 章节九十三：chat_avatar 顶层节（聊天窗口头像尺寸），缺失时补默认
        avatar = deepcopy(DEFAULT_CHAT_AVATAR)
        if isinstance(merged.get("chat_avatar"), dict):
            _deep_merge(avatar, merged["chat_avatar"])
        merged["chat_avatar"] = avatar
        return merged

    def reload(self) -> None:
        self.config = self.load()

    def save(self, path: str | Path | None = None) -> None:
        """写回 theme_config.json（加锁，92.7 #3）。"""
        target = Path(path) if path else self.path
        with THEME_WRITE_LOCK:
            target.write_text(
                json.dumps(self.config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def overlay(self) -> dict:
        """返回 chat_overlay 配置（遮罩/开关）。"""
        return self.config.get("chat_overlay", deepcopy(DEFAULT_CHAT_OVERLAY))

    def avatar_size(self) -> int:
        """返回聊天窗口头像尺寸（128/256，章节九十三）。"""
        av = self.config.get("chat_avatar", DEFAULT_CHAT_AVATAR)
        try:
            size = int(av.get("size", DEFAULT_CHAT_AVATAR["size"]))
        except (TypeError, ValueError):
            size = DEFAULT_CHAT_AVATAR["size"]
        return size if size in (128, 256) else DEFAULT_CHAT_AVATAR["size"]

    def to_css(self) -> str:
        """将主题配置转换为 CSS 字符串，注入 Gradio。

        - mode=light/dark：输出对应主题
        - mode=system（章节八十八 88.3）：浅色为默认，深色通过
          `@media (prefers-color-scheme: dark)` 自动跟随系统
        - 章节九十二：注入遮罩 CSS 变量（--chat-overlay-color/--chat-overlay-opacity），
          深色（含 system 深色）自动变深色遮罩，手动选色覆盖自动
        """
        mode = self.config.get("mode", "light")
        if mode == "system":
            # Q3：跟随系统时保留用户自定义色。
            # 仅将"用户显式声明的 custom 键"（相对基色的差异）叠加到深浅两套基色，
            # 避免把整套浅色默认值覆盖到深色配色上。
            base_light = deepcopy(LIGHT_THEME["custom"])
            base_dark = deepcopy(DARK_THEME["custom"])
            user_custom = self.config.get("custom", {})
            overrides = {}
            for k, v in user_custom.items():
                if v != base_light.get(k):
                    overrides[k] = v
            light = _deep_merge(base_light, deepcopy(overrides))
            dark = _deep_merge(base_dark, deepcopy(overrides))
            css = self._build_theme_css(light, overlay_color=self._overlay_color(False))
            css += self._build_system_dark_css(dark, overlay_color=self._overlay_color(True))
            return css
        is_dark = mode == "dark"
        return self._build_theme_css(
            self.config.get("custom", {}), overlay_color=self._overlay_color(is_dark)
        )

    def _overlay_color(self, dark: bool) -> str:
        """遮罩颜色：手动选色优先，否则自动随明暗（浅白/深黑）。"""
        ov = self.config.get("chat_overlay", {})
        manual = ov.get("color")
        if manual:
            return manual
        return "#000000" if dark else "#FFFFFF"

    def _overlay_opacity(self) -> str:
        ov = self.config.get("chat_overlay", {})
        try:
            return str(max(0.0, min(0.9, float(ov.get("opacity", 0.4)))))
        except (TypeError, ValueError):
            return "0.4"

    def _build_theme_css(self, c: dict, overlay_color: str = "#FFFFFF") -> str:
        bg = c.get("chat_background", {}).get("value", "#F0F0F0")
        css = f"""
        :root {{
            --primary-color: {c.get("primary_color", "#4A90D9")};
            --bg-color: {c.get("background_color", "#F5F5F5")};
            --user-bubble: {c.get("user_bubble_color", "#95EC69")};
            --ai-bubble: {c.get("ai_bubble_color", "#FFFFFF")};
            --text-color: {c.get("text_color", "#333333")};
            --timestamp-color: {c.get("timestamp_color", "#999999")};
            --font-size: {c.get("font_size", "14px")};
            --border-radius: {c.get("border_radius", "18px")};
            --chat-overlay-color: {overlay_color};
            --chat-overlay-opacity: {self._overlay_opacity()};
            --chat-avatar-size: {self.avatar_size()}px;
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
            border-radius: {c["avatar_border_radius"]};
        }}
        """
        custom_css = self.config.get("custom_css", "")
        if custom_css:
            css += f"\n{custom_css}"
        return css

    def _build_system_dark_css(self, c: dict, overlay_color: str = "#000000") -> str:
        """主题跟随系统：深色覆盖（prefers-color-scheme: dark）。"""
        bg = c.get("chat_background", {}).get("value", "#262626")
        return f"""
        @media (prefers-color-scheme: dark) {{
            :root {{
                --primary-color: {c.get("primary_color", "#61A5E0")};
                --bg-color: {c.get("background_color", "#1F1F1F")};
                --user-bubble: {c.get("user_bubble_color", "#2E7D32")};
                --ai-bubble: {c.get("ai_bubble_color", "#2D2D2D")};
                --text-color: {c.get("text_color", "#E0E0E0")};
                --timestamp-color: {c.get("timestamp_color", "#888888")};
                --chat-overlay-color: {overlay_color};
                --chat-avatar-size: {self.avatar_size()}px;
            }}
            body {{
                background-color: var(--bg-color);
                color: var(--text-color);
            }}
            .gradio-container {{
                background-color: {bg};
            }}
        }}
        """

    def mode(self) -> str:
        return self.config.get("mode", "light")


theme = Theme()
