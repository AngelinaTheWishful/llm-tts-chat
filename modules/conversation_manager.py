"""ConvManager：会话管理（章节五 5.5 / 六十三）。

- 会话存储：conversations/{session_id}/messages.json + summary.txt + name.txt + audio/
- 消息追加（含音频保存）
- 上下文构建（摘要 + 最近 N 轮）
- 摘要压缩触发（总轮数超阈值）
- 会话导出/导入（zip，路径穿越防护）
"""

import json
import random
import shutil
import string
import zipfile
from datetime import datetime
from pathlib import Path

from modules.base_manager import BaseManager


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def generate_session_id() -> str:
    """生成会话 ID：时间戳 + 4 位随机。"""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"sess_{_now_stamp()}_{suffix}"


class ConvManager(BaseManager):
    """会话管理。"""

    def __init__(
        self,
        convs_dir: str | Path,
        max_history_rounds: int = 4,
        summarize_trigger_rounds: int = 20,
    ):
        super().__init__("conversation")
        self.dir = Path(convs_dir)
        self.dir.mkdir(exist_ok=True)
        self.max_history_rounds = max_history_rounds
        self.summarize_trigger_rounds = summarize_trigger_rounds
        # 全量内存缓存（章节二十五）：启动/首次读取时加载，写操作同步更新
        self._messages_cache: dict[str, list[dict]] = {}

    def load_all(self) -> None:
        """启动时将所有会话消息加载到内存缓存。"""
        for sdir in self.dir.iterdir():
            if sdir.is_dir():
                self._read_messages(sdir)

    # ---------- 会话生命周期 ----------

    def list_sessions(self) -> list[dict]:
        """返回 [{id, name, msg_count, created_at, updated_at}, ...]。"""
        sessions: list[dict] = []
        for sdir in sorted(self.dir.iterdir(), reverse=True):
            if not sdir.is_dir():
                continue
            messages = self._read_messages(sdir)
            sessions.append(
                {
                    "id": sdir.name,
                    "name": self._read_name(sdir),
                    "msg_count": len(messages),
                    "created_at": self._read_text(sdir / "created_at.txt") or sdir.name,
                    "updated_at": self._read_text(sdir / "updated_at.txt") or "",
                }
            )
        return sessions

    def create_session(self, name: str = "") -> str:
        """创建新会话，返回 session_id。"""
        session_id = generate_session_id()
        sdir = self.dir / session_id
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "audio").mkdir(exist_ok=True)
        self._write_json(sdir / "messages.json", [])
        self._write_text(sdir / "summary.txt", "")
        self._write_text(sdir / "name.txt", name or "新会话")
        self._write_text(sdir / "created_at.txt", _now_stamp())
        self._write_text(sdir / "updated_at.txt", _now_stamp())
        self._messages_cache[session_id] = []
        self.log("info", f"会话已创建: {session_id} ({name})")
        return session_id

    def delete_session(self, session_id: str) -> bool:
        """删除会话文件夹（含所有音频）。"""
        sdir = self.dir / session_id
        if not sdir.exists():
            return False
        shutil.rmtree(str(sdir), ignore_errors=True)
        self._messages_cache.pop(session_id, None)
        self.log("info", f"会话已删除: {session_id}")
        return True

    def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名会话。"""
        sdir = self.dir / session_id
        if not sdir.exists():
            return False
        self._write_text(sdir / "name.txt", new_name)
        return True

    def session_exists(self, session_id: str) -> bool:
        return (self.dir / session_id).exists()

    # ---------- 消息 ----------

    def get_messages(self, session_id: str) -> list[dict]:
        """加载 messages.json。"""
        sdir = self.dir / session_id
        if not sdir.exists():
            return []
        return self._read_messages(sdir)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        audio_data: bytes | None = None,
    ) -> dict:
        """追加消息。有 audio_data 时保存为 audio/msg_N.wav。"""
        sdir = self.dir / session_id
        if not sdir.exists():
            raise FileNotFoundError(f"会话不存在: {session_id}")

        messages = self._read_messages(sdir)
        msg_index = len(messages)

        message: dict = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        if audio_data:
            audio_dir = sdir / "audio"
            audio_dir.mkdir(exist_ok=True)
            audio_file = f"audio/msg_{msg_index}.wav"
            (audio_dir / f"msg_{msg_index}.wav").write_bytes(audio_data)
            message["audio_file"] = audio_file

        messages.append(message)
        self._write_json(sdir / "messages.json", messages)
        self._messages_cache[session_id] = messages
        self._write_text(sdir / "updated_at.txt", _now_stamp())
        return message

    # ---------- 上下文构建 / 摘要 ----------

    def build_llm_context(self, session_id: str) -> tuple[str, list[dict]]:
        """构建 LLM 上下文：读取摘要 + 取最近 N 轮消息，返回 (summary, recent_messages)。"""
        sdir = self.dir / session_id
        summary = ""
        if sdir.exists():
            summary = self._read_text(sdir / "summary.txt")

        messages = self.get_messages(session_id)
        recent_count = self.max_history_rounds * 2  # 每轮含 user + assistant
        recent_messages = messages[-recent_count:] if recent_count > 0 else messages

        return summary, recent_messages

    def total_rounds(self, session_id: str) -> int:
        """统计会话轮数（user 消息数）。"""
        messages = self.get_messages(session_id)
        return sum(1 for m in messages if m.get("role") == "user")

    def maybe_summarize(self, session_id: str, summarize_fn=None) -> str:
        """总轮数超阈值时触发摘要压缩，返回新摘要（未触发返回空串）。"""
        if self.total_rounds(session_id) < self.summarize_trigger_rounds:
            return ""

        sdir = self.dir / session_id
        messages = self.get_messages(session_id)
        if not messages or summarize_fn is None:
            return ""

        old_summary = self._read_text(sdir / "summary.txt")
        history = messages[: -self.max_history_rounds * 2]  # 除最近 N 轮外的全部
        source = history if history else messages

        if old_summary:
            history_for_summary = [{"role": "user", "content": f"已有摘要：{old_summary}"}, *source]
        else:
            history_for_summary = source

        new_summary = summarize_fn(history_for_summary)
        self._write_text(sdir / "summary.txt", new_summary)

        # 仅保留最近 N 轮，其余压缩进摘要
        kept = messages[-self.max_history_rounds * 2 :]
        self._write_json(sdir / "messages.json", kept)
        self._messages_cache[session_id] = kept
        self.log("info", f"会话摘要已更新: {session_id}")
        return new_summary

    def update_summary(self, session_id: str, summary: str) -> None:
        sdir = self.dir / session_id
        if sdir.exists():
            self._write_text(sdir / "summary.txt", summary)

    # ---------- 收藏（章节六十一） ----------

    def _favorites_path(self, session_id: str) -> Path:
        return self.dir / session_id / "favorites.json"

    def list_favorites(self, session_id: str) -> list[dict]:
        """返回收藏列表。"""
        path = self._favorites_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def add_favorite(
        self, session_id: str, msg_index: int, tags: list[str] | None = None, note: str = ""
    ) -> bool:
        """收藏指定消息。"""
        messages = self.get_messages(session_id)
        if msg_index < 0 or msg_index >= len(messages):
            return False
        msg = messages[msg_index]

        favorites = self.list_favorites(session_id)
        if any(f.get("msg_index") == msg_index for f in favorites):
            return False

        favorites.append(
            {
                "msg_index": msg_index,
                "version_index": 0,
                "content": msg.get("content", ""),
                "audio_file": msg.get("audio_file", ""),
                "timestamp": msg.get("timestamp", ""),
                "tags": tags or [],
                "note": note,
            }
        )
        self._write_json(self._favorites_path(session_id), favorites)
        return True

    def remove_favorite(self, session_id: str, msg_index: int) -> bool:
        favorites = self.list_favorites(session_id)
        remaining = [f for f in favorites if f.get("msg_index") != msg_index]
        if len(remaining) == len(favorites):
            return False
        self._write_json(self._favorites_path(session_id), remaining)
        return True

    def is_favorite(self, session_id: str, msg_index: int) -> bool:
        return any(f.get("msg_index") == msg_index for f in self.list_favorites(session_id))

    # ---------- 搜索（章节七十三） ----------

    def search_in_session(self, session_id: str, query: str) -> list[dict]:
        """在当前会话搜索消息。"""
        query = query.strip().lower()
        if not query:
            return []
        messages = self.get_messages(session_id)
        results = []
        for i, msg in enumerate(messages):
            if query in msg.get("content", "").lower():
                results.append(
                    {
                        "index": i,
                        "session_id": session_id,
                        "role": msg.get("role", ""),
                        "content": msg.get("content", ""),
                        "timestamp": msg.get("timestamp", ""),
                        "context_before": messages[i - 1].get("content", "") if i > 0 else "",
                        "context_after": (
                            messages[i + 1].get("content", "") if i < len(messages) - 1 else ""
                        ),
                    }
                )
        return results

    def search_global(self, query: str, filters: dict | None = None) -> list[dict]:
        """跨所有会话搜索（支持 角色/日期/收藏 筛选）。"""
        filters = filters or {}
        results = []
        for session in self.list_sessions():
            for r in self.search_in_session(session["id"], query):
                r["session_name"] = session["name"]
                results.append(r)

        # 筛选
        if filters.get("is_favorite"):
            results = [r for r in results if self.is_favorite(r["session_id"], r["index"])]
        if filters.get("date_from"):
            results = [r for r in results if r.get("timestamp", "") >= filters["date_from"]]
        if filters.get("role"):
            results = [r for r in results if r["session_name"] == filters["role"]]

        return sorted(results, key=lambda x: x.get("timestamp", ""), reverse=True)

    # ---------- 统计（章节六十八） ----------

    def get_session_stats(self, session_id: str) -> dict:
        """单会话统计。"""
        messages = self.get_messages(session_id)
        user_count = sum(1 for m in messages if m.get("role") == "user")
        ai_count = sum(1 for m in messages if m.get("role") == "assistant")
        favorites = self.list_favorites(session_id)
        audio_count = sum(1 for m in messages if m.get("audio_file"))
        return {
            "session_id": session_id,
            "name": self._read_name(self.dir / session_id),
            "msg_count": len(messages),
            "user_count": user_count,
            "ai_count": ai_count,
            "favorite_count": len(favorites),
            "audio_count": audio_count,
        }

    def get_global_stats(self) -> dict:
        """全局统计看板。"""
        sessions = self.list_sessions()
        total_msgs = 0
        total_favorites = 0
        total_audio = 0
        most_active_session = None
        most_active_msgs = 0

        for s in sessions:
            stats = self.get_session_stats(s["id"])
            total_msgs += stats["msg_count"]
            total_favorites += stats["favorite_count"]
            total_audio += stats["audio_count"]
            if stats["msg_count"] > most_active_msgs:
                most_active_msgs = stats["msg_count"]
                most_active_session = stats

        return {
            "session_count": len(sessions),
            "total_msgs": total_msgs,
            "total_favorites": total_favorites,
            "total_audio": total_audio,
            "most_active_session": most_active_session,
        }

    # ---------- 导出 / 导入 ----------

    def export_session(self, session_id: str) -> str | None:
        """将会话导出为 zip（messages.json + audio/*.wav），返回 zip 路径。"""
        sdir = self.dir / session_id
        if not sdir.exists():
            return None

        exports_dir = self.dir.parent / "exports"
        exports_dir.mkdir(exist_ok=True)
        zip_path = exports_dir / f"{session_id}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            messages_file = sdir / "messages.json"
            if messages_file.exists():
                zf.write(messages_file, "messages.json")
            audio_dir = sdir / "audio"
            if audio_dir.exists():
                for f in sorted(audio_dir.glob("*.wav")):
                    zf.write(f, f"audio/{f.name}")

        return str(zip_path)

    def import_session(self, zip_path: str | Path) -> str | None:
        """从 zip 导入会话，返回新 session_id（路径穿越防护）。"""
        zip_path = Path(zip_path)
        session_id = generate_session_id()
        sdir = self.dir / session_id
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "audio").mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                member_path = Path(member)
                # 路径穿越防护
                if member_path.is_absolute() or ".." in member_path.parts:
                    self.log("warning", f"跳过不安全路径: {member}")
                    continue
                target = (sdir / member_path).resolve()
                if not str(target).startswith(str(sdir.resolve())):
                    self.log("warning", f"跳过越界路径: {member}")
                    continue
                zf.extract(member, sdir)

        messages_file = sdir / "messages.json"
        if not messages_file.exists():
            self.log("error", f"导入的会话缺少 messages.json: {zip_path}")
            shutil.rmtree(str(sdir), ignore_errors=True)
            return None
        try:
            messages = json.loads(messages_file.read_text(encoding="utf-8"))
            if not isinstance(messages, list):
                raise ValueError("messages.json 不是数组")
        except (json.JSONDecodeError, ValueError):
            self.log("error", f"导入的会话 messages.json 格式无效: {zip_path}")
            shutil.rmtree(str(sdir), ignore_errors=True)
            return None

        self._write_text(sdir / "name.txt", f"导入会话 {_now_stamp()}")
        self._write_text(sdir / "created_at.txt", _now_stamp())
        self._write_text(sdir / "updated_at.txt", _now_stamp())
        self._messages_cache[session_id] = messages
        self.log("info", f"会话已导入: {session_id}")
        return session_id

    # ---------- 文件读写工具 ----------

    def _read_messages(self, sdir: Path) -> list[dict]:
        """读取会话消息（优先走内存缓存）。"""
        sid = sdir.name
        if sid in self._messages_cache:
            return self._messages_cache[sid]

        path = sdir / "messages.json"
        data: list[dict] = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                data = loaded if isinstance(loaded, list) else []
            except (json.JSONDecodeError, OSError):
                data = []
        self._messages_cache[sid] = data
        return data

    @staticmethod
    def _read_name(sdir: Path) -> str:
        return ConvManager._read_text(sdir / "name.txt") or sdir.name

    @staticmethod
    def _read_text(path: Path) -> str:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    @staticmethod
    def _write_json(path: Path, data) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
