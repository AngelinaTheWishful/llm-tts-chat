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
    """R1：存储/LLM 使用原始文本，不做 HTML 转义（XSS 由渲染层负责）。"""
    text, _ = sanitize_input("<script>alert(1)</script>")
    assert text == "<script>alert(1)</script>"
    assert "&lt;" not in text


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

    def list_gpt_models(self, gsv_root):
        from modules.tts_client import TTSClient

        return TTSClient.list_gpt_models(gsv_root)

    def list_sovits_models(self, gsv_root):
        from modules.tts_client import TTSClient

        return TTSClient.list_sovits_models(gsv_root)


class FakeTTSOffline:
    def synthesize_normalized(self, *args, **kwargs):
        return b"WAVDATA"

    def check_api(self):
        return False

    def list_gpt_models(self, gsv_root):
        from modules.tts_client import TTSClient

        return TTSClient.list_gpt_models(gsv_root)

    def list_sovits_models(self, gsv_root):
        from modules.tts_client import TTSClient

        return TTSClient.list_sovits_models(gsv_root)


def make_service(tmp_path, tts=None):
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
            "memory": {"enabled": True, "scope": "character", "recall_limit": 5},
        }
    )
    char_mgr = CharManager(tmp_path / "chars", config_manager=cm)
    conv_mgr = ConvManager(tmp_path / "convs")
    from modules.memory_store import MemoryStore

    ui = UiService(
        cm,
        char_mgr,
        conv_mgr,
        tts or FakeTTS(),
        memory_store=MemoryStore(tmp_path / "memories"),
    )
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
    """无音频时返回 None（而非空串），防止 Gradio 把空串解析为工作目录导致 PermissionError。

    R7：TTS 离线（实时探测仍离线）时问候语无音频。
    """
    ui = make_service(tmp_path, tts=FakeTTSOffline())
    ui.tts_healthy = False  # 缓存离线 + 实时探测离线 → 无音频
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


def test_last_audio_file_rejects_path_traversal(tmp_path):
    """audio_file 含 ../ 越界路径时被拒绝，不返回会话目录外文件（修复）。"""
    import json

    ui = make_service(tmp_path)
    session = ui.new_session("问候角色")["session_id"]

    # 越界文件（会话目录外）
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"WAV")

    # 写入含 ../../ 的 audio_file 字段
    messages = ui.conv_mgr.get_messages(session)
    messages.append({"role": "assistant", "content": "x", "audio_file": "../../outside.wav"})
    import pathlib

    sdir = pathlib.Path(ui.conv_mgr.dir) / session
    (sdir / "messages.json").write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")

    assert ui._last_audio_file(session) is None  # 越界路径被拒绝


def test_select_character_returns_avatar_path(tmp_path):
    """章节九十三：select_character 返回角色头像路径（portrait.png 存在时）。"""
    # 头像角色（带 portrait.png）
    char_dir = tmp_path / "chars" / "头像角色"
    char_dir.mkdir(parents=True)
    (char_dir / "character.json").write_text(
        json.dumps({"name": "头像角色"}, ensure_ascii=False), encoding="utf-8"
    )
    (char_dir / "portrait.png").write_bytes(b"PNGDATA")

    ui = make_service(tmp_path)
    result = ui.select_character("头像角色")
    assert "error" not in result
    assert result["character"] == "头像角色"
    assert result["avatar"] == str(char_dir / "portrait.png")


def test_select_character_avatar_empty_when_missing(tmp_path):
    """章节九十三：无 portrait.png 时 avatar 返回空串（前端回落首字占位）。"""
    ui = make_service(tmp_path)
    result = ui.select_character("问候角色")  # make_service 未建头像文件
    assert "error" not in result
    assert result["avatar"] == ""


def test_refresh_gsv_root_success(tmp_path):
    """章节九十四：refresh_gsv_root 全量刷新——探测成功返回路径并更新状态。"""
    gsv = tmp_path / "GPT-SoVITS-v2pro-test"
    gsv.mkdir(parents=True)
    (gsv / "api_v2.py").write_text("", encoding="utf-8")
    (gsv / "GPT_weights_v2Pro").mkdir(parents=True)
    (gsv / "GPT_weights_v2Pro" / "a.ckpt").write_bytes(b"")
    (gsv / "SoVITS_weights_v2Pro").mkdir(parents=True)
    (gsv / "SoVITS_weights_v2Pro" / "a.pth").write_bytes(b"")

    ui = make_service(tmp_path)
    ui.config_mgr.set_top_level("gsv_root", str(gsv))
    result = ui.refresh_gsv_root()
    assert result["ok"] is True
    assert result["path"] == str(gsv)
    assert result["source"] == "config"
    assert "GPT 模型 1 个" in result["message"]
    assert "SoVITS 模型 1 个" in result["message"]


def test_refresh_gsv_root_fail_message(tmp_path):
    """章节九十四：探测失败返回 CFG-008 提示。"""
    ui = make_service(tmp_path)
    ui.config_mgr.set_top_level("gsv_root", "")
    result = ui.refresh_gsv_root()
    assert result["ok"] is False
    assert result["path"] == ""
    assert "[CFG-008]" in result["message"]
