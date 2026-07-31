"""UiService：UI 事件编排层（发送消息/会话管理/角色切换/健康检查）。

将 Gradio 组件事件与 Core 层（LLM/TTS/CharMgr/ConvMgr）解耦。
"""

import html as html_lib

from modules.base_manager import BaseManager
from modules.character_manager import CharManager
from modules.conversation_manager import ConvManager
from modules.llm_client import LLMClient, call_llm_with_fallback
from modules.lorebook_matcher import LorebookMatcher
from modules.prompt_builder import build_messages
from modules.tts_client import TTSClient


def sanitize_input(
    text: str, max_length: int = 2000, sensitive_words: list[str] | None = None
) -> tuple[str, str]:
    """校验和过滤用户输入（章节五十六）。返回 (处理后的文本, 警告信息)。"""
    text = (text or "").strip()
    if not text:
        return "", "请输入消息"

    if len(text) > max_length:
        return "", f"消息过长（{len(text)}/{max_length}），请分段发送"

    text = html_lib.escape(text)

    for word in sensitive_words or []:
        if word:
            text = text.replace(word, "*" * len(word))

    return text, ""


class UiService(BaseManager):
    """UI 事件编排层。"""

    def __init__(
        self, config_mgr, char_mgr: CharManager, conv_mgr: ConvManager, tts_client: TTSClient
    ):
        super().__init__("ui")
        self.config_mgr = config_mgr
        self.char_mgr = char_mgr
        self.conv_mgr = conv_mgr
        self.tts_client = tts_client
        self.lore_matcher = LorebookMatcher()
        self.active_session: str | None = None
        self.active_character: str | None = None
        self.last_audio_path: str = ""
        self.tts_healthy = False

    # ---------- 对话流程（章节八） ----------

    def send_message(self, user_input: str, text_lang: str, voice_lang: str) -> dict:
        """处理用户发送消息，返回 UI 更新所需的数据。"""
        config = self.config_mgr
        max_len = config.get("app", {}).get("max_input_length", 2000)
        sensitive = config.get("app", {}).get("sensitive_words", [])
        text, warn = sanitize_input(user_input, max_len, sensitive)
        if warn:
            return {"error": warn}

        # 0. 先校验角色（避免无角色时产生空会话/脏消息）
        character = (
            self.char_mgr.get_character(self.active_character) if self.active_character else None
        )
        if not character:
            return {"error": "请先选择一个角色"}

        if not self.active_session:
            self.active_session = self.conv_mgr.create_session(
                self.active_character and f"{self.active_character}-1" or "新会话"
            )

        # 1. 保存用户消息
        self.conv_mgr.add_message(self.active_session, "user", text)

        # 2. 构建上下文
        summary, recent = self.conv_mgr.build_llm_context(self.active_session)

        # 3. Lorebook 匹配
        lore_entries = self._match_lorebook(text)

        # 4. 角色配置（已在上方校验）

        protection_mode = config.get("prompt_protection", {}).get("mode", "A")
        messages = build_messages(
            character,
            lore_entries,
            summary,
            recent,
            text,
            text_lang,
            protection_mode=protection_mode,
        )

        # 5. LLM 调用（含多提供商故障转移）
        providers = config.get("llm_providers", {})
        llm_cfg = config.get("llm", {})
        try:
            reply, provider_name = call_llm_with_fallback(
                providers,
                llm_cfg.get("active_provider", ""),
                llm_cfg.get("fallback_enabled", True),
                messages[0]["content"],
                messages[1:],
            )
        except Exception as e:
            self.log("error", f"LLM 调用失败: {e}")
            return {"error": f"LLM 调用失败: {e}"}

        # 6. 检查上下文长度 → 摘要压缩
        self.conv_mgr.maybe_summarize(
            self.active_session, summarize_fn=self._summarize_with_provider
        )

        # 7. TTS 合成（失败不阻断文字显示）
        audio_data = None
        norm = config.get("audio_normalization", {})
        try:
            if self.tts_healthy:
                audio_data = self.tts_client.synthesize_normalized(
                    reply,
                    voice_lang,
                    params=self._tts_params(),
                    target_db=norm.get("target_dB", -3.0),
                    global_volume=norm.get("global_volume", 1.0),
                )
        except Exception as e:
            self.log("warning", f"TTS 合成失败（不影响文字）: {e}")

        # 8. 保存 AI 回复
        self.conv_mgr.add_message(self.active_session, "assistant", reply, audio_data)

        # 9. 更新音频路径
        self.last_audio_path = self._last_audio_file(self.active_session)

        return {
            "messages": self.conv_mgr.get_messages(self.active_session),
            "audio_path": self.last_audio_path,
            "provider": provider_name,
            "session_id": self.active_session,
            "session_name": self._session_name(self.active_session),
        }

    def _summarize_with_provider(self, history: list[dict]) -> str:
        providers = self.config_mgr.get("llm_providers", {})
        llm_cfg = self.config_mgr.get("llm", {})
        provider_config = self._pick_provider_config(providers, llm_cfg.get("active_provider", ""))
        client = LLMClient(provider_config)
        return client.summarize(history)

    @staticmethod
    def _pick_provider_config(providers: dict, active: str) -> dict:
        if active in providers:
            return providers[active]
        for cfg in providers.values():
            return cfg
        return {}

    def _match_lorebook(self, user_input: str) -> list[str]:
        character = (
            self.char_mgr.get_character(self.active_character) if self.active_character else None
        )
        if not character:
            return []
        lore = character.get("lorebook") or {}
        if not lore.get("enabled"):
            return []
        return self.lore_matcher.match(user_input, lore.get("entries", []))

    # ---------- 会话管理 ----------

    def _tts_params(self) -> dict:
        tts = self.config_mgr.get("tts", {})
        return {
            "top_k": tts.get("top_k", 15),
            "top_p": tts.get("top_p", 1.0),
            "temperature": tts.get("temperature", 1.0),
            "speed": tts.get("speed", 1.0),
        }

    def _synthesize_speech(self, text: str, voice_lang: str) -> bytes | None:
        """合成语音（失败返回 None，不影响文字流程）。"""
        if not self.tts_healthy:
            return None
        norm = self.config_mgr.get("audio_normalization", {})
        try:
            return self.tts_client.synthesize_normalized(
                text,
                voice_lang,
                params=self._tts_params(),
                target_db=norm.get("target_dB", -3.0),
                global_volume=norm.get("global_volume", 1.0),
            )
        except Exception as e:
            self.log("warning", f"TTS 合成失败（不影响文字）: {e}")
            return None

    def new_session(self, character_name: str | None = None) -> dict:
        name = character_name or self.active_character or "新会话"
        self.active_session = self.conv_mgr.create_session(name)
        self.last_audio_path = ""

        # 问候语流程（章节十五）：自动加入角色问候语 + 语音
        self._add_greeting()

        messages = self.conv_mgr.get_messages(self.active_session)
        self.last_audio_path = self._last_audio_file(self.active_session)
        return {
            "session_id": self.active_session,
            "session_name": name,
            "messages": messages,
            "audio_path": self.last_audio_path,
        }

    def _add_greeting(self) -> None:
        """将角色问候语作为第一轮消息加入会话（含语音）。"""
        if not self.active_character:
            return
        character = self.char_mgr.get_character(self.active_character)
        if not character:
            return
        greeting = character.get("greeting", "")
        if not greeting:
            return

        voice_lang = self.config_mgr.get("tts", {}).get("voice_language", "中文")
        audio = self._synthesize_speech(greeting, voice_lang)
        self.conv_mgr.add_message(self.active_session, "assistant", greeting, audio)
        self.log("info", f"已添加角色问候语: {self.active_character}")

    def switch_session(self, session_id: str) -> dict:
        if not self.conv_mgr.session_exists(session_id):
            return {"error": f"会话不存在: {session_id}"}
        self.active_session = session_id
        messages = self.conv_mgr.get_messages(session_id)
        self.last_audio_path = self._last_audio_file(session_id)
        return {
            "session_id": session_id,
            "session_name": self._session_name(session_id),
            "messages": messages,
            "audio_path": self.last_audio_path,
        }

    def delete_session(self, session_id: str) -> dict:
        if session_id == self.active_session:
            self.active_session = None
            self.last_audio_path = ""
        self.conv_mgr.delete_session(session_id)
        return {"active_session": self.active_session}

    # ---------- 角色 ----------

    def select_character(self, name: str) -> dict:
        char = self.char_mgr.get_character(name)
        if not char:
            return {"error": f"角色不存在: {name}"}
        self.active_character = name
        gsv_root = self.config_mgr.get("gsv_root", "")
        self.char_mgr.apply_preset(char, self.tts_client, gsv_root=gsv_root)
        return {"character": name, "message": f"已切换到角色: {name}"}

    # ---------- 健康检查 ----------

    def check_health(self) -> bool:
        self.tts_healthy = self.tts_client.check_api()
        return self.tts_healthy

    # ---------- 工具 ----------

    def _last_audio_file(self, session_id: str) -> str | None:
        """返回最后一条带音频消息的路径；无音频时返回 None。

        禁止返回空串：Gradio 的 abspath("") 会解析为工作目录并当作文件哈希，
        导致 PermissionError。
        """
        messages = self.conv_mgr.get_messages(session_id)
        for msg in reversed(messages):
            audio_file = msg.get("audio_file")
            if audio_file:
                path = self.conv_mgr.dir / session_id / audio_file
                if path.is_file():
                    return str(path)
        return None

    def _session_name(self, session_id: str) -> str:
        for s in self.conv_mgr.list_sessions():
            if s["id"] == session_id:
                return s["name"]
        return session_id

    @staticmethod
    def messages_to_chatbot(messages: list[dict]) -> list[list[str]]:
        """转换为 Gradio Chatbot 的 [(user, ai), ...] 格式。"""
        pairs: list[list[str]] = []
        for i in range(0, len(messages), 2):
            user = messages[i]
            ai = messages[i + 1] if i + 1 < len(messages) else None
            user_text = user.get("content", "") if user.get("role") == "user" else ""
            if user.get("role") == "assistant":
                pairs.append(["", user.get("content", "")])
                continue
            pairs.append([user_text, ai.get("content", "") if ai else ""])
        return pairs
