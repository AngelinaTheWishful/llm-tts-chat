"""LorebookMatcher 单元测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.lorebook_matcher import LorebookMatcher


def test_keyword_match():
    matcher = LorebookMatcher()
    entries = [
        {"keywords": ["钢琴", "音乐"], "content": "学姐会弹钢琴"},
        {"keywords": ["弟弟"], "content": "学姐有个弟弟"},
    ]
    result = matcher.match("我想学钢琴", entries)
    assert "学姐会弹钢琴" in result
    assert "学姐有个弟弟" not in result


def test_synonym_expand():
    matcher = LorebookMatcher()
    expanded = matcher.expand_keywords(["开心"])
    assert "高兴" in expanded
    assert "快乐" in expanded


def test_no_match_returns_empty():
    matcher = LorebookMatcher()
    entries = [{"keywords": ["钢琴"], "content": "学姐会弹钢琴"}]
    assert matcher.match("今天天气不错", entries) == []
