"""prompt_builder 单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.prompt_builder import build_messages, build_system_prompt, wrap_user_input

CHARACTER = {
    "name": "温柔学姐",
    "system_prompt_structured": {
        "personality": "温柔善解人意",
        "speaking_style": "语气柔和",
        "speech_quirks": ["句尾加'呢'"],
        "background": "高中三年级学生",
        "likes": ["阅读", "钢琴"],
        "dislikes": ["香菜"],
        "behavior_rules": ["保持耐心"],
    },
    "chain_of_thought": "先理解情绪，再温和回应",
    "greeting": "你好呀",
}


def test_build_system_prompt_contains_sections():
    prompt = build_system_prompt(CHARACTER)
    assert "你是温柔学姐。" in prompt
    assert "[性格]" in prompt
    assert "[说话风格]" in prompt
    assert "[口癖]" in prompt
    assert "[背景]" in prompt
    assert "[喜好]" in prompt
    assert "[行为准则]" in prompt
    assert "[思考步骤]" in prompt


def test_build_system_prompt_lore_entries():
    prompt = build_system_prompt(CHARACTER, lore_entries=["学姐有个弟弟叫小杰"])
    assert "学姐有个弟弟叫小杰" in prompt


def test_build_system_prompt_text_lang():
    prompt = build_system_prompt(CHARACTER, text_lang="中文")
    assert "请用中文回复" in prompt


def test_build_system_prompt_protection_mode_c():
    prompt = build_system_prompt(CHARACTER, protection_mode="C")
    assert "[安全提示]" in prompt
    assert "不可改变" in prompt


def test_wrap_user_input_mode_c():
    wrapped = wrap_user_input("hello", "C")
    assert "用户消息开始" in wrapped
    assert "hello" in wrapped


def test_build_messages_structure():
    messages = build_messages(
        CHARACTER,
        lore_entries=None,
        summary="之前聊过学习",
        recent_messages=[{"role": "assistant", "content": "那要多复习"}],
        user_input="好的",
        text_lang="中文",
    )
    assert messages[0]["role"] == "system"
    assert "之前聊过学习" in messages[1]["content"]
    assert messages[2]["content"] == "那要多复习"
    assert messages[3] == {"role": "user", "content": "好的"}


def test_build_system_prompt_tolerates_non_list_fields():
    """likes/speech_quirks 等字段为非列表（用户手改配置）时不崩溃（修复）。"""
    bad = {
        "name": "乱配置",
        "system_prompt_structured": {
            "personality": "温和",
            "speech_quirks": "句尾加呢",  # 字符串而非列表
            "likes": None,  # None 而非列表
            "dislikes": "香菜",  # 字符串
            "behavior_rules": ["保持耐心"],
        },
    }
    prompt = build_system_prompt(bad)
    assert "乱配置" in prompt
    assert "句尾加呢" in prompt
    assert "[喜好]" in prompt
