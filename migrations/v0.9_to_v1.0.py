"""v0.9 → v1.0 数据迁移：旧版 llm 节点迁移到 llm_providers。"""


def migrate(config: dict, data_dir) -> dict:
    """旧版 llm 节点迁移到 llm_providers（单一数据源）。"""
    # 旧版 llm 节点迁移到 llm_providers（单一数据源）
    if "llm_providers" not in config:
        old_llm = config.pop("llm", {})
        config["llm"] = {"active_provider": "default", "fallback_enabled": True}
        config["llm_providers"] = {"default": {**old_llm, "priority": 1}}
    if "voice_language" not in config.get("tts", {}):
        config["tts"]["voice_language"] = "中文"
    return config
