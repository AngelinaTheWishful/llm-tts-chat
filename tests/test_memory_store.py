"""MemoryStore 单元测试（章节八十四 长期记忆/RAG）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.memory_store import (
    MemoryStore,
    extract_rule_memories,
    split_summary_and_memories,
)


def test_extract_rule_memories():
    text = "我叫小明，我喜欢弹钢琴，我住在北京，这周末有空吗？我讨厌熬夜。"
    memories = extract_rule_memories(text)
    assert any("我喜欢弹钢琴" in m for m in memories)
    assert any("我住在北京" in m for m in memories)
    assert any("我讨厌熬夜" in m for m in memories)
    # 规则提取结果不包含普通问句
    assert not any("这周末有空吗" in m for m in memories)


def test_split_summary_and_memories():
    combined = "[摘要]\n聊了钢琴相关话题。\n[记忆]\n记忆：用户喜欢弹钢琴\n记忆：用户考过八级\n"
    summary, memories = split_summary_and_memories(combined)
    assert "聊了钢琴" in summary
    assert memories == ["用户喜欢弹钢琴", "用户考过八级"]


def test_split_no_memories():
    summary, memories = split_summary_and_memories("普通摘要内容")
    assert summary == "普通摘要内容"
    assert memories == []


def test_add_and_recall(tmp_path):
    store = MemoryStore(tmp_path / "memories")
    assert store.add_entry("用户喜欢弹钢琴", scope="character", key="学姐") is True
    assert store.add_entry("用户住在北京", scope="character", key="学姐") is True

    # 去重：相同文本不重复入库
    assert store.add_entry("用户喜欢弹钢琴", scope="character", key="学姐") is False

    recalled = store.recall("你会弹钢琴吗", scope="character", key="学姐", limit=5)
    assert "用户喜欢弹钢琴" in recalled
    assert "用户住在北京" not in recalled

    assert store.count(scope="character", key="学姐") == 2


def test_scope_isolation(tmp_path):
    store = MemoryStore(tmp_path / "memories")
    store.add_entry("用户喜欢猫", scope="character", key="角色A")
    # 角色 B 与全局不受角色 A 影响
    assert store.recall("喜欢猫", scope="character", key="角色B") == []
    assert store.recall("喜欢猫", scope="global", key="global") == []

    store.add_entry("用户喜欢猫", scope="global", key="global")
    assert store.recall("喜欢猫", scope="global", key="global") == ["用户喜欢猫"]


def test_clear(tmp_path):
    store = MemoryStore(tmp_path / "memories")
    store.add_entry("用户喜欢猫", scope="character", key="角色A")
    assert store.clear(scope="character", key="角色A") == 1
    assert store.count(scope="character", key="角色A") == 0


def test_safe_key(tmp_path):
    store = MemoryStore(tmp_path / "memories")
    store.add_entry("用户喜欢猫", scope="character", key="a/b\\c:d*e")
    assert (tmp_path / "memories" / "character" / "a_b_c_d_e" / "memories.json").exists()


def test_scope_sanitized(tmp_path):
    """scope 含路径穿越字符时被净化，防止越界写（修复）。"""
    store = MemoryStore(tmp_path / "memories")
    store.add_entry("用户喜欢猫", scope="../../evil", key="x")
    # 净化后落在 memories/evil/x/memories.json，而非越界目录
    assert (tmp_path / "memories" / "evil" / "x" / "memories.json").exists()
    assert not (tmp_path.parent / "evil").exists()


def test_concurrent_add_entries(tmp_path):
    """并发写入记忆不丢更新、不写坏 JSON（并发锁修复）。

    20 个线程写相同文本：去重后应恰好 1 条；若读改写无锁会出现重复/写坏。
    """
    import threading

    store = MemoryStore(tmp_path / "memories")
    errors = []

    def worker(_):
        try:
            store.add_entry("用户喜欢弹钢琴", scope="character", key="并发")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert store.count(scope="character", key="并发") == 1  # 去重后仅 1 条，无重复/写坏
