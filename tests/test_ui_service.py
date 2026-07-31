"""UiService 纯函数单元测试（sanitize_input / messages_to_chatbot）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.character_manager import CharManager
from modules.config_manager import ConfigManager
from modules.conversation_manager import ConvManager
from modules.ui_service import UiService, sanitize_input


def test_sanitize_input_strips_and_checks_length():
    text, warn = sanitize_input("  你好  ")
    assert text == "你好"
    assert warn == ""

    text, warn = sanitize_input("   ")
    assert text == ""
    assert warn == "请输入消息"


def test_sanitize_input_length_limit():
    text, warn = sanitize_input("x" * 100, max_length=10)
    assert warn == "消息过长（100/10），请分段发送"


def test_sanitize_input_html_escape():
    text, _ = sanitize_input("<script>alert(1)</script>")
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_sanitize_input_sensitive_words():
    text, _ = sanitize_input("讨论敏感话题", sensitive_words=["敏感"])
    assert "敏感" not in text
    assert "**" in text


def test_messages_to_chatbot_pairs():
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
        {"role": "user", "content": "最近怎样"},
        {"role": "assistant", "content": "还不错"},
    ]
    pairs = UiService.messages_to_chatbot(messages)
    assert pairs == [["你好", "你好呀"], ["最近怎样", "还不错"]]


def test_messages_to_chatbot_single_assistant():
    messages = [
        {"role": "assistant", "content": "我是AI"},
    ]
    pairs = UiService.messages_to_chatbot(messages)
    assert pairs == [["", "我是AI"]]


class FakeTTS:
    def synthesize_normalized(self, *args, **kwargs):
        return b"WAVDATA"

    def check_api(self):
        return True


def make_service(tmp_path):
    char_dir = tmp_path / "chars" / "问候角色"
    char_dir.mkdir(parents=True)
    greeting_text = {"name": "问候角色", "greeting": "你好呀，最近学习顺利吗？"}
    (char_dir / "character.json").write_text(
        json.dumps(greeting_text, ensure_ascii=False),
        encoding="utf-8",
    )
    cm = ConfigManager(tmp_path / "cfg.json")
    cm.replace(
        {
            "data_version": "1.0",
            "llm": {"active_provider": "x", "fallback_enabled": True},
            "llm_providers": {"x": {"base_url": "http://x", "api_key": "", "model": "m"}},
            "tts": {"api_base_url": "http://127.0.0.1:9880", "voice_language": "中文"},
        }
    )
    char_mgr = CharManager(tmp_path / "chars", config_manager=cm)
    conv_mgr = ConvManager(tmp_path / "convs")
    ui = UiService(cm, char_mgr, conv_mgr, FakeTTS())
    ui.tts_healthy = True
    return ui


def test_new_session_adds_greeting(tmp_path):
    ui = make_service(tmp_path)
    ui.active_character = "问候角色"
    result = ui.new_session("问候角色")

    assert len(result["messages"]) == 1
    msg = result["messages"][0]
    assert msg["role"] == "assistant"
    assert msg["content"] == "你好呀，最近学习顺利吗？"
    assert msg.get("audio_file")  # 含问候语音频
    assert result["audio_path"]  # last_audio_path 已更新


def test_new_session_no_character_no_greeting(tmp_path):
    ui = make_service(tmp_path)
    result = ui.new_session(None)
    assert result["messages"] == []


def test_last_audio_file_returns_none_when_missing(tmp_path):
    """无音频时返回 None（而非空串），防止 Gradio 把空串解析为工作目录导致 PermissionError。"""
    ui = make_service(tmp_path)
    ui.tts_healthy = False  # 关闭 TTS，问候语无音频
    ui.active_character = "问候角色"
    result = ui.new_session("问候角色")
    assert result["messages"][0].get("audio_file") is None
    assert result["audio_path"] is None
    assert ui._last_audio_file(result["session_id"]) is None


def test_last_audio_file_returns_existing_file(tmp_path):
    from pathlib import Path

    ui = make_service(tmp_path)
    ui.tts_healthy = True
    ui.active_character = "问候角色"
    session = ui.new_session("问候角色")["session_id"]

    # 问候语带音频，路径应指向存在的文件
    path = ui._last_audio_file(session)
    assert path is not None
    assert Path(path).is_file()
