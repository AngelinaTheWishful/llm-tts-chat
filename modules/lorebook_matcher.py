"""LorebookMatcher：基于 jieba 分词 + 同义词扩展的关键词匹配引擎。"""

import jieba

DEFAULT_SYNONYMS = {
    "开心": ["高兴", "快乐", "愉快", "喜悦"],
    "难过": ["伤心", "悲伤", "忧郁", "失落"],
    "学习": ["读书", "复习", "考试", "功课"],
}


class LorebookMatcher:
    """根据用户输入匹配 lorebook 条目，返回匹配的 content 列表。"""

    def __init__(self, synonyms: dict | None = None):
        self.synonyms = synonyms or DEFAULT_SYNONYMS

    def expand_keywords(self, keywords: list[str]) -> set[str]:
        """扩展关键词为同义词集。"""
        expanded = set(keywords)
        for kw in keywords:
            if kw in self.synonyms:
                expanded.update(self.synonyms[kw])
        return expanded

    def match(self, user_input: str, lore_entries: list[dict]) -> list[str]:
        """根据用户输入匹配 lorebook 条目，返回匹配的 content 列表。"""
        words = set(jieba.lcut(user_input))

        matched: list[str] = []
        for entry in lore_entries:
            keywords = self.expand_keywords(entry.get("keywords", []))
            if words & keywords:  # 交集不为空即匹配
                content = entry.get("content", "")
                if content:
                    matched.append(content)

        return matched
