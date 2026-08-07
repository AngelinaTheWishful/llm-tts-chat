"""UiService：UI 事件编排层（发送消息/会话管理/角色切换/健康检查）。

将 Gradio 组件事件与 Core 层（LLM/TTS/CharMgr/ConvMgr）解耦。
"""

import threading
import time
from pathlib import Path

from modules.base_manager import BaseManager
from modules.character_manager import CharManager
from modules.conversation_manager import ConvManager
from modules.error_codes import classify, format_error
from modules.llm_client import LLMClient, call_llm_with_fallback
from modules.lorebook_matcher import LorebookMatcher
from modules.memory_store import (
    MemoryStore,
    extract_rule_memories,
    split_summary_and_memories,
)
from modules.prompt_builder import build_messages
from modules.reporter import write_entry
from modules.tts_client import TTSClient

# 章节八十七 87.2：TTS 合成超时预算（秒），超过则本次先回复文字
DEFAULT_TTS_TIMEOUT = 20.0


def sanitize_input(
    text: str, max_length: int = 2000, sensitive_words: list[str] | None = None
) -> tuple[str, str]:
    """校验和过滤用户输入（章节五十六）。

    返回 (处理后的文本, 警告信息)。存储与 LLM 上下文使用原始文本（R1），
    XSS 防护由渲染层（Gradio Chatbot 消毒）负责，不做 HTML 转义。
    """
    text = (text or "").strip()
    if not text:
        return "", "请输入消息"

    if len(text) > max_length:
        return "", f"消息过长（{len(text)}/{max_length}），请分段发送"

    for word in sensitive_words or []:
        if word:
            text = text.replace(word, "*" * len(word))

    return text, ""


class UiService(BaseManager):
    """UI 事件编排层。"""

    def __init__(
        self,
        config_mgr,
        char_mgr: CharManager,
        conv_mgr: ConvManager,
        tts_client: TTSClient,
        memory_store: MemoryStore | None = None,
    ):
        super().__init__("ui")
        self.config_mgr = config_mgr
        self.char_mgr = char_mgr
        self.conv_mgr = conv_mgr
        self.tts_client = tts_client
        self.lore_matcher = LorebookMatcher()
        self.memory_store = memory_store or MemoryStore()
        self.active_session: str | None = None
        self.active_character: str | None = None
        self.last_audio_path: str = ""
        self.tts_healthy = False
        # R12: 按会话覆盖的 LLM 提供商（session_id -> provider 名）
        self.session_providers: dict[str, str] = {}
        # 章节八十四: LLM 摘要阶段顺带提取的记忆（extract_with_llm）
        self._pending_memories: list[str] = []

    # ---------- 对话流程（章节八） ----------

    def send_message(self, user_input: str, text_lang: str, voice_lang: str) -> dict:
        """处理用户发送消息，返回 UI 更新所需的数据。

        章节九十：全程步骤级报告写入 run_report（文本 + JSONL 双份），
        失败步骤带稳定错误码，并在返回 error 中带 [CODE]。
        """
        t_start = time.time()

        def _rstep(step: str, status: str = "OK", detail: str = "", code: str = ""):
            elapsed = f"{time.time() - t_start:.2f}s"
            detail_txt = f"{detail}（{elapsed}）" if detail else f"耗时{elapsed}"
            write_entry("run_report", step, status, detail_txt, code)
            self.log(
                "debug" if status == "OK" else "warning",
                f"[run_report] {step} | {status}"
                + (f" | [{code}]" if code else "")
                + f" | {elapsed}",
            )

        config = self.config_mgr
        max_len = config.get("app", {}).get("max_input_length", 2000)
        sensitive = config.get("app", {}).get("sensitive_words", [])
        text, warn = sanitize_input(user_input, max_len, sensitive)
        if warn:
            return {"error": f"[UI-001] {warn}"}

        # 0. 先校验角色（避免无角色时产生空会话/脏消息）
        character = (
            self.char_mgr.get_character(self.active_character) if self.active_character else None
        )
        if not character:
            return {"error": "[UI-002] 请先选择一个角色"}
        _rstep("输入校验通过")

        # Q10：捕获会话快照，全程使用局部变量，避免并发发送/切换会话时写错会话
        session_id = self.active_session
        if not session_id:
            session_id = self.conv_mgr.create_session(
                self.active_character and f"{self.active_character}-1" or "新会话"
            )
            self.active_session = session_id
            _rstep("自动创建会话", detail=session_id)
        _rstep("会话确认", detail=session_id)

        # 1. 保存用户消息
        self.conv_mgr.add_message(session_id, "user", text)
        _rstep("保存用户消息", detail=f"{len(text)}字")

        # 1.5 记忆提取（章节八十四，规则提取）
        memory_cfg = config.get("memory", {})
        if memory_cfg.get("enabled", True):
            mem_scope, mem_key = self._memory_scope_key()
            new_memories = extract_rule_memories(text)
            if new_memories:
                self.memory_store.add_memories(
                    new_memories,
                    scope=mem_scope,
                    key=mem_key,
                    source_session=session_id,
                )
            _rstep("记忆提取", detail=f"新增 {len(new_memories)} 条")

        # 2. 构建上下文
        summary, recent = self.conv_mgr.build_llm_context(session_id)
        _rstep("构建上下文", detail=f"summary={len(summary)}字 recent={len(recent)}条")

        # 2.5 记忆召回（章节八十四）
        memory_entries = []
        if memory_cfg.get("enabled", True):
            mem_scope, mem_key = self._memory_scope_key()
            memory_entries = self.memory_store.recall(
                text, scope=mem_scope, key=mem_key, limit=memory_cfg.get("recall_limit", 5)
            )
            _rstep("记忆召回", detail=f"{len(memory_entries)} 条")

        # 3. Lorebook 匹配
        lore_entries = self._match_lorebook(text)
        _rstep("Lorebook 匹配", detail=f"{len(lore_entries)} 条")

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
            memory_entries=memory_entries,
        )

        # 5. LLM 调用（多提供商故障转移 + 会话级提供商覆盖 R12）
        providers = config.get("llm_providers", {})
        llm_cfg = config.get("llm", {})
        session_provider = self.get_session_provider(session_id)
        self.log(
            "debug",
            f"LLM 发送准备: 提供商数量={len(providers)} 名称={list(providers.keys())} "
            f"active_provider={llm_cfg.get('active_provider', '')} "
            f"session_provider={session_provider or '跟随全局'} "
            f"会话={session_id}",
        )
        if not providers:
            self.log(
                "warning",
                "LLM 发送前检测到 llm_providers 为空，将抛出『没有可用的 LLM 提供商』——"
                "请检查 config.json 或侧栏配置面板是否已填写提供商",
            )
        try:
            reply, provider_name = call_llm_with_fallback(
                providers,
                llm_cfg.get("active_provider", ""),
                llm_cfg.get("fallback_enabled", True),
                messages[0]["content"],
                messages[1:],
                session_provider=session_provider,
            )
        except Exception as e:
            # R4：回滚刚保存的用户消息，避免重发重复
            self.conv_mgr.remove_last_message(session_id, role="user")
            self.log("error", f"LLM 调用失败（已回滚用户消息）: {e}")
            _rstep("LLM 调用", status="FAIL", code=classify(e)[0], detail=str(e)[:120])
            return {"error": format_error(e, prefix="LLM 调用失败")}
        _rstep("LLM 调用", detail=f"提供商={provider_name} 回复={len(reply)}字")
        self.log("info", f"LLM 调用成功: 提供商={provider_name} 回复长度={len(reply)}")

        # 6. 检查上下文长度 → 摘要压缩（extract_with_llm 时顺带提取记忆）
        try:
            self.conv_mgr.maybe_summarize(session_id, summarize_fn=self._summarize_with_provider)
        except Exception as e:
            self.log("warning", f"摘要压缩失败（不阻断回复）: {e}")
            _rstep("摘要压缩", status="WARN", code=classify(e)[0], detail=str(e)[:120])
        if memory_cfg.get("enabled", True) and self._pending_memories:
            mem_scope, mem_key = self._memory_scope_key()
            self.memory_store.add_memories(
                self._pending_memories,
                scope=mem_scope,
                key=mem_key,
                source_session=session_id,
            )
            self._pending_memories = []

        # 7. TTS 合成（R7：离线时实时探测，失败不阻断文字显示；
        #    章节八十七 87.2：20s 超时预算，超时先回复文字）
        audio_data = None
        tts_notice = ""
        norm = config.get("audio_normalization", {})
        if self._ensure_tts_ready():
            try:
                audio_data, tts_timed_out = self._run_with_timeout(
                    lambda: self.tts_client.synthesize_normalized(
                        reply,
                        voice_lang,
                        params=self._tts_params(),
                        target_db=norm.get("target_dB", -3.0),
                        global_volume=norm.get("global_volume", 1.0),
                    ),
                    timeout=self._tts_timeout(),
                )
                if tts_timed_out:
                    tts_notice = "[TTS-004] 语音合成超时，已先回复文字"
                    _rstep(
                        "TTS 合成",
                        status="WARN",
                        code="TTS-004",
                        detail=f"超时>{self._tts_timeout():.0f}s",
                    )
                elif audio_data is None:
                    tts_notice = "[TTS-003] TTS 合成失败，本次回复无语音"
                    _rstep("TTS 合成", status="WARN", code="TTS-003", detail="合成结果为空")
                else:
                    _rstep("TTS 合成", detail=f"{len(audio_data)} bytes")
            except Exception as e:
                self.log("warning", f"TTS 合成失败（不影响文字）: {e}")
                tts_notice = f"{format_error(e, prefix='')}，本次回复无语音"
                _rstep("TTS 合成", status="WARN", code=classify(e)[0], detail=str(e)[:120])
        else:
            tts_notice = "[TTS-001] TTS API 离线，本次回复无语音"
            _rstep("TTS 合成", status="WARN", code="TTS-001", detail="API 离线")

        # 8. 保存 AI 回复（章节九十五：音频新命名，携带角色名 + 消息版本 1）
        self.conv_mgr.add_message(
            session_id,
            "assistant",
            reply,
            audio_data,
            character=self.active_character or "",
            message_version=1,
        )

        # 9. 更新音频路径
        self.last_audio_path = self._last_audio_file(session_id)
        _rstep("保存 AI 回复", detail=f"总耗时{time.time() - t_start:.2f}s")

        return {
            "messages": self.conv_mgr.get_messages(session_id),
            "audio_path": self.last_audio_path,
            "provider": provider_name,
            "session_id": session_id,
            "session_name": self._session_name(session_id),
            "tts_notice": tts_notice,
        }

    def regenerate_last_reply(self, text_lang: str = "中文", voice_lang: str = "中文") -> dict:
        """重新生成最后一条 AI 回复（Q7）。

        - 删除最后一条 assistant 消息（含音频），基于最后一条 user 消息重新调用 LLM+TTS
        - 旧回复写入新回复的 edited_from 版本记录，便于追溯
        """
        t_start = time.time()
        session_id = self.active_session
        if not session_id:
            return {"error": "[UI-002] 尚无会话可重新生成"}
        messages = self.conv_mgr.get_messages(session_id)
        if not messages or messages[-1].get("role") != "assistant":
            return {"error": "[UI-003] 最后一条消息不是 AI 回复，无法重新生成"}
        if not any(m.get("role") == "user" for m in messages):
            return {"error": "[UI-003] 会话中无用户消息，无法重新生成"}

        # 移除旧 assistant 回复（保留文本与音频字节到恢复用）
        old = messages[-1]
        old_audio_path = old.get("audio_file") or ""
        old_audio_bytes = None
        if old_audio_path:
            try:
                old_audio_path_abs = self.conv_mgr.dir / session_id / old_audio_path
                if old_audio_path_abs.is_file():
                    old_audio_bytes = old_audio_path_abs.read_bytes()
            except OSError:
                old_audio_bytes = None
        self.conv_mgr.remove_last_message(session_id, role="assistant")

        # 基于最后一条 user 消息重新生成
        last_user = next(
            (m for m in reversed(self.conv_mgr.get_messages(session_id)) if m["role"] == "user"),
            None,
        )
        if last_user is None:
            return {"error": "[UI-003] 未找到用户消息"}

        config = self.config_mgr
        character = (
            self.char_mgr.get_character(self.active_character) if self.active_character else None
        )
        if not character:
            return {"error": "[UI-002] 请先选择一个角色"}

        summary, recent = self.conv_mgr.build_llm_context(session_id)
        memory_entries = []
        memory_cfg = config.get("memory", {})
        if memory_cfg.get("enabled", True):
            mem_scope, mem_key = self._memory_scope_key()
            memory_entries = self.memory_store.recall(
                last_user["content"],
                scope=mem_scope,
                key=mem_key,
                limit=memory_cfg.get("recall_limit", 5),
            )
        lore_entries = self._match_lorebook(last_user["content"])
        protection_mode = config.get("prompt_protection", {}).get("mode", "A")
        msgs = build_messages(
            character,
            lore_entries,
            summary,
            recent,
            last_user["content"],
            text_lang,
            protection_mode=protection_mode,
            memory_entries=memory_entries,
        )

        providers = config.get("llm_providers", {})
        llm_cfg = config.get("llm", {})
        session_provider = self.get_session_provider(session_id)
        try:
            reply, provider_name = call_llm_with_fallback(
                providers,
                llm_cfg.get("active_provider", ""),
                llm_cfg.get("fallback_enabled", True),
                msgs[0]["content"],
                msgs[1:],
                session_provider=session_provider,
            )
        except Exception as e:
            # 恢复旧回复（含音频），避免数据丢失
            self.conv_mgr.add_message(
                session_id,
                "assistant",
                old.get("content", ""),
                old_audio_bytes,
                character=old.get("character", "") or self.active_character or "",
                message_version=1,
            )
            self.log("error", f"重新生成失败（已恢复旧回复）: {e}")
            return {"error": format_error(e, prefix="重新生成失败")}

        # TTS 合成（超时/失败不阻断文字）
        audio_data = None
        tts_notice = ""
        norm = config.get("audio_normalization", {})
        if self._ensure_tts_ready():
            try:
                audio_data, timed_out = self._run_with_timeout(
                    lambda: self.tts_client.synthesize_normalized(
                        reply,
                        voice_lang,
                        params=self._tts_params(),
                        target_db=norm.get("target_dB", -3.0),
                        global_volume=norm.get("global_volume", 1.0),
                    ),
                    timeout=self._tts_timeout(),
                )
                if timed_out:
                    tts_notice = "[TTS-004] 语音合成超时，已先回复文字"
                elif audio_data is None:
                    tts_notice = "[TTS-003] TTS 合成失败，本次回复无语音"
            except Exception as e:
                self.log("warning", f"重新生成 TTS 失败（不影响文字）: {e}")
                tts_notice = f"{format_error(e, prefix='')}，本次回复无语音"

        # 章节九十五：重新生成的消息版本为 2+（携带角色名）
        new_msg = self.conv_mgr.add_message(
            session_id,
            "assistant",
            reply,
            audio_data,
            character=self.active_character or "",
            message_version=2,
        )
        # 旧回复保留为版本记录（Q7 多版本追溯）
        if old.get("content") and new_msg.get("msg_id"):
            try:
                self.conv_mgr.edit_message(
                    session_id,
                    new_msg["msg_id"],
                    reply,
                    prepend_versions=[old.get("content", "")],
                )
            except Exception as e:
                self.log("debug", f"记录旧回复版本失败: {e}")

        self.last_audio_path = self._last_audio_file(session_id)
        self.log("info", f"重新生成完成: 提供商={provider_name} 耗时{time.time() - t_start:.1f}s")
        return {
            "messages": self.conv_mgr.get_messages(session_id),
            "audio_path": self.last_audio_path,
            "provider": provider_name,
            "session_id": session_id,
            "session_name": self._session_name(session_id),
            "tts_notice": tts_notice,
        }

    def _summarize_with_provider(self, history: list[dict]) -> str:
        providers = self.config_mgr.get("llm_providers", {})
        llm_cfg = self.config_mgr.get("llm", {})
        provider_config = self._pick_provider_config(providers, llm_cfg.get("active_provider", ""))
        client = LLMClient(provider_config)

        # 章节八十四：extract_with_llm 时摘要调用顺带提取记忆（不额外调用）
        memory_cfg = self.config_mgr.get("memory", {})
        if memory_cfg.get("extract_with_llm", False):
            combined = client.chat(
                "你是对话摘要与记忆提取助手。",
                [
                    *history,
                    {
                        "role": "user",
                        "content": (
                            "请输出：1) 对话摘要（简洁）；"
                            "2) 从用户陈述中提取的用户长期偏好/事实记忆"
                            "（每条以「记忆：」开头，每行一条，无记忆则只输出摘要）。\n"
                            "格式：\n[摘要]\n<摘要内容>\n[记忆]\n记忆：<内容>\n记忆：<内容>"
                        ),
                    },
                ],
            )
            summary, memories = split_summary_and_memories(combined)
            self._pending_memories = [m for m in memories if m]
            return summary

        return client.summarize(history)

    def _memory_scope_key(self) -> tuple[str, str]:
        """返回记忆库作用域与键（章节八十四）：character/<角色名> 或 global/global。"""
        scope = self.config_mgr.get("memory", {}).get("scope", "character")
        if scope == "global":
            return "global", "global"
        return "character", self.active_character or "default"

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

    def _tts_timeout(self) -> float:
        """读取 TTS 合成超时预算（config tts.synthesis_timeout，默认 20s）。"""
        raw = self.config_mgr.get("tts", {}).get("synthesis_timeout", DEFAULT_TTS_TIMEOUT)
        return float(raw or DEFAULT_TTS_TIMEOUT)

    def _run_with_timeout(
        self, fn, timeout: float = DEFAULT_TTS_TIMEOUT
    ) -> tuple[bytes | None, bool]:
        """在子线程运行 TTS 合成 fn，timeout 秒内未完成则视为超时。

        Returns:
            (音频或 None, 是否超时)。超时后线程在后台继续，结果丢弃。
        """
        result: dict = {}

        def _run() -> None:
            try:
                result["value"] = fn()
            except Exception as e:  # noqa: BLE001
                result["error"] = e

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return None, True
        if "error" in result:
            raise result["error"]
        return result.get("value"), False

    def _synthesize_speech(self, text: str, voice_lang: str) -> bytes | None:
        """合成语音（失败/超时返回 None，不影响文字流程）。"""
        if not self._ensure_tts_ready():
            return None
        norm = self.config_mgr.get("audio_normalization", {})
        try:
            audio, timed_out = self._run_with_timeout(
                lambda: self.tts_client.synthesize_normalized(
                    text,
                    voice_lang,
                    params=self._tts_params(),
                    target_db=norm.get("target_dB", -3.0),
                    global_volume=norm.get("global_volume", 1.0),
                ),
                timeout=self._tts_timeout(),
            )
            if timed_out:
                self.log("warning", f"TTS 合成超时（>{self._tts_timeout():.0f}s），本次无语音")
                return None
            return audio
        except Exception as e:
            self.log("warning", f"TTS 合成失败（不影响文字）: {e}")
            return None

    def _ensure_tts_ready(self) -> bool:
        """R7：TTS 状态缓存增强——缓存为离线时实时探测一次，避免静默跳过语音。"""
        if self.tts_healthy:
            return True
        self.tts_healthy = self.tts_client.check_api()
        return self.tts_healthy

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
        # 章节九十五：问候语音频携带角色名 + 消息版本 1
        self.conv_mgr.add_message(
            self.active_session,
            "assistant",
            greeting,
            audio,
            character=self.active_character or "",
            message_version=1,
        )
        self.log("info", f"已添加角色问候语: {self.active_character}")

    def switch_session(self, session_id: str) -> dict:
        if not self.conv_mgr.session_exists(session_id):
            return {"error": f"会话不存在: {session_id}"}
        self.active_session = session_id
        messages = self.conv_mgr.get_messages(session_id)
        self.last_audio_path = self._last_audio_file(session_id)
        # R12：加载该会话的提供商覆盖
        self._load_session_provider(session_id)
        return {
            "session_id": session_id,
            "session_name": self._session_name(session_id),
            "messages": messages,
            "audio_path": self.last_audio_path,
        }

    # ---------- 会话级 LLM 提供商（R12） ----------

    def _provider_file(self, session_id: str) -> Path:
        return Path(self.conv_mgr.dir) / session_id / "provider.txt"

    def _load_session_provider(self, session_id: str) -> str:
        """从会话目录 provider.txt 加载提供商覆盖。"""
        p = self._provider_file(session_id)
        provider = ""
        if p.exists():
            provider = p.read_text(encoding="utf-8").strip()
        self.session_providers[session_id] = provider
        return provider

    def get_session_provider(self, session_id: str | None) -> str | None:
        """返回会话级提供商（无覆盖时返回 None → 跟随全局活动提供商）。"""
        if not session_id:
            return None
        provider = self.session_providers.get(session_id)
        if provider is None:
            provider = self._load_session_provider(session_id)
        return provider or None

    def set_session_provider(self, session_id: str | None, provider: str) -> bool:
        """设置会话级提供商（空值 = 跟随全局），持久化到 provider.txt。

        兼容前端误传标签「跟随全局」：统一归一为空值，避免被当作提供商名
        导致"没有可用的 LLM 提供商"。
        """
        if not session_id or not self.conv_mgr.session_exists(session_id):
            return False
        provider = (provider or "").strip()
        if provider == "跟随全局":
            provider = ""
        self.session_providers[session_id] = provider
        p = self._provider_file(session_id)
        if provider:
            p.write_text(provider, encoding="utf-8")
        elif p.exists():
            p.unlink(missing_ok=True)
        self.log("info", f"会话级提供商已设置: {session_id} -> {provider or '跟随全局'}")
        return True

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
        # 章节九十二：返回角色聊天背景路径（character.json background 字段 > 固定文件名），
        # 由 app.py 层做 gr.set_static_paths 单文件注册后再供前端 JS 应用
        # 章节九十三：同时返回角色头像路径（portrait.png 主图，无则空串，前端回落首字占位）
        return {
            "character": name,
            "background": char.get("_background", "") or "",
            "avatar": char.get("_portrait", "") or "",
            "message": f"已切换到角色: {name}",
        }

    # ---------- 健康检查 ----------

    def check_health(self) -> bool:
        self.tts_healthy = self.tts_client.check_api()
        return self.tts_healthy

    # ---------- gsv_root 统一管理（章节九十四） ----------

    def refresh_gsv_root(self) -> dict:
        """前端「重新探测」一键全量刷新。

        重探测 gsv_root（成功自动写回 config.json）+ 重扫 GPT/SoVITS 权重列表 +
        重解析当前角色参考音频 + 重应用音色预设。
        """
        path, source = self.config_mgr.resolve_gsv_root()
        if not path:
            return {
                "ok": False,
                "path": "",
                "source": "",
                "message": "[CFG-008] 未找到 GPT-SoVITS 目录（含 api_v2.py），"
                "请确认其与项目位于同一父目录，或在前端手动输入路径",
            }
        gpt_models = self.tts_client.list_gpt_models(path)
        sovits_models = self.tts_client.list_sovits_models(path)
        preset_info = ""
        if self.active_character:
            char = self.char_mgr.get_character(self.active_character)
            if char:
                self.char_mgr.apply_preset(char, self.tts_client, gsv_root=path)
                preset_info = f"，已应用角色「{self.active_character}」音色预设"
        src = {
            "config": "已有配置",
            "startup_report": "启动报告",
            "scan": "同级目录扫描",
        }.get(source, source)
        return {
            "ok": True,
            "path": path,
            "source": source,
            "message": (
                f"GPT-SoVITS 路径已就绪（来源：{src}）：{path}"
                f"（GPT 模型 {len(gpt_models)} 个 / "
                f"SoVITS 模型 {len(sovits_models)} 个{preset_info}）"
            ),
        }

    # ---------- 工具 ----------

    def _last_audio_file(self, session_id: str) -> str | None:
        """返回最后一条带音频消息的路径；无音频时返回 None。

        禁止返回空串：Gradio 的 abspath("") 会解析为工作目录并当作文件哈希，
        导致 PermissionError。
        """
        messages = self.conv_mgr.get_messages(session_id)
        sdir = (self.conv_mgr.dir / session_id).resolve()
        for msg in reversed(messages):
            audio_file = msg.get("audio_file")
            if not audio_file:
                continue
            path = (self.conv_mgr.dir / session_id / str(audio_file)).resolve()
            # 路径穿越防护：仅允许会话目录内的音频文件
            if not str(path).startswith(str(sdir)):
                continue
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
