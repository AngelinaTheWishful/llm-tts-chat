"""MemoryStore：长期记忆 / RAG（章节八十四）。

- 记忆库目录 memories/
  - 角色级: memories/character/<角色名>/memories.json
  - 全局:   memories/global/memories.json
- 规则提取（默认）+ 可选 LLM 提取（extract_with_llm，摘要时顺带，不额外调用）
- 召回：jieba 分词 + 关键词重叠打分，Top-N
- 去重：相同文本或关键词重叠 >= 2 跳过
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import jieba

from modules.base_manager import BaseManager

RULE_PATTERNS = [
    r"我喜欢[^，。！？；,!?;]{1,24}",
    r"我不喜欢[^，。！？；,!?;]{1,24}",
    r"我讨厌[^，。！？；,!?;]{1,24}",
    r"我爱[^，。！？；,!?;]{1,24}",
    r"我住在[^，。！？；,!?;]{1,24}",
    r"我今年[^，。！？；,!?;]{1,24}",
    r"我出生在[^，。！？；,!?;]{1,24}",
    r"我是[^，。！？；,!?;]{1,24}",
    r"我经常[^，。！？；,!?;]{1,24}",
    r"我每天[^，。！？；,!?;]{1,24}",
    r"我想去[^，。！？；,!?;]{1,24}",
    r"我的[^，。！？；,!?;]{1,24}",
]

STOPWORDS = {
    "我",
    "你",
    "他",
    "她",
    "我们",
    "你们",
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "也",
    "很",
    "都",
    "就",
    "不",
    "这",
    "那",
    "有",
    "会",
    "要",
    "想",
}


def extract_rule_memories(text: str) -> list[str]:
    """规则提取用户陈述，返回去重后的记忆文本列表。"""
    memories = []
    for pattern in RULE_PATTERNS:
        for m in re.findall(pattern, text):
            statement = m.strip()
            if 4 <= len(statement) <= 60 and statement not in memories:
                memories.append(statement)
    return memories


def split_summary_and_memories(text: str) -> tuple[str, list[str]]:
    """解析 '[摘要]... [记忆]记忆：...' 组合输出，返回 (summary, memories)。

    用于 extract_with_llm：摘要调用顺带提取记忆（不额外调用 LLM）。
    """
    text = text or ""
    marker = "[记忆]"
    if marker in text:
        summary_part, mem_part = text.split(marker, 1)
        memories = [
            line.strip()
            for line in mem_part.splitlines()
            if line.strip() and not line.strip().startswith("[")
        ]
        memories = [re.sub(r"^记忆[：:]\s*", "", m) for m in memories]
        return summary_part.strip(), memories
    return text.strip(), []


class MemoryStore(BaseManager):
    """长期记忆库（角色级 + 全局）。"""

    def __init__(self, root: str | Path | None = None):
        super().__init__("memory")
        self.root = Path(root) if root else (Path(__file__).resolve().parent.parent / "memories")

    # ---------- 文件读写 ----------

    @staticmethod
    def _safe_key(key: str) -> str:
        return re.sub(r'[\\/:*?"<>|\s]+', "_", key or "").strip("_") or "default"

    def _path(self, scope: str, key: str) -> Path:
        return self.root / scope / self._safe_key(key) / "memories.json"

    def _load(self, scope: str, key: str) -> list[dict]:
        p = self._path(scope, key)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save(self, scope: str, key: str, entries: list[dict]) -> None:
        p = self._path(scope, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 关键词 / 提取 ----------

    @classmethod
    def _keywords(cls, text: str) -> list[str]:
        try:
            tokens = set(jieba.lcut(text or ""))
        except Exception:
            tokens = set(text or "")
        return [w for w in tokens if len(w) >= 2 and w not in STOPWORDS]

    # ---------- 记忆操作 ----------

    def add_entry(
        self,
        text: str,
        scope: str = "character",
        key: str = "",
        source_session: str = "",
    ) -> bool:
        """新增一条记忆（去重后返回是否写入）。"""
        if not text or not text.strip():
            return False
        text = text.strip()
        kws = self._keywords(text)
        entries = self._load(scope, key)
        for e in entries:
            if e.get("text") == text:
                return False
            overlap = len(set(e.get("keywords", [])) & set(kws))
            if overlap >= 2:
                return False
        now = datetime.now().isoformat(timespec="seconds")
        entries.append(
            {
                "id": uuid.uuid4().hex[:12],
                "text": text,
                "keywords": kws,
                "source_session": source_session,
                "created_at": now,
                "updated_at": now,
                "hit_count": 0,
            }
        )
        self._save(scope, key, entries)
        self.log("info", f"新增记忆[{scope}/{key}]: {text}")
        return True

    def add_memories(
        self,
        texts: list[str],
        scope: str = "character",
        key: str = "",
        source_session: str = "",
    ) -> int:
        """批量新增记忆，返回新增数量。"""
        added = 0
        for t in texts or []:
            if self.add_entry(t, scope=scope, key=key, source_session=source_session):
                added += 1
        return added

    def recall(
        self,
        query: str,
        scope: str = "character",
        key: str = "",
        limit: int = 5,
    ) -> list[str]:
        """按关键词重叠召回相关记忆文本，Top-N。"""
        entries = self._load(scope, key)
        if not entries or not query:
            return []
        q_tokens = set(self._keywords(query))
        scored = []
        for e in entries:
            score = len(q_tokens & set(e.get("keywords", [])))
            if score > 0:
                scored.append((score, e))
        if not scored:
            return []
        scored.sort(key=lambda x: (x[0], x[1].get("updated_at", "")), reverse=True)
        top = [e for _, e in scored[:limit]]
        for e in top:
            e["hit_count"] = e.get("hit_count", 0) + 1
        self._save(scope, key, entries)
        return [e["text"] for e in top]

    def list_entries(self, scope: str = "character", key: str = "") -> list[dict]:
        return self._load(scope, key)

    def clear(self, scope: str = "character", key: str = "") -> int:
        """清空指定记忆库，返回删除条数。"""
        entries = self._load(scope, key)
        if entries:
            self._path(scope, key).unlink(missing_ok=True)
        return len(entries)

    def count(self, scope: str = "character", key: str = "") -> int:
        return len(self._load(scope, key))
