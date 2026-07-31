"""LLM 角色扮演聊天 + GPT-SoVITS TTS — Gradio 主入口。

Phase 4：左右分栏主界面 + 配置向导（条件可见性）。
"""

import argparse
import json
import socket
import sys
from pathlib import Path

import gradio as gr

from modules.character_manager import CharManager
from modules.config_manager import ConfigManager, decrypt_api_key, encrypt_api_key
from modules.conversation_manager import ConvManager
from modules.i18n import I18n
from modules.logger import setup_logger
from modules.migration import MigrationManager
from modules.theme import Theme
from modules.tts_client import TTSClient
from modules.ui_service import UiService

logger = setup_logger("app")
config_mgr = ConfigManager()
i18n = I18n()
i18n.switch(config_mgr.get("app", {}).get("language", "zh_CN"))
theme = Theme()

PROJECT_ROOT = Path(__file__).resolve().parent
CHARACTERS_DIR = PROJECT_ROOT / "characters"
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations"

CHAT_HEIGHT = 500
SIDEBAR_CSS = f"""
#sidebar-col {{
    height: {CHAT_HEIGHT}px;
    overflow-y: auto;
    padding-right: 6px;
}}
#sidebar-col .gradio-accordion {{ margin-bottom: 6px; }}
"""

char_mgr = CharManager(CHARACTERS_DIR, config_manager=config_mgr)
conv_mgr = ConvManager(CONVERSATIONS_DIR)
tts_client = TTSClient(config_mgr.get("tts", {}).get("api_base_url", "http://127.0.0.1:9880"))
ui_service = UiService(config_mgr, char_mgr, conv_mgr, tts_client)

session_options = [(s["name"], s["id"]) for s in conv_mgr.list_sessions()]


def find_available_port(start_port: int = 7861, max_attempts: int = 10) -> int:
    """自动寻找可用端口。"""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"无法找到可用端口（{start_port}~{start_port + max_attempts - 1} 均被占用）")


def list_characters() -> list[str]:
    """扫描 characters/ 下的角色名。"""
    return char_mgr.list_names()


# ---------- 事件处理 ----------


def send_message_handler(user_input, text_lang, voice_lang):
    result = ui_service.send_message(user_input, text_lang, voice_lang)
    if "error" in result:
        return (
            gr.update(visible=True, value=f"🔴 {result['error']}"),
            gr.update(visible=False, value=None),
            gr.update(value=[]),
            _status_text(),
            gr.update(value=""),
        )
    chatbot_value = ui_service.messages_to_chatbot(result["messages"])
    return (
        gr.update(visible=False, value=""),
        gr.update(visible=True, value=result.get("audio_path") or None),
        gr.update(value=chatbot_value),
        _status_text(),
        gr.update(value=""),
    )


def new_session_handler():
    result = ui_service.new_session(ui_service.active_character)
    sessions = conv_mgr.list_sessions()
    chatbot_value = ui_service.messages_to_chatbot(result["messages"])
    return (
        gr.update(choices=[(s["name"], s["id"]) for s in sessions], value=result["session_id"]),
        gr.update(value=chatbot_value),
        gr.update(visible=True, value=result.get("audio_path") or None),
        _status_text(),
    )


def switch_session_handler(session_id):
    result = ui_service.switch_session(session_id)
    if "error" in result:
        return (
            gr.update(value=[]),
            gr.update(visible=False, value=None),
            gr.update(visible=True, value=f"🔴 {result['error']}"),
            _status_text(),
        )
    chatbot_value = ui_service.messages_to_chatbot(result["messages"])
    return (
        gr.update(value=chatbot_value),
        gr.update(visible=True, value=result.get("audio_path") or None),
        gr.update(visible=False, value=""),
        _status_text(),
    )


def select_character_handler(name):
    result = ui_service.select_character(name)
    if "error" in result:
        return gr.update(value=f"🔴 {result['error']}")
    return gr.update(value=f"🟢 角色: {name} | TTS 参数已应用")


def refresh_characters_handler():
    return gr.update(choices=list_characters())


# ---------- 角色编辑（章节二十八） ----------


def parse_lorebook_text(text: str) -> list[dict]:
    """解析 '关键词1,关键词2:内容' 每行一条的 Lorebook 文本。"""
    entries = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            kw_part, content = line.split(":", 1)
            keywords = [k.strip() for k in kw_part.split(",") if k.strip()]
            if keywords and content.strip():
                entries.append({"keywords": keywords, "content": content.strip()})
        else:
            entries.append({"keywords": [], "content": line})
    return entries


def format_lorebook_text(entries: list[dict]) -> str:
    """将 Lorebook 条目格式化为每行一条的文本。"""
    lines = []
    for entry in entries or []:
        keywords = ",".join(entry.get("keywords", []))
        content = entry.get("content", "")
        if keywords:
            lines.append(f"{keywords}:{content}")
        elif content:
            lines.append(content)
    return "\n".join(lines)


def load_character_to_editor(character_name):
    """将角色配置载入编辑表单。"""
    char = char_mgr.get_character(character_name)
    if not char:
        return [gr.update(value="") for _ in range(11)] + [gr.update(value=None)]

    sc = char.get("system_prompt_structured", {})
    lore = char.get("lorebook", {})
    portrait = char.get("_portrait", None) or None

    def lines_to_text(items):
        return "\n".join(items or [])

    return [
        gr.update(value=char.get("name", "")),
        gr.update(value=char.get("greeting", "")),
        gr.update(value=sc.get("personality", "")),
        gr.update(value=sc.get("speaking_style", "")),
        gr.update(value=lines_to_text(sc.get("speech_quirks", []))),
        gr.update(value=sc.get("background", "")),
        gr.update(value=lines_to_text(sc.get("likes", []))),
        gr.update(value=lines_to_text(sc.get("dislikes", []))),
        gr.update(value=lines_to_text(sc.get("behavior_rules", []))),
        gr.update(value=char.get("chain_of_thought", "")),
        gr.update(value=format_lorebook_text(lore.get("entries", []))),
        gr.update(value=portrait),
    ]


def save_character_handler(
    character_name,
    char_name,
    greeting,
    personality,
    speaking_style,
    quirks,
    background,
    likes,
    dislikes,
    behavior_rules,
    chain_of_thought,
    lorebook_text,
    portrait_path,
):
    """保存角色编辑表单。"""
    name = (char_name or "").strip()
    if not name:
        return gr.update(value="🔴 角色名称不能为空")

    character = char_mgr.get_character(character_name) or {"name": name}
    character["name"] = name
    character["greeting"] = greeting

    sc = character.setdefault("system_prompt_structured", {})
    sc["personality"] = personality
    sc["speaking_style"] = speaking_style
    sc["speech_quirks"] = [s.strip() for s in quirks.splitlines() if s.strip()]
    sc["background"] = background
    sc["likes"] = [s.strip() for s in likes.splitlines() if s.strip()]
    sc["dislikes"] = [s.strip() for s in dislikes.splitlines() if s.strip()]
    sc["behavior_rules"] = [s.strip() for s in behavior_rules.splitlines() if s.strip()]
    character["chain_of_thought"] = chain_of_thought

    entries = parse_lorebook_text(lorebook_text)
    character.setdefault("lorebook", {})
    character["lorebook"]["enabled"] = bool(entries)
    character["lorebook"]["entries"] = entries

    char_mgr.save_character(character)

    if portrait_path:
        try:
            char_mgr.update_portrait(name, portrait_path)
        except Exception as e:
            logger.warning(f"头像更新失败: {e}")

    return (
        gr.update(value=f"🟢 角色「{name}」已保存"),
        gr.update(choices=list_characters()),
    )


# ---------- 语言 / 主题 ----------


def save_language_handler(lang):
    config_mgr.update("app", "language", lang)
    return ""


def save_theme_handler(mode):
    cfg = theme.config
    cfg["mode"] = mode
    theme_path = Path(__file__).resolve().parent / "theme_config.json"
    theme_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return ""


# ---------- 工具：导出/导入/搜索/统计（Phase 6） ----------


def export_session_handler():
    if not ui_service.active_session:
        return gr.update(value=None)
    path = conv_mgr.export_session(ui_service.active_session)
    return gr.update(value=path if path else None)


def import_session_handler(file):
    sessions = conv_mgr.list_sessions()
    choices = [(s["name"], s["id"]) for s in sessions]
    if not file:
        return (
            gr.update(choices=choices),
            "",
            gr.update(value=[]),
            gr.update(visible=False, value=None),
        )
    new_id = conv_mgr.import_session(file)
    if new_id:
        ui_service.active_session = new_id
        messages = conv_mgr.get_messages(new_id)
        audio_path = ui_service._last_audio_file(new_id)
        return (
            gr.update(choices=choices, value=new_id),
            f"🟢 会话已导入: {new_id}",
            gr.update(value=ui_service.messages_to_chatbot(messages)),
            gr.update(visible=True, value=audio_path or None),
        )
    return (
        gr.update(choices=choices),
        "🔴 导入失败（messages.json 无效）",
        gr.update(value=[]),
        gr.update(visible=False, value=None),
    )


def favorite_last_message_handler():
    if not ui_service.active_session:
        return gr.update(value="🔴 请先选择会话")
    messages = conv_mgr.get_messages(ui_service.active_session)
    if not messages:
        return gr.update(value="🔴 会话为空")
    last_ai_index = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_ai_index = i
            break
    if last_ai_index is None:
        return gr.update(value="🔴 没有可收藏的 AI 回复")
    if conv_mgr.is_favorite(ui_service.active_session, last_ai_index):
        conv_mgr.remove_favorite(ui_service.active_session, last_ai_index)
        return gr.update(value="⭐ 已取消收藏")
    conv_mgr.add_favorite(ui_service.active_session, last_ai_index)
    return gr.update(value="⭐ 已收藏最后一条回复")


def search_session_handler(query):
    if not ui_service.active_session or not query:
        return gr.update(value="")
    results = conv_mgr.search_in_session(ui_service.active_session, query)
    if not results:
        return gr.update(value="（无匹配结果）")
    lines = [f"[{r['timestamp']}] ({r['role']}) {r['content']}" for r in results]
    return gr.update(value="\n\n".join(lines))


def stats_handler():
    if not ui_service.active_session:
        return gr.update(value="（请先选择或创建会话）")
    s = conv_mgr.get_session_stats(ui_service.active_session)
    g = conv_mgr.get_global_stats()
    most = g["most_active_session"]
    text = (
        f"## 本会话「{s['name']}」\n"
        f"消息数: {s['msg_count']} | 用户: {s['user_count']} | AI: {s['ai_count']}\n"
        f"收藏: {s['favorite_count']} | 语音: {s['audio_count']}\n\n"
        f"## 全局统计\n"
        f"会话数: {g['session_count']} | 总消息: {g['total_msgs']}\n"
        f"收藏总数: {g['total_favorites']} | 语音总数: {g['total_audio']}\n"
    )
    if most:
        text += f"最活跃会话: {most['name']}（{most['msg_count']} 条）"
    return gr.update(value=text)


# ---------- 侧栏折叠 / 配置保存（Phase 9） ----------


def persist_sidebar_state(current_visible: bool):
    """仅持久化折叠状态，不做任何 UI 重渲染（避免 Accordion 内容丢失）。"""
    new_visible = not current_visible
    config_mgr.update("app", "sidebar_collapsed", not new_visible)
    return new_visible


def save_settings_handler(
    gsv_root,
    tts_url,
    provider_name,
    base_url,
    api_key,
    model,
    max_tokens,
    temperature,
    text_language,
):
    """侧栏配置保存：写回 config.json 并即时生效（TTS 地址立即更新，LLM 下次发送生效）。"""
    provider_name = (provider_name or "deepseek").strip()
    config = config_mgr.get_raw()

    config["gsv_root"] = gsv_root or ""
    config["tts"]["api_base_url"] = tts_url or "http://127.0.0.1:9880"

    provider = config["llm_providers"].get(provider_name, {})
    provider.update(
        {
            "base_url": base_url or "",
            "api_key": encrypt_api_key(api_key) if api_key else provider.get("api_key", ""),
            "model": model or "",
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "text_language": text_language,
            "priority": provider.get("priority", 1),
        }
    )
    config["llm_providers"][provider_name] = provider
    config["llm"]["active_provider"] = provider_name

    config_mgr.replace(config)

    # 即时生效：TTS 地址立即更新（LLM 每次发送时从 config 读取，天然即时）
    tts_client.base = config["tts"]["api_base_url"].rstrip("/")
    logger.info(f"侧栏配置已保存，TTS 地址: {tts_client.base}")
    return gr.update(value="🟢 配置已保存，即时生效")


def health_check_handler():
    ui_service.check_health()
    return gr.update(value=_status_text())


def _status_text() -> str:
    api = "🟢" if ui_service.tts_healthy else "🔴"
    provider = config_mgr.get("llm", {}).get("active_provider", "未配置")
    session = ui_service.active_session or "无"
    tts_state = "在线" if ui_service.tts_healthy else "离线"
    return f"{api} TTS API {tts_state} | 提供商: {provider} | 会话: {session}"


# ---------- 配置向导 ----------


def build_config(
    gsv_root: str,
    tts_url: str,
    provider_name: str,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
    text_language: str,
) -> dict:
    """由向导输入构建完整配置。"""
    config = config_mgr.get_raw()
    provider = {
        "base_url": base_url,
        "api_key": encrypt_api_key(api_key) if api_key else "",
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "text_language": text_language,
        "priority": 1,
    }
    config["gsv_root"] = gsv_root
    config["tts"]["api_base_url"] = tts_url
    config["llm_providers"] = {provider_name: provider}
    config["llm"]["active_provider"] = provider_name
    config["llm"]["fallback_enabled"] = True
    return config


def on_wizard_complete(
    gsv_root,
    tts_url,
    provider_name,
    base_url,
    api_key,
    model,
    max_tokens,
    temperature,
    text_language,
):
    """配置向导完成：保存配置并切换到主界面。"""
    provider_name = (provider_name or "deepseek").strip()
    base_url = (base_url or "").strip()
    if not base_url:
        logger.warning("LLM API Base URL 为空，仍保存（可稍后在设置中修改）")

    config = build_config(
        gsv_root,
        tts_url,
        provider_name,
        base_url,
        api_key,
        model,
        max_tokens,
        temperature,
        text_language,
    )
    config_mgr.replace(config)
    # 更新 TTS 客户端地址
    tts_client.base = config.get("tts", {}).get("api_base_url", "http://127.0.0.1:9880").rstrip("/")
    logger.info("配置向导完成，已保存 config.json")
    return gr.update(visible=False), gr.update(visible=True)


# ---------- 界面构建 ----------


def build_wizard() -> tuple[gr.Group, gr.Group]:
    """构建配置向导与主界面两个条件可见性区块。"""
    is_first = config_mgr.is_first_run()

    with gr.Group(visible=is_first) as wizard_block:
        gr.Markdown("## 首次启动配置向导")
        gr.Markdown("请完成以下配置，全部可在后续设置中修改。")

        gr.Markdown("### 步骤 1: GPT-SoVITS 配置")
        gsv_root = gr.Textbox(
            label="GPT-SoVITS 本体路径",
            value=config_mgr.get("gsv_root", ""),
            placeholder="C:/.../GPT-SoVITS-v2pro-20250604",
        )
        tts_url = gr.Textbox(
            label="TTS API 地址",
            value=config_mgr.get("tts", {}).get("api_base_url", "http://127.0.0.1:9880"),
        )

        gr.Markdown("### 步骤 2: LLM 配置")
        provider_name = gr.Textbox(
            label="提供商名称", value="deepseek", placeholder="deepseek / openai / ..."
        )
        base_url = gr.Textbox(label="API Base URL", value="https://api.deepseek.com/v1")
        api_key = gr.Textbox(label="API Key", type="password")
        model = gr.Textbox(label="模型名称", value="deepseek-chat")
        max_tokens = gr.Slider(256, 8192, value=2048, step=256, label="Max Tokens")
        temperature = gr.Slider(0.0, 2.0, value=0.8, step=0.1, label="Temperature")
        text_language = gr.Dropdown(
            ["中文", "日本語", "English"], value="中文", label="回复文字语种"
        )

        gr.Markdown("### 步骤 3: 初始角色选择")
        gr.Dropdown(
            list_characters() or ["（暂无角色，可稍后创建）"],
            label="选择初始角色（可跳过）",
        )

        gr.Markdown("")
        finish_btn = gr.Button("完成配置", variant="primary")

    with gr.Group(visible=not is_first) as main_block:
        sidebar_initial_visible = not config_mgr.get("app", {}).get("sidebar_collapsed", False)
        sidebar_state = gr.State(value=sidebar_initial_visible)

        with gr.Row():
            sidebar_toggle_btn = gr.Button("☰ 侧栏", scale=0)
            lang_dd = gr.Dropdown(
                choices=[("中文", "zh_CN"), ("日本語", "ja_JP"), ("English", "en_US")],
                value=config_mgr.get("app", {}).get("language", "zh_CN"),
                label="界面语言",
                scale=1,
            )
            theme_dd = gr.Dropdown(
                choices=[("浅色", "light"), ("深色", "dark")],
                value=theme.mode(),
                label="主题",
                scale=1,
            )

        with gr.Row():
            # ---- 左栏（可折叠 + 独立滚动条） ----
            with gr.Column(
                scale=1, min_width=280, visible=sidebar_initial_visible, elem_id="sidebar-col"
            ):
                with gr.Accordion(i18n.t("角色"), open=False):
                    character_dropdown = gr.Dropdown(
                        choices=list_characters(), label=i18n.t("选择角色"), value=None
                    )
                    refresh_btn = gr.Button(i18n.t("刷新角色"))

                with gr.Accordion(i18n.t("编辑角色"), open=False):
                    editor_name = gr.Textbox(label=i18n.t("角色名称"))
                    editor_greeting = gr.Textbox(label=i18n.t("问候语"))
                    editor_personality = gr.Textbox(label=i18n.t("性格"))
                    editor_style = gr.Textbox(label=i18n.t("说话风格"))
                    editor_quirks = gr.Textbox(label=i18n.t("口癖（每行一条）"), lines=3)
                    editor_background = gr.Textbox(label=i18n.t("背景故事"), lines=3)
                    editor_likes = gr.Textbox(label=i18n.t("喜好（每行一条）"), lines=2)
                    editor_dislikes = gr.Textbox(label=i18n.t("厌恶（每行一条）"), lines=2)
                    editor_rules = gr.Textbox(label=i18n.t("行为准则（每行一条）"), lines=3)
                    editor_cot = gr.Textbox(label=i18n.t("思维链 (CoT)"), lines=3)
                    editor_lorebook = gr.Textbox(
                        label=i18n.t("Lorebook（关键词:内容 每行一条）"), lines=5
                    )
                    editor_portrait = gr.Image(label=i18n.t("上传头像"), type="filepath")
                    editor_save_btn = gr.Button(i18n.t("保存角色"))
                    editor_status = gr.Markdown(visible=False)

                with gr.Accordion(i18n.t("会话"), open=False):
                    new_session_btn = gr.Button(i18n.t("新建会话"))
                    session_radio = gr.Radio(
                        choices=session_options,
                        label=i18n.t("会话列表"),
                        value=ui_service.active_session,
                    )

                with gr.Accordion("配置", open=False):
                    _active_cfg = config_mgr.get_active_provider_config()
                    _active_name = config_mgr.get("llm", {}).get("active_provider", "deepseek")
                    cfg_gsv_root = gr.Textbox(
                        label="GPT-SoVITS 本体路径", value=config_mgr.get("gsv_root", "")
                    )
                    cfg_tts_url = gr.Textbox(
                        label="TTS API 地址",
                        value=config_mgr.get("tts", {}).get(
                            "api_base_url", "http://127.0.0.1:9880"
                        ),
                    )
                    cfg_provider = gr.Textbox(label="提供商名称", value=_active_name)
                    cfg_base_url = gr.Textbox(
                        label="API Base URL", value=_active_cfg.get("base_url", "")
                    )
                    cfg_api_key = gr.Textbox(
                        label="API Key",
                        type="password",
                        value=decrypt_api_key(_active_cfg.get("api_key", "")),
                    )
                    cfg_model = gr.Textbox(label="模型名称", value=_active_cfg.get("model", ""))
                    cfg_max_tokens = gr.Slider(
                        256,
                        8192,
                        value=int(_active_cfg.get("max_tokens", 2048)),
                        step=256,
                        label="Max Tokens",
                    )
                    cfg_temperature = gr.Slider(
                        0.0,
                        2.0,
                        value=float(_active_cfg.get("temperature", 0.8)),
                        step=0.1,
                        label="Temperature",
                    )
                    cfg_text_lang = gr.Dropdown(
                        ["中文", "日本語", "English"],
                        value=_active_cfg.get("text_language", "中文"),
                        label="回复文字语种",
                    )
                    cfg_save_btn = gr.Button("保存配置", variant="primary")
                    cfg_status = gr.Markdown(visible=False)

                with gr.Accordion("工具", open=False):
                    with gr.Row():
                        export_btn = gr.Button("导出会话")
                        import_btn = gr.Button("导入会话")
                    export_file = gr.File(label="导出文件", visible=False)
                    import_file = gr.File(label="导入 zip", type="filepath")
                    import_status = gr.Markdown(visible=False)
                    gr.Markdown("#### 搜索")
                    search_box = gr.Textbox(label="在本会话中搜索", placeholder="输入关键词")
                    search_results = gr.Markdown(visible=False)
                    stats_btn = gr.Button("查看统计")
                    stats_output = gr.Markdown(visible=False)

                gr.Markdown("### " + i18n.t("状态"))
                status_text = gr.Markdown(_status_text())

            # ---- 右栏 ----
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    label=i18n.t("聊天"), type="tuples", render_markdown=True, height=CHAT_HEIGHT
                )
                audio_player = gr.Audio(label=i18n.t("语音回复"), type="filepath", visible=False)
                with gr.Row():
                    fav_btn = gr.Button("⭐ 收藏最后一条回复")
                    fav_status = gr.Markdown(visible=False)

                with gr.Row():
                    text_lang_dd = gr.Dropdown(
                        ["中文", "日本語", "English"],
                        value=config_mgr.get("llm_providers", {})
                        .get(config_mgr.get("llm", {}).get("active_provider", ""), {})
                        .get("text_language", "中文"),
                        label=i18n.t("回复文字语种"),
                        scale=1,
                    )
                    voice_lang_dd = gr.Dropdown(
                        ["中文", "日本語", "English", "自动"],
                        value=config_mgr.get("tts", {}).get("voice_language", "中文"),
                        label=i18n.t("合成语音语种"),
                        scale=1,
                    )

                input_box = gr.Textbox(
                    label="输入消息", placeholder="Enter 发送，Shift+Enter 换行", lines=2
                )
                send_btn = gr.Button("发送", variant="primary")

        banner = gr.Markdown(visible=False)

    # ---- 事件绑定 ----
    finish_btn.click(
        fn=on_wizard_complete,
        inputs=[
            gsv_root,
            tts_url,
            provider_name,
            base_url,
            api_key,
            model,
            max_tokens,
            temperature,
            text_language,
        ],
        outputs=[wizard_block, main_block],
    )

    send_outputs = [banner, audio_player, chatbot, status_text, input_box]
    send_inputs = [input_box, text_lang_dd, voice_lang_dd]

    send_btn.click(fn=send_message_handler, inputs=send_inputs, outputs=send_outputs)
    input_box.submit(fn=send_message_handler, inputs=send_inputs, outputs=send_outputs)

    new_session_btn.click(
        fn=new_session_handler,
        outputs=[session_radio, chatbot, audio_player, status_text],
    )

    session_radio.change(
        fn=switch_session_handler,
        inputs=[session_radio],
        outputs=[chatbot, audio_player, banner, status_text],
    )

    character_dropdown.change(
        fn=select_character_handler,
        inputs=[character_dropdown],
        outputs=[status_text],
    )
    character_dropdown.change(
        fn=load_character_to_editor,
        inputs=[character_dropdown],
        outputs=[
            editor_name,
            editor_greeting,
            editor_personality,
            editor_style,
            editor_quirks,
            editor_background,
            editor_likes,
            editor_dislikes,
            editor_rules,
            editor_cot,
            editor_lorebook,
            editor_portrait,
        ],
    )

    refresh_btn.click(
        fn=refresh_characters_handler,
        outputs=[character_dropdown],
    )

    editor_save_btn.click(
        fn=save_character_handler,
        inputs=[
            character_dropdown,
            editor_name,
            editor_greeting,
            editor_personality,
            editor_style,
            editor_quirks,
            editor_background,
            editor_likes,
            editor_dislikes,
            editor_rules,
            editor_cot,
            editor_lorebook,
            editor_portrait,
        ],
        outputs=[editor_status, character_dropdown],
    )

    lang_dd.change(
        fn=save_language_handler,
        inputs=[lang_dd],
        outputs=[],
        js="() => { setTimeout(() => location.reload(), 300); }",
    )
    theme_dd.change(
        fn=save_theme_handler,
        inputs=[theme_dd],
        outputs=[],
        js="() => { setTimeout(() => location.reload(), 300); }",
    )

    sidebar_toggle_btn.click(
        fn=persist_sidebar_state,
        inputs=[sidebar_state],
        outputs=[sidebar_state],
        js="""(new_state) => {
            const col = document.getElementById('sidebar-col');
            if (col) col.style.display = new_state ? '' : 'none';
        }""",
    )

    cfg_save_btn.click(
        fn=save_settings_handler,
        inputs=[
            cfg_gsv_root,
            cfg_tts_url,
            cfg_provider,
            cfg_base_url,
            cfg_api_key,
            cfg_model,
            cfg_max_tokens,
            cfg_temperature,
            cfg_text_lang,
        ],
        outputs=[cfg_status],
    )

    export_btn.click(fn=export_session_handler, outputs=[export_file])
    import_btn.click(
        fn=import_session_handler,
        inputs=[import_file],
        outputs=[session_radio, import_status, chatbot, audio_player],
    )
    search_box.submit(
        fn=search_session_handler,
        inputs=[search_box],
        outputs=[search_results],
    )
    stats_btn.click(fn=stats_handler, outputs=[stats_output])
    fav_btn.click(fn=favorite_last_message_handler, outputs=[fav_status])

    health_timer = gr.Timer(value=30)
    health_timer.tick(fn=health_check_handler, outputs=[status_text])

    return wizard_block, main_block, status_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM 角色扮演聊天 + GPT-SoVITS TTS")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--share", action="store_true", help="启用 Gradio 公网分享")
    parser.add_argument("--port", type=int, default=None, help="指定端口（默认自动寻找）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.debug:
        setup_logger("app", debug=True)

    # 数据迁移（章节四十九）：启动时检测并执行
    migration_mgr = MigrationManager(
        config_mgr,
        PROJECT_ROOT / "migrations",
        backup_dir=PROJECT_ROOT / "backup",
        data_dir=PROJECT_ROOT,
    )
    ok, msg = migration_mgr.run()
    if not ok:
        logger.error(f"数据迁移失败: {msg}")

    with gr.Blocks(title="LLM 角色扮演聊天", css=theme.to_css() + SIDEBAR_CSS) as demo:
        _, _, status_text = build_wizard()
        demo.load(fn=health_check_handler, outputs=status_text)

    demo.queue(default_concurrency_limit=2)

    port = args.port or find_available_port(config_mgr.get("app", {}).get("port", 7861))
    logger.info(f"启动端口: {port}")
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=args.share,
        inbrowser=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"应用异常退出: {e}", exc_info=True)
        sys.exit(1)
