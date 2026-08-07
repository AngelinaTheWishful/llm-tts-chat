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
    sid = mgr.create_session("日常")
    mgr.add_message(sid, "user", "你好")
    mgr.add_message(sid, "assistant", "你好呀", audio_data=b"WAVDATA")

    messages = mgr.get_messages(sid)
    assert len(messages) == 2
    # 章节九十五：音频命名规范（角色_会话_时间戳_v版本_m消息版本）
    assert messages[1]["audio_file"].startswith("audio/unknown_日常_")
    assert messages[1]["audio_file"].endswith("_v1.3.7_m1.wav")
    audio_rel = messages[1]["audio_file"]
    assert (tmp_path / sid / audio_rel).read_bytes() == b"WAVDATA"


def test_audio_filename_format_and_fields(tmp_path):
    """章节九十五：音频文件名带角色名/会话名/时间戳/应用版本/消息版本，消息写入 character 字段。"""
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session("暴行-1")
    msg = mgr.add_message(
        sid, "assistant", "你好", audio_data=b"WAV", character="暴行", message_version=2
    )
    assert msg["character"] == "暴行"
    audio_name = msg["audio_file"]
    parts = audio_name.split("/")[-1]
    assert parts.startswith("暴行_暴行-1_")
    assert "_v1.3.7_m2.wav" in parts
    # 时间戳为 8 位日期 + 6 位时间
    import re

    m = re.search(r"_(\d{8})_(\d{6})_v1.3.7_m2\.wav$", parts)
    assert m is not None
    assert (tmp_path / sid / audio_name).read_bytes() == b"WAV"


def test_audio_filename_sanitizes_illegal_chars(tmp_path):
    """章节九十五：角色/会话名含非法文件名字符时被清洗为下划线。"""
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session("会话/名:含?特殊*字符")
    msg = mgr.add_message(sid, "assistant", "hi", audio_data=b"WAV", character="角色/名:含?")
    fname = msg["audio_file"].split("/")[-1]  # 不含 audio/ 前缀
    assert ":" not in fname
    assert "/" not in fname
    assert "*" not in fname
    assert fname.startswith("角色_名_含_")  # 清洗后角色名


def test_audio_filename_truncates_long_names(tmp_path):
    """章节九十五：超长角色/会话名被截断（默认 40 字符）。"""
    mgr = ConvManager(tmp_path)
    long_name = "长" * 80
    sid = mgr.create_session(long_name)
    msg = mgr.add_message(sid, "assistant", "hi", audio_data=b"WAV", character=long_name)
    segments = msg["audio_file"].split("/")[-1].split("_")
    assert len(segments[0]) <= 40  # 角色名截断
    assert len(segments[1]) <= 40  # 会话名截断
    assert "长" in segments[0]


def test_add_message_without_character_no_field(tmp_path):
    """章节九十五：未传角色时消息不写 character 字段。"""
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    msg = mgr.add_message(sid, "assistant", "hi", audio_data=b"WAV")
    assert "character" not in msg


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
    # 章节九十五：导入后音频引用保留新命名
    assert messages[1]["audio_file"].startswith("audio/")
    assert messages[1]["audio_file"].endswith("_v1.3.7_m1.wav")
    assert (tmp_path / "convs2" / new_sid / messages[1]["audio_file"]).exists()


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


def test_search_global_role_filter(tmp_path):
    """role 筛选应按消息角色（user/assistant）过滤，而非会话名（修复）。"""
    mgr = ConvManager(tmp_path)
    s1 = mgr.create_session("会话A")
    mgr.add_message(s1, "user", "讨论钢琴")
    mgr.add_message(s1, "assistant", "钢琴很好听")

    user_only = mgr.search_global("钢琴", filters={"role": "user"})
    assert len(user_only) == 1
    assert user_only[0]["role"] == "user"

    ai_only = mgr.search_global("钢琴", filters={"role": "assistant"})
    assert len(ai_only) == 1
    assert ai_only[0]["role"] == "assistant"


def test_import_session_rejects_non_dict_messages(tmp_path):
    """messages.json 含非法消息结构（非 dict/缺 role/content）时拒绝导入（修复）。"""
    bad_zip = tmp_path / "badmsg.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("messages.json", '["abc", 123]')

    mgr = ConvManager(tmp_path / "convs")
    assert mgr.import_session(bad_zip) is None


def test_import_session_rejects_zip_bomb(tmp_path):
    """超多成员/超大的 zip 拒绝导入（zip 炸弹防护，修复）。"""
    bomb_zip = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        zf.writestr("messages.json", "[]")
        # 单文件超过 100MB 上限（用稀疏内容模拟 file_size 大）
        zf.writestr("big.bin", b"\0" * (101 * 1024 * 1024))

    mgr = ConvManager(tmp_path / "convs")
    assert mgr.import_session(bomb_zip) is None


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


# ---------- R5：msg_id 收藏 + 摘要压缩孤儿清理 ----------


def test_add_message_has_msg_id(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    msg = mgr.add_message(sid, "user", "你好")
    assert msg.get("msg_id")
    assert len(msg["msg_id"]) == 12


def test_favorite_survives_summarize_by_msg_id(tmp_path):
    mgr = ConvManager(tmp_path, max_history_rounds=1, summarize_trigger_rounds=2)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "q0")
    mgr.add_message(sid, "assistant", "a0")
    mgr.add_message(sid, "user", "q1")
    mgr.add_message(sid, "assistant", "a1")

    # 收藏最后一条（index 3）与新一条（index 2）
    assert mgr.add_favorite(sid, 3) is True

    # 摘要压缩：保留最近 1 轮（index 2,3），index 0,1 被裁剪
    mgr.maybe_summarize(sid, summarize_fn=lambda h: "摘要")
    messages = mgr.get_messages(sid)
    assert len(messages) == 2
    assert messages[0]["content"] == "q1"
    assert messages[1]["content"] == "a1"

    # 收藏的 a1 仍在 → msg_id 有效，收藏保留
    assert mgr.is_favorite(sid, 1) is True
    favs = mgr.list_favorites(sid)
    assert len(favs) == 1
    assert favs[0]["content"] == "a1"

    # 再次压缩后若被裁掉，收藏被清理
    mgr.add_message(sid, "user", "q2")
    mgr.add_message(sid, "assistant", "a2")
    mgr.add_favorite(sid, 3)
    mgr.maybe_summarize(sid, summarize_fn=lambda h: "摘要2")
    # 现在消息只剩 q2/a2，旧收藏 a1 已不存在 → 孤儿被清理
    remaining = mgr.list_favorites(sid)
    assert len(remaining) == 1
    assert remaining[0]["content"] == "a2"


def test_edit_message_preserves_history(tmp_path):
    """Q9：编辑消息内容并保留 edited_from 版本记录。"""
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    msg = mgr.add_message(sid, "assistant", "旧内容")
    updated = mgr.edit_message(sid, msg["msg_id"], "新内容")
    assert updated is not None
    assert updated["content"] == "新内容"
    assert updated["edited_from"] == ["旧内容"]
    assert mgr.get_messages(sid)[0]["content"] == "新内容"

    # prepend_versions：重新生成时记录旧回复（新内容未变时不重复记录当前内容）
    updated2 = mgr.edit_message(sid, msg["msg_id"], "第二版", prepend_versions=["第一版"])
    assert updated2["edited_from"] == ["第一版", "新内容", "旧内容"]

    # 内容未变但提供前置版本（重新生成场景）仍记录版本
    updated3 = mgr.edit_message(sid, msg["msg_id"], "第二版", prepend_versions=["旧回复"])
    assert updated3["edited_from"] == ["旧回复", "第一版", "新内容", "旧内容"]


def test_edit_message_not_found(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    assert mgr.edit_message(sid, "nonexistent", "x") is None


# ---------- R4：remove_last_message 回滚 ----------


def test_remove_last_message_rollback(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session()
    mgr.add_message(sid, "user", "你好")
    mgr.add_message(sid, "assistant", "回复", audio_data=b"WAV")

    removed = mgr.remove_last_message(sid, role="assistant")
    assert removed is not None
    assert removed["content"] == "回复"
    messages = mgr.get_messages(sid)
    assert len(messages) == 1
    # 章节九十五：删除消息时清理对应新命名音频文件
    assert not (tmp_path / sid / removed["audio_file"]).exists()

    removed2 = mgr.remove_last_message(sid, role="user")
    assert removed2["content"] == "你好"
    assert mgr.get_messages(sid) == []


def test_remove_last_message_missing_session(tmp_path):
    mgr = ConvManager(tmp_path)
    assert mgr.remove_last_message("nonexistent") is None


# ---------- R3：会话回收站 ----------


def _conv_mgr(tmp_path):
    """回收站默认取 convs_dir.parent/trash/sessions，用独立子目录保证测试隔离。"""
    return ConvManager(tmp_path / "convs")


def test_delete_moves_to_trash(tmp_path):
    mgr = _conv_mgr(tmp_path)
    sid = mgr.create_session("回收测试")
    mgr.add_message(sid, "user", "hi")

    assert mgr.delete_session(sid) is True
    assert not mgr.session_exists(sid)
    trash = mgr.list_trash()
    assert len(trash) == 1
    assert trash[0]["original_id"] == sid
    assert trash[0]["deleted_at"]


def test_restore_from_trash(tmp_path):
    mgr = _conv_mgr(tmp_path)
    sid = mgr.create_session("恢复测试")
    mgr.delete_session(sid)

    trash = mgr.list_trash()
    restored_sid = mgr.restore_from_trash(trash[0]["id"])
    assert restored_sid == sid
    assert mgr.session_exists(sid)
    assert mgr.list_trash() == []


def test_empty_trash(tmp_path):
    mgr = _conv_mgr(tmp_path)
    sid = mgr.create_session()
    mgr.delete_session(sid)
    assert len(mgr.list_trash()) == 1
    assert mgr.empty_trash() == 1
    assert mgr.list_trash() == []


def test_delete_permanent(tmp_path):
    mgr = _conv_mgr(tmp_path)
    sid = mgr.create_session()
    mgr.delete_session(sid, permanent=True)
    assert not mgr.session_exists(sid)
    assert mgr.list_trash() == []


# ---------- R8：会话元数据缓存 ----------


def test_session_meta_cached(tmp_path):
    mgr = ConvManager(tmp_path)
    sid = mgr.create_session("缓存会话")
    # 第一次 list_sessions 后元数据进入缓存
    mgr.list_sessions()
    assert sid in mgr._sessions_meta
    meta = mgr._sessions_meta[sid]
    assert meta["name"] == "缓存会话"
    # 重命名后缓存失效重建
    mgr.rename_session(sid, "新名字")
    assert mgr.list_sessions()[0]["name"] == "新名字"
