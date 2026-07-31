"""ConvManager 单元测试（含摘要压缩）。"""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.conversation_manager import ConvManager


def test_load_all_caches_messages(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "你好")

    # 新实例 load_all 后缓存加载
    mgr2 = ConvManager(tmp_path)
    assert mgr2._messages_cache == {}  # 尚未加载
    mgr2.load_all()
    assert mgr2._messages_cache[sid] == mgr.get_messages(sid)

    # 缓存命中后读取结果一致
    assert mgr2.get_messages(sid) == mgr2._messages_cache[sid]


def test_cache_invalidated_on_delete(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "hi")
    assert sid in mgr._messages_cache
    mgr.delete_session(sid)
    assert sid not in mgr._messages_cache


def test_create_and_list_session(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session("日常")
    assert mgr.session_exists(sid)
    sessions = mgr.list_sessions()
    assert sessions[0]["name"] == "日常"
    assert sessions[0]["msg_count"] == 0


def test_add_message_and_get(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "你好")
    mgr.add_message(sid, "assistant", "你好呀", audio_data=b"WAVDATA")

    messages = mgr.get_messages(sid)
    assert len(messages) == 2
    assert messages[1]["audio_file"] == "audio/msg_1.wav"
    assert (tmp_path / sid / "audio" / "msg_1.wav").read_bytes() == b"WAVDATA"


def test_delete_and_rename(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session("原名")
    mgr.rename_session(sid, "新名")
    assert mgr.list_sessions()[0]["name"] == "新名"
    assert mgr.delete_session(sid) is True
    assert not mgr.session_exists(sid)


def test_build_llm_context_keeps_recent_rounds(tmp_path):
    mgr = ConvManager(tmp_path, max_history_rounds=2)
    sid = mgr.create_session()
    for i in range(6):
        mgr.add_message(sid, "user", f"q{i}")
        mgr.add_message(sid, "assistant", f"a{i}")

    summary, recent = mgr.build_llm_context(sid)
    assert summary == ""
    assert len(recent) == 4  # 最近 2 轮 = 4 条
    assert recent[-1]["content"] == "a5"
    assert mgr.total_rounds(sid) == 6


def test_maybe_summarize_triggered(tmp_path):
    mgr = ConvManager(tmp_path, max_history_rounds=2, summarize_trigger_rounds=3)
    sid = mgr.create_session()
    for i in range(4):
        mgr.add_message(sid, "user", f"q{i}")
        mgr.add_message(sid, "assistant", f"a{i}")

    new_summary = mgr.maybe_summarize(sid, summarize_fn=lambda h: "【摘要】聊了 4 轮")
    assert new_summary == "【摘要】聊了 4 轮"
    summary, recent = mgr.build_llm_context(sid)
    assert summary == "【摘要】聊了 4 轮"
    assert len(recent) == 4  # 仅保留最近 2 轮


def test_maybe_summarize_not_triggered(tmp_path):
    mgr = ConvManager(tmp_path, summarize_trigger_rounds=100)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "hi")
    mgr.add_message(sid, "assistant", "hello")
    assert mgr.maybe_summarize(sid, summarize_fn=lambda h: "不应触发") == ""


def test_export_and_import_session(tmp_path):
    mgr = ConvManager(tmp_path / "convs")
    sid = mgr.create_session("导出测试")
    mgr.add_message(sid, "user", "你好")
    mgr.add_message(sid, "assistant", "你好呀", audio_data=b"WAV")

    zip_path = mgr.export_session(sid)
    assert zip_path is not None

    # 导入到新目录
    mgr2 = ConvManager(tmp_path / "convs2")
    new_sid = mgr2.import_session(zip_path)
    assert new_sid is not None
    messages = mgr2.get_messages(new_sid)
    assert len(messages) == 2
    assert messages[1]["audio_file"] == "audio/msg_1.wav"


def test_import_session_rejects_invalid(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("messages.json", "{not valid json")

    mgr = ConvManager(tmp_path / "convs")
    assert mgr.import_session(bad_zip) is None


def test_import_session_path_traversal_guarded(tmp_path):
    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("messages.json", "[]")
        zf.writestr("../evil.txt", "pwned")

    convs = tmp_path / "convs"
    mgr = ConvManager(convs)
    sid = mgr.import_session(evil_zip)
    assert sid is not None
    assert not (tmp_path / "evil.txt").exists()  # 越界文件未写出


# ---------- 收藏（章节六十一） ----------


def test_favorite_add_remove_list(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "你好")
    mgr.add_message(sid, "assistant", "你好呀")

    assert mgr.add_favorite(sid, 1, tags=["精彩"], note="风格好") is True
    assert mgr.is_favorite(sid, 1) is True
    assert mgr.is_favorite(sid, 0) is False

    favs = mgr.list_favorites(sid)
    assert len(favs) == 1
    assert favs[0]["content"] == "你好呀"
    assert favs[0]["tags"] == ["精彩"]

    assert mgr.add_favorite(sid, 1) is False  # 已收藏
    assert mgr.remove_favorite(sid, 1) is True
    assert mgr.list_favorites(sid) == []
    assert mgr.remove_favorite(sid, 1) is False  # 不存在


def test_favorite_invalid_index(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    assert mgr.add_favorite(sid, 5) is False  # 越界


# ---------- 搜索（章节七十三） ----------


def test_search_in_session(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "我喜欢学习钢琴")
    mgr.add_message(sid, "assistant", "那要多练习呢")
    mgr.add_message(sid, "user", "最近好累")

    results = mgr.search_in_session(sid, "钢琴")
    assert len(results) == 1
    assert results[0]["index"] == 0
    assert results[0]["context_after"] == "那要多练习呢"


def test_search_global_with_filters(tmp_path):
    mgr = ConvManager(tmp_path)
    s1 = mgr.create_session("会话A")
    s2 = mgr.create_session("会话B")
    mgr.add_message(s1, "user", "讨论钢琴")
    mgr.add_message(s1, "assistant", "钢琴很好听")
    mgr.add_message(s2, "user", "钢琴坏了")

    all_results = mgr.search_global("钢琴")
    assert len(all_results) == 3

    fav_only = mgr.search_global("钢琴", filters={"is_favorite": True})
    assert fav_only == []

    mgr.add_favorite(s1, 1)
    fav_only = mgr.search_global("钢琴", filters={"is_favorite": True})
    assert len(fav_only) == 1
    assert fav_only[0]["index"] == 1


# ---------- 统计（章节六十八） ----------


def test_session_and_global_stats(tmp_path):
    mgr = ConvManager(tmp_path)
    s1 = mgr.create_session("会话A")
    mgr.add_message(s1, "user", "你好")
    mgr.add_message(s1, "assistant", "你好呀")
    mgr.add_favorite(s1, 1)

    stats = mgr.get_session_stats(s1)
    assert stats["msg_count"] == 2
    assert stats["user_count"] == 1
    assert stats["ai_count"] == 1
    assert stats["favorite_count"] == 1

    s2 = mgr.create_session("会话B")
    mgr.add_message(s2, "user", "hi")

    global_stats = mgr.get_global_stats()
    assert global_stats["session_count"] == 2
    assert global_stats["total_msgs"] == 3
    assert global_stats["total_favorites"] == 1
    assert global_stats["most_active_session"]["session_id"] == s1
