"""I18n：多语言界面（章节二十二）。

- locales/zh_CN.json（键为中文原文）
- locales/ja_JP.json、locales/en_US.json 映射到对应语言
- t(key) 未找到时回退到中文 key
"""

import json
from pathlib import Path

DEFAULT_LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"
SUPPORTED_LOCALES = ["zh_CN", "ja_JP", "en_US"]


class I18n:
    """多语言支持。"""

    def __init__(self, locale_dir: str | Path = DEFAULT_LOCALE_DIR):
        self.locale_dir = Path(locale_dir)
        self.current_lang = "zh_CN"
        self.translations: dict = {}
        self._load_all()

    def _load_all(self) -> None:
        """预加载所有语言包。"""
        self._loaded: dict[str, dict] = {}
        for lang in SUPPORTED_LOCALES:
            path = self.locale_dir / f"{lang}.json"
            if path.exists():
                try:
                    self._loaded[lang] = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._loaded[lang] = {}
            else:
                self._loaded[lang] = {}
        self.switch("zh_CN")

    def switch(self, lang: str) -> None:
        """切换当前语言。"""
        if lang not in self._loaded:
            lang = "zh_CN"
        self.current_lang = lang
        self.translations = self._loaded.get(lang, {})

    def t(self, key: str) -> str:
        """翻译：key 是中文原文，fallback 回中文。"""
        return self.translations.get(key, key)

    def available_locales(self) -> list[str]:
        return SUPPORTED_LOCALES
