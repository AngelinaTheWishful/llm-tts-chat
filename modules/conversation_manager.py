"""ConvManager：会话管理（章节五 5.5 / 六十三）。

- 会话存储：conversations/{session_id}/messages.json + summary.txt + name.txt + audio/
- 消息追加（含音频保存）
- 上下文构建（摘要 + 最近 N 轮）
- 摘要压缩触发（总轮数超阈值）
- 会话导出/导入（zip，路径穿越防护）
"""

import json
import random
import re
import shutil
import string
import threading
import uuid
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
        trash_dir: str | Path | None = None,
    ):
        super().__init__("conversation")
        self.dir = Path(convs_dir)
        self.dir.mkdir(exist_ok=True)
        self.trash_dir = Path(trash_dir) if trash_dir else (self.dir.parent / "trash" / "sessions")
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.max_history_rounds = max_history_rounds
        self.summarize_trigger_rounds = summarize_trigger_rounds
        # R2: 全写操作共用写锁（Gradio 队列并发时保护 messages.json 等文件）
        self._lock = threading.RLock()
        # 全量内存缓存（章节二十五）：启动/首次读取时加载，写操作同步更新
        self._messages_cache: dict[str, list[dict]] = {}
        # R8: 会话元数据缓存（name/created_at/updated_at），避免每次列表全量读文件
        self._sessions_meta: dict[str, dict] = {}

    def load_all(self) -> None:
        """启动时将所有会话消息加载到内存缓存。"""
        for sdir in self.dir.iterdir():
            if sdir.is_dir():
                self._read_messages(sdir)
                self._read_meta(sdir)

    # ---------- 会话生命周期 ----------

    def list_sessions(self) -> list[dict]:
        """返回 [{id, name, msg_count, created_at, updated_at}, ...]（元数据走内存缓存 R8）。"""
        sessions: list[dict] = []
        for sdir in sorted(self.dir.iterdir(), reverse=True):
            if not sdir.is_dir():
                continue
            meta = self._read_meta(sdir)
            sessions.append(
                {
                    "id": sdir.name,
                    "name": meta["name"],
                    "msg_count": len(self._read_messages(sdir)),
                    "created_at": meta["created_at"],
                    "updated_at": meta["updated_at"],
                }
            )
        return sessions

    def _read_meta(self, sdir: Path) -> dict:
        """读取/缓存会话元数据。"""
        sid = sdir.name
        if sid in self._sessions_meta:
            return self._sessions_meta[sid]
        meta = {
            "name": self._read_name(sdir),
            "created_at": self._read_text(sdir / "created_at.txt") or sdir.name,
            "updated_at": self._read_text(sdir / "updated_at.txt") or "",
        }
        self._sessions_meta[sid] = meta
        return meta

    def _invalidate_meta(self, session_id: str) -> None:
        self._sessions_meta.pop(session_id, None)

    def create_session(self, name: str = "") -> str:
        """创建新会话，返回 session_id。"""
        with self._lock:
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
            self._invalidate_meta(session_id)
            self.log("info", f"会话已创建: {session_id} ({name})")
            return session_id

    def delete_session(self, session_id: str, permanent: bool = False) -> bool:
        """删除会话。

        - permanent=False（默认）：移入回收站 trash/sessions/（带时间戳，R3），可恢复
        - permanent=True：直接删除（清空回收站时使用）
        """
        with self._lock:
            sdir = self.dir / session_id
            if not sdir.exists():
                return False
            if permanent:
                shutil.rmtree(str(sdir), ignore_errors=True)
            else:
                target = self.trash_dir / f"{session_id}_deleted_{_now_stamp()}"
                shutil.move(str(sdir), str(target))
                self.log("info", f"会话已删除（移入回收站）: {session_id}")
            self._messages_cache.pop(session_id, None)
            self._invalidate_meta(session_id)
            return True

    # ---------- 会话回收站（R3） ----------

    def _trash_item(self, path: Path) -> dict:
        """解析回收站项元数据。"""
        stamp = ""
        name_parts = path.name.rsplit("_deleted_", 1)
        original_sid = name_parts[0] if name_parts else path.name
        if len(name_parts) == 2:
            stamp = name_parts[1]
        deleted_at = ""
        try:
            deleted_at = datetime.strptime(stamp, "%Y%m%d_%H%M%S").isoformat()
        except ValueError:
            deleted_at = ""
        return {
            "id": path.name,
            "original_id": original_sid,
            "deleted_at": deleted_at,
            "size": sum(f.stat().st_size for f in path.rglob("*") if f.is_file()),
        }

    def list_trash(self) -> list[dict]:
        """列出回收站会话。"""
        if not self.trash_dir.exists():
            return []
        items = []
        for p in sorted(self.trash_dir.iterdir(), reverse=True):
            if p.is_dir():
                items.append(self._trash_item(p))
        return items

    def restore_from_trash(self, trash_id: str) -> str | None:
        """从回收站恢复会话，返回新的 session_id。"""
        with self._lock:
            src = self.trash_dir / trash_id
            if not src.exists():
                return None
            original_sid = self._trash_item(src)["original_id"]
            target = self.dir / original_sid
            if target.exists():
                original_sid = f"{original_sid}_restored_{_now_stamp()}"
                target = self.dir / original_sid
            shutil.move(str(src), str(target))
            self._invalidate_meta(original_sid)
            self.log("info", f"会话已从回收站恢复: {original_sid}")
            return original_sid

    def empty_trash(self, older_than_days: int | None = None) -> int:
        """清空回收站，可仅清理超过 N 天的项，返回删除数量。"""
        removed = 0
        with self._lock:
            for p in self.trash_dir.iterdir():
                if not p.is_dir():
                    continue
                if older_than_days is not None:
                    stamp = self._trash_item(p)["deleted_at"]
                    try:
                        deleted = datetime.fromisoformat(stamp)
                    except ValueError:
                        continue
                    if (datetime.now() - deleted).days < older_than_days:
                        continue
                shutil.rmtree(str(p), ignore_errors=True)
                removed += 1
        if removed:
            self.log("info", f"回收站清理完成: {removed} 项")
        return removed

    def trash_expired(self, days: int = 30) -> list[dict]:
        """返回回收站中已超过 days 天的项（用于 UI 提醒用户清理，R3）。"""
        expired = []
        now = datetime.now()
        for item in self.list_trash():
            if not item["deleted_at"]:
                continue
            try:
                deleted = datetime.fromisoformat(item["deleted_at"])
            except ValueError:
                continue
            if (now - deleted).days >= days:
                expired.append(item)
        return expired

    def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名会话。"""
        with self._lock:
            sdir = self.dir / session_id
            if not sdir.exists():
                return False
            self._write_text(sdir / "name.txt", new_name)
            self._invalidate_meta(session_id)
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
        character: str = "",
        message_version: int = 1,
    ) -> dict:
        """追加消息。有 audio_data 时按新命名规范保存音频（章节九十五）。

        音频命名：`audio/{角色名}_{会话名}_{合成时间}_v{应用版本}_m{消息版本}.wav`，
        合成时间为落盘时刻（YYYYMMDD_HHMMSS）；消息写入 `character` 字段。
        每条消息分配唯一 msg_id（R5）。
        """
        with self._lock:
            sdir = self.dir / session_id
            if not sdir.exists():
                raise FileNotFoundError(f"会话不存在: {session_id}")

            messages = self._read_messages(sdir)

            message: dict = {
                "msg_id": uuid.uuid4().hex[:12],
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            if character:
                message["character"] = character

            if audio_data:
                audio_dir = sdir / "audio"
                audio_dir.mkdir(exist_ok=True)
                audio_name = self._audio_filename(sdir, character, int(message_version or 1))
                (audio_dir / audio_name).write_bytes(audio_data)
                message["audio_file"] = f"audio/{audio_name}"

            messages.append(message)
            self._write_json(sdir / "messages.json", messages)
            self._messages_cache[session_id] = messages
            self._write_text(sdir / "updated_at.txt", _now_stamp())
            self._invalidate_meta(session_id)
            return message

    @staticmethod
    def _audio_filename(sdir: Path, character: str, message_version: int = 1) -> str:
        """生成音频文件名（章节九十五）：{角色}_{会话}_{时间戳}_v{版本}_m{消息版本}.wav。"""
        from modules.version import APP_VERSION

        char = ConvManager._sanitize_filename(character) or "unknown"
        session_name = ConvManager._read_name(sdir)
        sess = ConvManager._sanitize_filename(session_name) or "session"
        ts = _now_stamp()
        return f"{char}_{sess}_{ts}_{APP_VERSION}_m{int(message_version or 1)}.wav"

    @staticmethod
    def _sanitize_filename(name: str, limit: int = 40) -> str:
        """清洗文件名非法字符（\\ / : * ? " < > | 及控制字符）并截断，用于音频命名。"""
        cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name or ""))
        cleaned = cleaned.strip().strip(".").replace("..", "_")
        return cleaned[:limit]

    def remove_last_message(self, session_id: str, role: str | None = None) -> dict | None:
        """删除最后一条消息（R4：LLM 失败时回滚刚保存的用户消息）。

        从后向前查找 role 匹配的消息并删除，含对应音频文件清理。
        """
        with self._lock:
            sdir = self.dir / session_id
            if not sdir.exists():
                return None
            messages = self._read_messages(sdir)
            target_idx = None
            for i in range(len(messages) - 1, -1, -1):
                if role is None or messages[i].get("role") == role:
                    target_idx = i
                    break
            if target_idx is None:
                return None
            removed = messages.pop(target_idx)
            audio_file = removed.get("audio_file")
            if audio_file:
                audio_path = sdir / audio_file
                audio_path.unlink(missing_ok=True)
            self._write_json(sdir / "messages.json", messages)
            self._messages_cache[session_id] = messages
            self._write_text(sdir / "updated_at.txt", _now_stamp())
            self._invalidate_meta(session_id)
            self.log("debug", f"已删除消息（回滚）: {session_id} role={role}")
            return removed

    def find_message_index(self, session_id: str, msg_id: str) -> int:
        """按 msg_id 查找消息下标，未找到返回 -1。"""
        messages = self.get_messages(session_id)
        for i, m in enumerate(messages):
            if m.get("msg_id") == msg_id:
                return i
        return -1

    def edit_message(
        self, session_id: str, msg_id: str, new_content: str, prepend_versions: list | None = None
    ) -> dict | None:
        """编辑指定消息内容（Q9）。原内容保留在 edited_from，便于追溯。

        prepend_versions：可选，将历史版本前置到 edited_from（重新生成时记录旧回复）。
        msg_id 为空时编辑最后一条消息（兼容导入会话无 msg_id 的情况）。
        """
        with self._lock:
            sdir = self.dir / session_id
            if not sdir.exists():
                return None
            messages = self._read_messages(sdir)
            if not messages:
                return None
            # 无 msg_id（如导入会话）时定位最后一条消息
            targets = [m for m in messages if m.get("msg_id") == msg_id] if msg_id else []
            if not targets and not msg_id:
                targets = [messages[-1]]
            if not targets:
                return None
            m = targets[0]
            if not m.get("msg_id"):
                m["msg_id"] = uuid.uuid4().hex[:12]
            original = m.get("content", "")
            versions = list(prepend_versions or [])
            if original != new_content:
                if original not in versions:
                    versions.append(original)
                m["content"] = new_content
                m["edited_at"] = datetime.now().isoformat(timespec="seconds")
            # 即使内容未变，也记录前置版本（重新生成时旧回复）
            if versions:
                m["edited_from"] = versions + m.get("edited_from", [])
                self._write_json(sdir / "messages.json", messages)
                self._messages_cache[session_id] = messages
                self._write_text(sdir / "updated_at.txt", _now_stamp())
                self._invalidate_meta(session_id)
            self.log("info", f"消息已编辑: {session_id} msg_id={msg_id}")
            return m

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
        with self._lock:
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
                history_for_summary = [
                    {"role": "user", "content": f"已有摘要：{old_summary}"},
                    *source,
                ]
            else:
                history_for_summary = source

            new_summary = summarize_fn(history_for_summary)
            if not new_summary or not new_summary.strip():
                # 摘要为空（如 LLM 静默失败）时不截断历史，避免数据永久丢失
                self.log("warning", f"摘要结果为空，跳过压缩: {session_id}")
                return ""
            self._write_text(sdir / "summary.txt", new_summary)

            # 仅保留最近 N 轮，其余压缩进摘要
            kept = messages[-self.max_history_rounds * 2 :]
            self._write_json(sdir / "messages.json", kept)
            self._messages_cache[session_id] = kept
            self._invalidate_meta(session_id)
            # R5：清理已不存在消息的收藏（收藏内保留内容副本）
            self._prune_orphan_favorites(session_id)
            self.log("info", f"会话摘要已更新: {session_id}")
            return new_summary

    def _prune_orphan_favorites(self, session_id: str) -> None:
        """删除引用已不存在消息（msg_id/index）的收藏条目（R5）。"""
        path = self._favorites_path(session_id)
        if not path.exists():
            return
        messages = self.get_messages(session_id)
        known_msg_ids = {m.get("msg_id") for m in messages}
        kept = []
        for fav in self.list_favorites(session_id):
            msg_id = fav.get("msg_id")
            idx = fav.get("msg_index")
            if msg_id:
                if msg_id in known_msg_ids:
                    kept.append(fav)
            elif isinstance(idx, int) and 0 <= idx < len(messages):
                # 旧版 index 型收藏：消息仍在则保留并升级为 msg_id
                if messages[idx].get("msg_id"):
                    fav["msg_id"] = messages[idx]["msg_id"]
                kept.append(fav)
            else:
                self.log("debug", f"清理孤儿收藏: {session_id} msg_index={idx}")
        if len(kept) != len(self.list_favorites(session_id)):
            self._write_json(path, kept)

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

    def _message_msg_id(self, session_id: str, msg_index: int) -> str | None:
        """返回指定下标消息的 msg_id（不存在返回 None）。"""
        messages = self.get_messages(session_id)
        if msg_index < 0 or msg_index >= len(messages):
            return None
        return messages[msg_index].get("msg_id")

    def add_favorite(
        self, session_id: str, msg_index: int, tags: list[str] | None = None, note: str = ""
    ) -> bool:
        """收藏指定消息（以 msg_id 为唯一标识，R5）。"""
        with self._lock:
            messages = self.get_messages(session_id)
            if msg_index < 0 or msg_index >= len(messages):
                return False
            msg = messages[msg_index]
            msg_id = msg.get("msg_id")

            favorites = self.list_favorites(session_id)
            # 去重以 msg_id 为准（msg_index 在摘要压缩后会失效，不可作为主键）
            if msg_id:
                if any(f.get("msg_id") == msg_id for f in favorites):
                    return False
            elif any(f.get("msg_index") == msg_index for f in favorites):
                return False

            favorites.append(
                {
                    "msg_id": msg_id or "",
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
        with self._lock:
            favorites = self.list_favorites(session_id)
            msg_id = self._message_msg_id(session_id, msg_index)

            def _matches(fav: dict) -> bool:
                if msg_id:
                    return fav.get("msg_id") == msg_id
                return fav.get("msg_index") == msg_index

            remaining = [f for f in favorites if not _matches(f)]
            if len(remaining) == len(favorites):
                return False
            self._write_json(self._favorites_path(session_id), remaining)
            return True

    def is_favorite(self, session_id: str, msg_index: int) -> bool:
        msg_id = self._message_msg_id(session_id, msg_index)
        for f in self.list_favorites(session_id):
            if msg_id and f.get("msg_id") == msg_id:
                return True
            if not msg_id and f.get("msg_index") == msg_index:
                return True
        return False

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
            results = [r for r in results if r.get("role") == filters["role"]]

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
        with self._lock:
            session_id = generate_session_id()
            sdir = self.dir / session_id
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "audio").mkdir(exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                info_list = zf.infolist()
                # zip 炸弹防护：成员数 / 总解压大小 / 单文件大小上限
                if len(info_list) > 1000:
                    self.log("error", f"导入的会话 zip 成员数超限: {zip_path}")
                    shutil.rmtree(str(sdir), ignore_errors=True)
                    return None
                if sum(i.file_size for i in info_list) > 500 * 1024 * 1024:
                    self.log("error", f"导入的会话 zip 解压总大小超限: {zip_path}")
                    shutil.rmtree(str(sdir), ignore_errors=True)
                    return None
                if any(i.file_size > 100 * 1024 * 1024 for i in info_list):
                    self.log("error", f"导入的会话 zip 存在超大单文件: {zip_path}")
                    shutil.rmtree(str(sdir), ignore_errors=True)
                    return None
                for info in info_list:
                    member_path = Path(info.filename)
                    # 路径穿越防护
                    if info.is_dir() or member_path.is_absolute() or ".." in member_path.parts:
                        self.log("warning", f"跳过不安全路径: {info.filename}")
                        continue
                    target = (sdir / member_path).resolve()
                    if not str(target).startswith(str(sdir.resolve())):
                        self.log("warning", f"跳过越界路径: {info.filename}")
                        continue
                    try:
                        zf.extract(info, sdir)
                    except Exception as e:  # noqa: BLE001
                        # 解压异常（坏 CRC / 非法文件名 / 权限）→ 清理残留，避免幽灵会话
                        self.log("error", f"导入会话解压失败（已清理）: {info.filename}: {e}")
                        shutil.rmtree(str(sdir), ignore_errors=True)
                        return None

            messages_file = sdir / "messages.json"
            if not messages_file.exists():
                self.log("error", f"导入的会话缺少 messages.json: {zip_path}")
                shutil.rmtree(str(sdir), ignore_errors=True)
                return None
            try:
                messages = json.loads(messages_file.read_text(encoding="utf-8"))
                if not isinstance(messages, list):
                    raise ValueError("messages.json 不是数组")
                # 结构校验：每条消息必须为 dict 且含 role/content 字段
                for m in messages:
                    if not isinstance(m, dict):
                        raise ValueError("messages.json 存在非法消息结构")
                    if not isinstance(m.get("role"), str) or not isinstance(m.get("content"), str):
                        raise ValueError("messages.json 存在非法消息结构")
            except (json.JSONDecodeError, ValueError):
                self.log("error", f"导入的会话 messages.json 格式无效: {zip_path}")
                shutil.rmtree(str(sdir), ignore_errors=True)
                return None

            self._write_text(sdir / "name.txt", f"导入会话 {_now_stamp()}")
            self._write_text(sdir / "created_at.txt", _now_stamp())
            self._write_text(sdir / "updated_at.txt", _now_stamp())
            self._messages_cache[session_id] = messages
            self._invalidate_meta(session_id)
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
