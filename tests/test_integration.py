"""集成测试：完整对话流程（LLM+TTS mock）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.ui_service as ui_service_module
from modules.character_manager import CharManager
from modules.config_manager import ConfigManager
from modules.conversation_manager import ConvManager
from modules.ui_service import UiService

CHAR_JSON = {
    "name": "集成测试角色",
    "greeting": "你好呀，今天想聊什么？",
    "system_prompt_structured": {
        "personality": "温柔",
        "speaking_style": "柔和",
        "speech_quirks": ["句尾加'呢'"],
        "background": "学生",
        "likes": ["阅读"],
        "dislikes": [],
        "behavior_rules": [],
    },
    "chain_of_thought": "",
    "lorebook": {
        "enabled": True,
        "entries": [{"keywords": ["钢琴"], "content": "学姐从小学钢琴，考过八级"}],
    },
}


class FakeTTS:
    def synthesize_normalized(
        self, text, voice_lang, params=None, target_db=-3.0, global_volume=1.0
    ):
        return f"WAV-{text[:5]}".encode()

    def check_api(self):
        return True


def setup(tmp_path):
    char_dir = tmp_path / "chars" / "集成测试角色"
    char_dir.mkdir(parents=True)
    (char_dir / "character.json").write_text(
        json.dumps(CHAR_JSON, ensure_ascii=False), encoding="utf-8"
    )

    cm = ConfigManager(tmp_path / "config.json")
    cm.replace(
        {
            "data_version": "1.0",
            "llm": {"active_provider": "x", "fallback_enabled": True},
            "llm_providers": {"x": {"base_url": "http://x", "api_key": "", "model": "m"}},
            "tts": {"api_base_url": "http://127.0.0.1:9880", "voice_language": "中文"},
            "audio_normalization": {"enabled": True, "target_dB": -3.0, "global_volume": 1.0},
            "prompt_protection": {"mode": "A"},
            "app": {"max_input_length": 2000, "sensitive_words": []},
        }
    )

    char_mgr = CharManager(tmp_path / "chars", config_manager=cm)
    conv_mgr = ConvManager(tmp_path / "convs")
    ui = UiService(cm, char_mgr, conv_mgr, FakeTTS())
    ui.tts_healthy = True
    return cm, char_mgr, conv_mgr, ui


def fake_llm_fallback(providers, active, fallback, system_prompt, messages, session_provider=None):
    """模拟 LLM 返回，记录收到的上下文。"""
    user_input = messages[-1]["content"]
    if "钢琴" in user_input:
        return "哈哈，我钢琴八级呢！你要听我弹吗？", "x"
    return f"收到你的消息：{user_input[:20]}", "x"


def test_full_conversation_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_service_module, "call_llm_with_fallback", fake_llm_fallback)

    cm, char_mgr, conv_mgr, ui = setup(tmp_path)

    # 1. 选择角色
    result = ui.select_character("集成测试角色")
    assert result["character"] == "集成测试角色"

    # 2. 新建会话 → 问候语
    result = ui.new_session("集成测试角色")
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == CHAR_JSON["greeting"]
    assert result["messages"][0].get("audio_file")

    # 3. 发送消息（触发 Lorebook 匹配 → LLM → TTS）
    result = ui.send_message("你会弹钢琴吗？", "中文", "中文")
    assert "error" not in result
    messages = result["messages"]
    assert len(messages) == 3  # 问候 + 用户 + AI
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "你会弹钢琴吗？"
    assert messages[2]["role"] == "assistant"
    assert "钢琴八级" in messages[2]["content"]
    assert messages[2].get("audio_file")  # AI 回复含语音

    # 4. 收藏最后一条 AI 回复
    ui.active_session = result["session_id"]
    assert conv_mgr.add_favorite(result["session_id"], 2) is True
    assert conv_mgr.is_favorite(result["session_id"], 2) is True

    # 5. 统计
    stats = conv_mgr.get_session_stats(result["session_id"])
    assert stats["msg_count"] == 3
    assert stats["favorite_count"] == 1


def test_send_message_without_character_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_service_module, "call_llm_with_fallback", fake_llm_fallback)
    cm, char_mgr, conv_mgr, ui = setup(tmp_path)
    result = ui.send_message("你好", "中文", "中文")
    assert "error" in result
    assert "角色" in result["error"]
