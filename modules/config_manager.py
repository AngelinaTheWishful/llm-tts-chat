"""ConfigManager：config.json 的加载、保存与校验。

采用单一数据源规则：`llm` 仅含选择器（active_provider/fallback_enabled），
提供商参数唯一存放于 `llm_providers`。读取当前 LLM 配置必须通过
get_active_provider_config()。
"""

import base64
import copy
import json
import os
import threading
from pathlib import Path

from modules.base_manager import BaseManager

DATA_VERSION = "1.0"

DEFAULT_CONFIG = {
    "data_version": DATA_VERSION,
    "llm": {
        "active_provider": "",
        "fallback_enabled": True,
    },
    "llm_providers": {},
    "tts": {
        "api_base_url": "http://127.0.0.1:9880",
        "version": "v2Pro",
        "voice_language": "中文",
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 1.0,
        "speed": 1.0,
        "synthesis_timeout": 20,
    },
    "app": {
        "port": 7861,
        "max_history_rounds": 4,
        "summarize_trigger_rounds": 20,
        "max_input_length": 2000,
        "sensitive_words": [],
        "language": "zh_CN",
        "sidebar_collapsed": False,
        "sidebar_width": 320,
    },
    "memory": {
        "enabled": True,
        "scope": "character",
        "recall_limit": 5,
        "extract_with_llm": False,
    },
    "gsv_root": "",
    "external_characters": [],
    "trash": {
        "auto_clean_days": 30,
        "max_size_mb": 500,
    },
    "session_timeout": {
        "idle_minutes": 30,
        "warning_minutes": 25,
    },
    "performance": {
        "device": "auto",
        "max_llm_concurrency": 2,
        "max_tts_concurrency": 1,
    },
    "prompt_protection": {
        "mode": "A",
    },
    "notification_sound": {
        "enabled": True,
        "sound_file": "sounds/notification.wav",
        "volume": 0.7,
    },
    "audio_normalization": {
        "enabled": True,
        "target_dB": -3.0,
        "global_volume": 1.0,
    },
    "proxy": {
        "enabled": False,
        "http": "",
        "https": "",
        "no_proxy": ["localhost", "127.0.0.1"],
    },
    "gsv_training": {
        "gsv_root": "",
        "archive_dir": "",
        "restore_dir": "",
        "cleanup_after_pack": True,
        "auto_detect": False,
        "auto_full": False,
    },
}


def encrypt_api_key(key: str) -> str:
    """简单 base64 编码（非真加密，仅防肉眼直接查看）。"""
    return base64.b64encode(key.encode()).decode()


def decrypt_api_key(encoded: str) -> str:
    """解码 base64，兼容旧版明文（validate=True 确保非 base64 字符原样返回）。"""
    try:
        decoded = base64.b64decode(encoded.encode(), validate=True).decode("utf-8")
        return decoded
    except Exception:
        return encoded


PROXY_ENV_VARS = ["HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"]


def apply_proxy_env(proxy_config: dict | None = None) -> None:
    """根据 config['proxy'] 注入/清除代理环境变量（R10）。

    requests 与 httpx(openai) 均默认从环境变量读取代理，注入即真实接线。
    - enabled=False 或未配置时清除全部代理环境变量
    """
    proxy = proxy_config or {}
    if proxy.get("enabled") and (proxy.get("http") or proxy.get("https")):
        os.environ["HTTP_PROXY"] = proxy.get("http", "") or ""
        os.environ["http_proxy"] = proxy.get("http", "") or ""
        os.environ["HTTPS_PROXY"] = proxy.get("https", "") or ""
        os.environ["https_proxy"] = proxy.get("https", "") or ""
        no_proxy = ",".join(p for p in (proxy.get("no_proxy") or []) if p)
        if no_proxy:
            os.environ["NO_PROXY"] = no_proxy
            os.environ["no_proxy"] = no_proxy
        else:
            os.environ.pop("NO_PROXY", None)
            os.environ.pop("no_proxy", None)
    else:
        for var in PROXY_ENV_VARS + ["NO_PROXY", "no_proxy"]:
            os.environ.pop(var, None)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 覆盖 base。"""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class ConfigManager(BaseManager):
    """config.json 加载/保存管理器（threading.Lock 写锁保护）。"""

    def __init__(self, config_path: str | Path | None = None):
        super().__init__("config")
        self.path = Path(config_path) if config_path else Path("config.json")
        # RLock：replace/update 内部再调用 save 时允许重入，避免死锁
        self._lock = threading.RLock()
        self._config: dict = {}
        self.load()

    def load(self) -> dict:
        """从磁盘加载配置并合并默认值。"""
        config = copy.deepcopy(DEFAULT_CONFIG)
        if self.path.exists():
            try:
                user_config = json.loads(self.path.read_text(encoding="utf-8-sig"))
                _deep_merge(config, user_config)
            except (json.JSONDecodeError, OSError) as e:
                self.log("error", f"[CFG-001] 配置加载失败，使用默认配置: {e}")
        self._config = config
        self.check_data_version()
        return self._config

    def check_data_version(self) -> bool:
        """检查数据版本是否匹配，不匹配时记录警告（迁移框架在数据迁移阶段实现）。

        Returns:
            True 表示版本一致，False 表示需要迁移
        """
        current = self._config.get("data_version", "0.9")
        if current != DATA_VERSION:
            self.log(
                "warning",
                f"数据版本不匹配（当前 {current}，预期 {DATA_VERSION}），"
                f"请在数据迁移阶段执行迁移脚本",
            )
            return False
        return True

    def get_raw(self) -> dict:
        """返回配置的深拷贝（只读用途）。"""
        return copy.deepcopy(self._config)

    def save(self) -> None:
        """原子写入 config.json（写锁保护 + 临时文件替换）。"""
        with self._lock:
            tmp_path = self.path.with_suffix(".tmp")
            try:
                tmp_path.write_text(
                    json.dumps(self._config, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(tmp_path, self.path)
                self.log("debug", f"配置已保存: {self.path}")
            except OSError as e:
                self.log("error", f"[CFG-002] 配置保存失败: {e}")

    def get(self, key: str, default=None):
        """读取顶层配置项。"""
        return self._config.get(key, default)

    def update(self, section: str, field: str, value) -> None:
        """更新 config[section][field] 并立即保存。"""
        with self._lock:
            self._config.setdefault(section, {})
            self._config[section][field] = value
            self.save()

    def replace(self, new_config: dict) -> None:
        """整体替换配置（配置向导完成后调用）并保存。"""
        with self._lock:
            self._config = new_config
            self.save()

    def get_active_provider_config(self) -> dict:
        """返回当前活动提供商的完整配置（单一数据源规则）。"""
        active = self._config.get("llm", {}).get("active_provider")
        providers = self._config.get("llm_providers", {})
        if active and active in providers:
            return providers[active]
        for name, cfg in providers.items():
            return cfg
        return {}

    def is_first_run(self) -> bool:
        """判断是否需要进入首次启动配置向导。"""
        if not self.path.exists():
            return True
        if not self._config.get("llm", {}).get("active_provider"):
            return True
        if not self._config.get("llm_providers", {}):
            return True
        if not self._config.get("tts", {}).get("api_base_url"):
            return True
        return False
