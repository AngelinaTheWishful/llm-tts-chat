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
from modules.config_manager import ConfigManager, apply_proxy_env, encrypt_api_key
from modules.conversation_manager import ConvManager
from modules.i18n import I18n
from modules.logger import setup_logger
from modules.migration import MigrationManager
from modules.theme import Theme
from modules.training_ops import TrainingOps, format_size
from modules.tts_client import TTSClient
from modules.ui_service import UiService

logger = setup_logger("app")
config_mgr = ConfigManager()
i18n = I18n()
i18n.switch(config_mgr.get("app", {}).get("language", "zh_CN"))
theme = Theme()
# R10：启动即按配置注入代理环境变量（requests/httpx 默认生效）
apply_proxy_env(config_mgr.get("proxy"))

PROJECT_ROOT = Path(__file__).resolve().parent
CHARACTERS_DIR = PROJECT_ROOT / "characters"
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations"

CHAT_HEIGHT = 500
_SIDEBAR_W = int(config_mgr.get("app", {}).get("sidebar_width", 320))
SIDEBAR_CSS = f"""
#sidebar-col {{
    height: {CHAT_HEIGHT}px;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 6px;
    flex: 0 0 {_SIDEBAR_W}px;
    width: {_SIDEBAR_W}px;
    min-width: 200px;
    max-width: 600px;
    /* Gradio 内联 flex-grow:1 会覆盖 flex 简写导致侧栏无限变宽挤占聊天区，强制不增长 */
    flex-grow: 0 !important;
    flex-shrink: 0 !important;
    /* Gradio 默认 flex-wrap:wrap 会让超高的折叠栏内容横向换列（表格跑到右侧），强制单列 */
    flex-wrap: nowrap !important;
}}
#sidebar-col .gradio-accordion {{ margin-bottom: 6px; }}
#sidebar-resizer {{
    width: 5px;
    flex-shrink: 0;
    cursor: col-resize;
    align-self: stretch;
    background: transparent;
    user-select: none;
}}
#sidebar-resizer-wrap {{
    flex-grow: 0 !important;
    flex-shrink: 0 !important;
    flex-basis: 5px !important;
    width: 5px !important;
    min-width: 5px !important;
    overflow: visible !important;
}}
#sidebar-resizer:hover, #sidebar-resizer.active {{ background: rgba(0,0,0,0.15); }}
body.resizing, body.resizing * {{ cursor: col-resize !important; user-select: none !important; }}
#sidebar-width-state {{ display: none !important; }}
#sidebar-collapse-state {{ display: none !important; }}
/* 章节八十六：移动端/响应式适配 */
@media (max-width: 900px) {{
    #top-row {{ flex-wrap: wrap; }}
    #main-row {{ flex-wrap: wrap; }}
    #sidebar-col {{
        flex: 0 0 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
        max-height: 40vh;
    }}
    #sidebar-resizer {{ display: none !important; }}
    #sidebar-resizer-wrap {{ display: none !important; }}
}}
"""

# 章节八十五：侧栏拖动调整宽度初始化 JS（页面加载即注入）
# 注意：Gradio 以 (${js})() 包装 js，必须为函数表达式而非 IIFE（分号会报错）
INIT_JS = """
function init_sidebar_resizer() {
    const MIN = 200, MAX = 600;
    const KEY = 'llm_tts_sidebar_width';
    function init() {
        const col = document.getElementById('sidebar-col');
        const res = document.getElementById('sidebar-resizer');
        if (!col || !res) { setTimeout(init, 300); return; }
        const apply = function (w) {
            w = Math.max(MIN, Math.min(MAX, w));
            col.style.width = w + 'px';
            col.style.flexBasis = w + 'px';
        };
        const saved = localStorage.getItem(KEY);
        if (saved) { apply(parseInt(saved, 10) || 320); }
        // 初始折叠状态：依据隐藏组件 sidebar-collapse-state（1=折叠）联动隐藏侧栏与分隔条
        const collapseWrap = document.getElementById('sidebar-collapse-state');
        const collapseInput = collapseWrap ? collapseWrap.querySelector('input') : null;
        const collapsed = collapseInput ? collapseInput.value === '1' : false;
        if (collapsed || !col.offsetParent) {
            col.style.display = 'none';
            res.style.display = 'none';
        }
        let dragging = false, startX = 0, startW = 0;
        res.addEventListener('mousedown', function (e) {
            e.preventDefault();
            dragging = true;
            startX = e.clientX;
            startW = parseInt(col.style.width, 10) || 320;
            res.classList.add('active');
            document.body.classList.add('resizing');
        });
        document.addEventListener('mousemove', function (e) {
            if (!dragging) { return; }
            apply(startW + (e.clientX - startX));
        });
        document.addEventListener('mouseup', function () {
            if (!dragging) { return; }
            dragging = false;
            res.classList.remove('active');
            document.body.classList.remove('resizing');
            const w = parseInt(col.style.width, 10) || 320;
            localStorage.setItem(KEY, String(w));
            const wrap = document.getElementById('sidebar-width-state');
            const input = wrap ? wrap.querySelector('input') : null;
            if (input) {
                input.value = w;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
    }
    init();
}
"""

char_mgr = CharManager(CHARACTERS_DIR, config_manager=config_mgr)
conv_mgr = ConvManager(CONVERSATIONS_DIR)
tts_client = TTSClient(config_mgr.get("tts", {}).get("api_base_url", "http://127.0.0.1:9880"))
ui_service = UiService(config_mgr, char_mgr, conv_mgr, tts_client)

_gt_cfg = config_mgr.get("gsv_training", {})
training_ops = TrainingOps(
    gsv_root=_gt_cfg.get("gsv_root", ""),
    archive_dir=_gt_cfg.get("archive_dir", ""),
    restore_dir=_gt_cfg.get("restore_dir", ""),
)

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
    # R7：TTS 不可用时给出可见提示（黄色），而非静默无语音
    notice = result.get("tts_notice") or ""
    banner_value = f"🟡 {notice}" if notice else ""
    return (
        gr.update(visible=bool(notice), value=banner_value),
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


def import_card_handler(file):
    """导入角色卡（章节六十九~七十一：自动检测格式）。"""
    if isinstance(file, dict):  # gradio_client 上传后可能传 FileData
        file = file.get("path") or file.get("name") or None
    if not file:
        return (
            gr.update(value="🔴 请选择角色卡文件"),
            gr.update(choices=list_characters()),
        )
    try:
        imported, warnings = char_mgr.import_card(file)
    except Exception as e:
        return (
            gr.update(value=f"🔴 导入失败: {e}"),
            gr.update(choices=list_characters()),
        )
    lines = []
    if imported:
        lines.append("🟢 导入成功: " + "、".join(imported))
    else:
        lines.append("🔴 未导入任何角色")
    lines.extend("⚠️ " + w for w in warnings[:6])
    if len(warnings) > 6:
        lines.append(f"⚠️ 等共 {len(warnings)} 条警告")
    return (
        gr.update(value="\n".join(lines)),
        gr.update(choices=list_characters()),
    )


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
    training_voice,
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

    # 训练音色联动（章节八十二）：选择已恢复实验后写入音色预设
    if training_voice:
        restored = training_ops.find_restored_weights(training_voice)
        if restored["gpt"] or restored["sovits"]:
            rs = character.setdefault("recommended_settings", {})
            if restored["gpt"]:
                rs["gpt_model"] = restored["gpt"]
            if restored["sovits"]:
                rs["sovits_model"] = restored["sovits"]

    char_mgr.save_character(character)

    if portrait_path:
        try:
            char_mgr.update_portrait(name, portrait_path)
        except Exception as e:
            logger.warning(f"头像更新失败: {e}")

    gr.Info(f"🟢 角色「{name}」已保存")
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


# ---------- 会话回收站（R3） ----------


def delete_session_handler():
    """删除当前会话（移入回收站）。"""
    if not ui_service.active_session:
        return (
            gr.update(value=""),
            gr.update(value=[]),
            gr.update(visible=False, value=None),
            _status_text(),
            gr.update(value="🔴 请先选择会话"),
        )
    sid = ui_service.active_session
    ui_service.delete_session(sid)
    sessions = conv_mgr.list_sessions()
    return (
        gr.update(choices=[(s["name"], s["id"]) for s in sessions], value=None),
        gr.update(value=[]),
        gr.update(visible=False, value=None),
        _status_text(),
        gr.update(value="🟢 会话已删除，可在「工具-回收站」恢复"),
    )


def trash_hint_text() -> str:
    """回收站满 30 天提醒（R3）。"""
    expired = conv_mgr.trash_expired(30)
    if expired:
        return f"🔔 回收站有 {len(expired)} 个会话已满 30 天，建议在工具中清理"
    return ""


def refresh_trash_handler():
    trash = conv_mgr.list_trash()
    choices = [
        (f"{t['original_id']}（{str(t['deleted_at'])[:16].replace('T', ' ')}）", t["id"])
        for t in trash
    ]
    return gr.update(choices=choices), gr.update(value=trash_hint_text())


def restore_trash_handler(trash_id):
    if not trash_id:
        return gr.update(value="🔴 请先选择要恢复的会话")
    sid = conv_mgr.restore_from_trash(trash_id)
    if not sid:
        return gr.update(value="🔴 恢复失败")
    sessions = conv_mgr.list_sessions()
    return (
        gr.update(value=f"🟢 已恢复会话: {sid}"),
        gr.update(choices=[(s["name"], s["id"]) for s in sessions]),
    )


def empty_trash_handler():
    n = conv_mgr.empty_trash()
    return gr.update(value=f"🟢 已清空回收站（{n} 项）"), gr.update(choices=[])


def status_and_trash_handler():
    """健康检查 + 回收站提醒合并（供 30s 定时器与页面加载）。"""
    ui_service.check_health()
    return gr.update(value=_status_text()), gr.update(value=trash_hint_text())


# ---------- 会话级 LLM 提供商（R12） ----------


def current_session_provider_handler(session_id):
    if not session_id:
        return gr.update(value="")
    p = ui_service.get_session_provider(session_id)
    # 下拉 value 用空串（其标签为「跟随全局」），不能用标签文本，否则会被当作提供商写入 provider.txt
    return gr.update(value=p or "")


def set_session_provider_handler(provider):
    if not ui_service.active_session:
        return gr.update(value="🔴 请先选择会话")
    ok = ui_service.set_session_provider(ui_service.active_session, provider)
    if not ok:
        return gr.update(value="🔴 设置失败")
    label = provider or "跟随全局"
    return gr.update(value=f"🟢 本会话提供商: {label}")


# ---------- 高级设置（R10） ----------


def save_advanced_settings_handler(
    device,
    max_llm_concurrency,
    max_tts_concurrency,
    idle_minutes,
    warning_minutes,
    notif_enabled,
    sound_file,
    volume,
    proxy_enabled,
    http,
    https,
    no_proxy,
    mem_enabled,
    mem_scope,
    recall_limit,
    mem_llm,
):
    cfg = config_mgr.get_raw()
    perf = cfg.setdefault("performance", {})
    perf["device"] = device or "auto"
    perf["max_llm_concurrency"] = int(max_llm_concurrency or 2)
    perf["max_tts_concurrency"] = int(max_tts_concurrency or 1)
    st = cfg.setdefault("session_timeout", {})
    st["idle_minutes"] = int(idle_minutes or 30)
    st["warning_minutes"] = int(warning_minutes or 25)
    notif = cfg.setdefault("notification_sound", {})
    notif["enabled"] = bool(notif_enabled)
    notif["sound_file"] = (sound_file or "").strip()
    notif["volume"] = float(volume or 0.7)
    proxy = cfg.setdefault("proxy", {})
    proxy["enabled"] = bool(proxy_enabled)
    proxy["http"] = (http or "").strip()
    proxy["https"] = (https or "").strip()
    proxy["no_proxy"] = [x.strip() for x in (no_proxy or "").split(",") if x.strip()]
    memory = cfg.setdefault("memory", {})
    memory["enabled"] = bool(mem_enabled)
    memory["scope"] = mem_scope or "character"
    memory["recall_limit"] = int(recall_limit or 5)
    memory["extract_with_llm"] = bool(mem_llm)
    config_mgr.replace(cfg)
    # R10：代理真实接线（注入环境变量）
    apply_proxy_env(proxy)
    logger.info("高级设置已保存（性能/会话超时/通知音效/代理/记忆）")
    gr.Info("🟢 高级设置已保存，即时生效")
    return gr.update(value="🟢 高级设置已保存，即时生效")


def clear_memory_handler():
    """清空当前作用域记忆。"""
    scope = config_mgr.get("memory", {}).get("scope", "character")
    key = "global" if scope == "global" else (ui_service.active_character or "default")
    n = ui_service.memory_store.clear(scope=scope, key=key)
    return gr.update(value=f"🟢 已清空记忆（{n} 条）")


# ---------- 训练管理（章节八十二） ----------


def refresh_training_choices():
    """刷新训练管理面板的实验/归档/恢复下拉。"""
    experiments = [e["experiment"] for e in training_ops.scan_experiments()]
    archives = [a["path"] for a in training_ops.list_archives()]
    restored = training_ops.list_restored()
    return (
        gr.update(choices=experiments),
        gr.update(choices=archives),
        gr.update(choices=restored),
    )


def preview_training_handler(experiment):
    if not experiment:
        return gr.update(value="🔴 请先选择训练实验")
    result = training_ops.preview_pack(experiment)
    if not result["ok"]:
        return gr.update(value=f"🔴 {result['error']}")
    lines = [
        f"## 预览打包「{experiment}」",
        f"- 归档: {result['zip']}",
        f"- 文件数: {len(result['files'])} 大小: {format_size(result['size'])}",
        "",
        "### 文件清单",
    ]
    lines += [f"- {f}" for f in result["files"]]
    return gr.update(value="\n".join(lines))


def pack_training_handler(experiment):
    if not experiment:
        return gr.update(value="🔴 请先选择训练实验")
    result = training_ops.pack_experiment(experiment)
    if not result["ok"]:
        return gr.update(value=f"🔴 {result['error']}")
    msg = (
        f"🟢 打包完成: {result['zip']}"
        f"（{len(result['files'])} 文件，{format_size(result['size'])}）"
    )
    if config_mgr.get("gsv_training", {}).get("cleanup_after_pack", True):
        clean = training_ops.cleanup_intermediates(experiment)
        if clean["ok"]:
            msg += f"\n🟢 中间素材已清理: {clean.get('cleaned', 0)} 项"
        else:
            msg += f"\n🔴 清理失败: {clean.get('error', '')}"
    return gr.update(value=msg)


def restore_training_handler(archive_path, write_back):
    if not archive_path:
        return gr.update(value="🔴 请先选择归档 zip")
    result = training_ops.restore_archive(archive_path, write_back=bool(write_back))
    if not result["ok"]:
        return gr.update(value=f"🔴 {result['error']}")
    msg = f"🟢 已恢复: {result['dest']}"
    if result["written_back"]:
        msg += f"（写回 {len(result['written_back'])} 文件）"
    return gr.update(value=msg)


def auto_detect_handler():
    """自动检测训练完成：默认仅提醒，auto_full 时自动打包清理。"""
    gt = config_mgr.get("gsv_training", {})
    if not gt.get("auto_detect", False):
        return gr.update(value="")
    completed = training_ops.detect_completed(idle_minutes=10)
    if not completed:
        return gr.update(value="")

    lines = []
    for c in completed:
        if c["has_archive"]:
            continue
        if gt.get("auto_full", False):
            pack = training_ops.pack_experiment(c["experiment"])
            if pack["ok"] and gt.get("cleanup_after_pack", True):
                training_ops.cleanup_intermediates(c["experiment"])
            lines.append(f"- {c['experiment']}（{c['size_text']}）→ 已自动打包清理")
        else:
            lines.append(f"- {c['experiment']}（{c['size_text']}，未归档）")
    if not lines:
        return gr.update(value="")
    hint = (
        "\n\n可在「训练管理」面板选择实验后点击「打包并清理」"
        if not gt.get("auto_full", False)
        else ""
    )
    return gr.update(value="🔔 疑似训练完成:\n" + "\n".join(lines) + hint)


def save_training_settings_handler(gsv_root, cleanup_after, auto_detect, auto_full):
    """保存训练管理配置（即时生效）。"""
    cfg = config_mgr.get_raw()
    gt = cfg.setdefault("gsv_training", {})
    gt["gsv_root"] = gsv_root or ""
    gt["cleanup_after_pack"] = bool(cleanup_after)
    gt["auto_detect"] = bool(auto_detect)
    gt["auto_full"] = bool(auto_full)
    config_mgr.replace(cfg)
    training_ops.gsv_root = Path(gsv_root).resolve() if gsv_root else Path("")
    gr.Info("🟢 训练配置已保存，即时生效")
    return gr.update(value="🟢 训练配置已保存，即时生效")


# ---------- 侧栏折叠 / 配置保存（Phase 9） ----------


def persist_sidebar_state(collapsed: int) -> int:
    """侧栏折叠状态持久化（0=展开，1=折叠）。"""
    config_mgr.update("app", "sidebar_collapsed", collapsed == 1)
    return collapsed


def save_sidebar_width(width):
    """保存侧栏宽度（章节八十五：拖动结束由前端隐藏组件派发触发）。"""
    try:
        config_mgr.update("app", "sidebar_width", int(width))
        logger.info(f"侧栏宽度已保存: {width}")
        return ""
    except (TypeError, ValueError):
        return ""


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
            "api_key": encrypt_api_key(api_key.strip()) if api_key else provider.get("api_key", ""),
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
    gr.Info("🟢 配置已保存，即时生效")
    return gr.update(value="🟢 配置已保存，即时生效")


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
        "api_key": encrypt_api_key(api_key.strip()) if api_key else "",
        "model": model,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
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
        sidebar_initial_collapsed = bool(config_mgr.get("app", {}).get("sidebar_collapsed", False))

        with gr.Row(elem_id="top-row"):
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

        with gr.Row(elem_id="main-row"):
            # ---- 左栏（可折叠 + 独立滚动条） ----
            # 始终 visible=True，初始折叠由 INIT_JS 依据 sidebar-collapse-state 隐藏（Gradio
            # visible=False 的隐藏无法被前端 js 覆盖，会导致初始折叠后无法展开）
            with gr.Column(scale=1, min_width=200, visible=True, elem_id="sidebar-col"):
                with gr.Accordion(i18n.t("角色"), open=False):
                    character_dropdown = gr.Dropdown(
                        choices=list_characters(), label=i18n.t("选择角色"), value=None
                    )
                    refresh_btn = gr.Button(i18n.t("刷新角色"))
                    card_import_file = gr.File(
                        label="导入角色卡（TavernAI/RisuAI/Chub/CAI）",
                        type="filepath",
                        file_types=[".png", ".json", ".risuai", ".txt"],
                    )
                    card_import_btn = gr.Button("导入角色卡")
                    card_import_status = gr.Markdown(visible=False)

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
                    editor_voice_dd = gr.Dropdown(
                        choices=training_ops.list_restored(),
                        label=i18n.t("训练音色（已恢复）"),
                        info=i18n.t("选择后保存将写入音色预设"),
                        value=None,
                    )
                    editor_save_btn = gr.Button(i18n.t("保存角色"))
                    editor_status = gr.Markdown(visible=False)

                with gr.Accordion(i18n.t("会话"), open=False):
                    new_session_btn = gr.Button(i18n.t("新建会话"))
                    session_radio = gr.Radio(
                        choices=session_options,
                        label=i18n.t("会话列表"),
                        value=ui_service.active_session,
                    )
                    delete_session_btn = gr.Button(i18n.t("删除会话（入回收站）"))
                    delete_session_status = gr.Markdown(visible=False)

                with gr.Accordion("配置", open=False):
                    _active_cfg = config_mgr.get_active_provider_config()
                    _active_name = config_mgr.get("llm", {}).get("active_provider", "deepseek")
                    _provider_names = list(config_mgr.get("llm_providers", {}).keys())
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
                    # R11：API Key 前端遮蔽——不回填明文，留空保持不变
                    cfg_api_key = gr.Textbox(
                        label="API Key",
                        type="password",
                        value="",
                        placeholder="已保存密钥，留空保持不变",
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
                    # R12：本会话 LLM 提供商覆盖
                    cfg_session_provider = gr.Dropdown(
                        choices=[("跟随全局", "")] + [(n, n) for n in _provider_names],
                        value="",
                        label="本会话提供商（可选）",
                        info="选择后仅本会话使用该提供商",
                    )
                    cfg_save_btn = gr.Button("保存配置", variant="primary")
                    cfg_status = gr.Markdown(visible=False)

                with gr.Accordion("高级设置", open=False):
                    _perf = config_mgr.get("performance", {})
                    _st = config_mgr.get("session_timeout", {})
                    _notif = config_mgr.get("notification_sound", {})
                    _proxy = config_mgr.get("proxy", {})
                    _mem = config_mgr.get("memory", {})
                    gr.Markdown("### 性能")
                    adv_device = gr.Dropdown(
                        ["auto", "GPU", "CPU"],
                        value=_perf.get("device", "auto"),
                        label="设备选择",
                    )
                    adv_llm_conc = gr.Slider(
                        1,
                        8,
                        value=int(_perf.get("max_llm_concurrency", 2)),
                        step=1,
                        label="LLM 最大并发数",
                    )
                    adv_tts_conc = gr.Slider(
                        1,
                        4,
                        value=int(_perf.get("max_tts_concurrency", 1)),
                        step=1,
                        label="TTS 最大并发数",
                    )
                    gr.Markdown("### 会话超时")
                    adv_idle = gr.Slider(
                        5,
                        120,
                        value=int(_st.get("idle_minutes", 30)),
                        step=5,
                        label="闲置分钟数",
                    )
                    adv_warn = gr.Slider(
                        1,
                        60,
                        value=int(_st.get("warning_minutes", 25)),
                        step=1,
                        label="预警分钟数",
                    )
                    gr.Markdown("### 通知音效")
                    adv_notif_enabled = gr.Checkbox(
                        value=_notif.get("enabled", True), label="启用通知音效"
                    )
                    adv_sound_file = gr.Textbox(
                        value=_notif.get("sound_file", ""), label="音效文件路径"
                    )
                    adv_volume = gr.Slider(
                        0.0,
                        1.0,
                        value=float(_notif.get("volume", 0.7)),
                        step=0.1,
                        label="音量",
                    )
                    gr.Markdown("### 代理（注入环境变量，LLM/TTS 生效）")
                    adv_proxy_enabled = gr.Checkbox(
                        value=_proxy.get("enabled", False), label="启用代理"
                    )
                    adv_http = gr.Textbox(value=_proxy.get("http", ""), label="HTTP 代理")
                    adv_https = gr.Textbox(value=_proxy.get("https", ""), label="HTTPS 代理")
                    adv_no_proxy = gr.Textbox(
                        value=",".join(_proxy.get("no_proxy", []) or []),
                        label="NO_PROXY（逗号分隔）",
                    )
                    gr.Markdown("### 长期记忆")
                    adv_mem_enabled = gr.Checkbox(
                        value=_mem.get("enabled", True), label="启用长期记忆"
                    )
                    adv_mem_scope = gr.Dropdown(
                        [("角色级", "character"), ("全局", "global")],
                        value=_mem.get("scope", "character"),
                        label="记忆作用域",
                    )
                    adv_mem_limit = gr.Slider(
                        1, 10, value=int(_mem.get("recall_limit", 5)), step=1, label="召回条数"
                    )
                    adv_mem_llm = gr.Checkbox(
                        value=_mem.get("extract_with_llm", False), label="摘要时用 LLM 提取记忆"
                    )
                    with gr.Row():
                        adv_save_btn = gr.Button("保存高级设置", variant="primary")
                        adv_clear_mem_btn = gr.Button("清空当前记忆")
                    adv_status = gr.Markdown(visible=False)

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
                    gr.Markdown("#### 回收站")
                    trash_refresh_btn = gr.Button("刷新回收站")
                    trash_dd = gr.Dropdown(label="回收站会话", choices=[], value=None)
                    with gr.Row():
                        trash_restore_btn = gr.Button("恢复会话")
                        trash_empty_btn = gr.Button("清空回收站")
                    trash_status = gr.Markdown(visible=False)

                with gr.Accordion("训练管理", open=False):
                    tr_gsv_root = gr.Textbox(
                        label="GPT-SoVITS 路径",
                        value=_gt_cfg.get("gsv_root", ""),
                        placeholder="C:/.../GPT-SoVITS-v2pro-20250604",
                    )
                    with gr.Row():
                        tr_exp_dd = gr.Dropdown(
                            label="训练实验",
                            choices=[e["experiment"] for e in training_ops.scan_experiments()],
                            value=None,
                        )
                        tr_refresh_btn = gr.Button("刷新")
                    with gr.Row():
                        tr_preview_btn = gr.Button("预览打包")
                        tr_pack_btn = gr.Button("打包并清理")
                    tr_cleanup_cb = gr.Checkbox(
                        label="打包后清理中间素材",
                        value=_gt_cfg.get("cleanup_after_pack", True),
                    )
                    tr_auto_detect = gr.Checkbox(
                        label="自动检测训练完成（提醒）",
                        value=_gt_cfg.get("auto_detect", False),
                    )
                    tr_auto_full = gr.Checkbox(
                        label="全自动打包清理（auto_full）",
                        value=_gt_cfg.get("auto_full", False),
                    )
                    tr_save_cfg_btn = gr.Button("保存训练配置")
                    with gr.Row():
                        tr_archive_dd = gr.Dropdown(
                            label="归档 zip",
                            choices=[a["path"] for a in training_ops.list_archives()],
                            value=None,
                        )
                        tr_writeback_cb = gr.Checkbox(label="写回 GPT-SoVITS", value=False)
                    tr_restore_btn = gr.Button("恢复归档")
                    tr_status = gr.Markdown(visible=False)

                gr.Markdown("### " + i18n.t("状态"))
                status_text = gr.Markdown(_status_text())

            # ---- 章节八十五：侧栏可拖动分隔条（容器禁增长，避免挤占聊天区） ----
            gr.HTML(
                '<div id="sidebar-resizer" title="拖动调整侧栏宽度"></div>',
                elem_id="sidebar-resizer-wrap",
            )

            # ---- 右栏 ----
            with gr.Column(scale=2):
                # 隐藏同步组件放在聊天列内部（避免成为 main-row 的直接 flex 子项，
                # 否则其 form 包装会 flex-grow 占位、挤压聊天区）
                sidebar_width_state = gr.Number(elem_id="sidebar-width-state")
                # 折叠状态同步组件（0=展开，1=折叠；与宽度同款隐藏组件模式，避免 gr.State 触发
                # Gradio "Too many arguments" 导致折叠事件失效）
                sidebar_collapse_state = gr.Number(
                    value=int(sidebar_initial_collapsed), elem_id="sidebar-collapse-state"
                )
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
    # R12：切换会话时刷新「本会话提供商」下拉
    session_radio.change(
        fn=current_session_provider_handler,
        inputs=[session_radio],
        outputs=[cfg_session_provider],
    )

    delete_session_btn.click(
        fn=delete_session_handler,
        outputs=[session_radio, chatbot, audio_player, status_text, delete_session_status],
    )

    trash_refresh_btn.click(
        fn=refresh_trash_handler,
        outputs=[trash_dd, trash_status],
    )
    trash_restore_btn.click(
        fn=restore_trash_handler,
        inputs=[trash_dd],
        outputs=[trash_status, session_radio],
    )
    trash_empty_btn.click(
        fn=empty_trash_handler,
        outputs=[trash_status, trash_dd],
    )

    cfg_session_provider.change(
        fn=set_session_provider_handler,
        inputs=[cfg_session_provider],
        outputs=[cfg_status],
    )

    adv_save_btn.click(
        fn=save_advanced_settings_handler,
        inputs=[
            adv_device,
            adv_llm_conc,
            adv_tts_conc,
            adv_idle,
            adv_warn,
            adv_notif_enabled,
            adv_sound_file,
            adv_volume,
            adv_proxy_enabled,
            adv_http,
            adv_https,
            adv_no_proxy,
            adv_mem_enabled,
            adv_mem_scope,
            adv_mem_limit,
            adv_mem_llm,
        ],
        outputs=[adv_status],
    )
    adv_clear_mem_btn.click(
        fn=clear_memory_handler,
        outputs=[adv_status],
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

    card_import_btn.click(
        fn=import_card_handler,
        inputs=[card_import_file],
        outputs=[card_import_status, character_dropdown],
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
            editor_voice_dd,
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
        inputs=[sidebar_collapse_state],
        outputs=[sidebar_collapse_state],
        js="""(v) => {
            const next = v === 1 ? 0 : 1;
            const col = document.getElementById('sidebar-col');
            const res = document.getElementById('sidebar-resizer');
            if (col) col.style.display = next === 1 ? 'none' : '';
            if (res) res.style.display = next === 1 ? 'none' : '';
            return next;
        }""",
    )

    # 章节八十五：拖动结束后由前端隐藏组件派发，写回 config.app.sidebar_width
    sidebar_width_state.change(
        fn=save_sidebar_width,
        inputs=[sidebar_width_state],
        outputs=[],
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

    tr_refresh_btn.click(
        fn=refresh_training_choices,
        outputs=[tr_exp_dd, tr_archive_dd, editor_voice_dd],
    )
    tr_preview_btn.click(
        fn=preview_training_handler,
        inputs=[tr_exp_dd],
        outputs=[tr_status],
    )
    tr_pack_btn.click(
        fn=pack_training_handler,
        inputs=[tr_exp_dd],
        outputs=[tr_status],
    )
    tr_restore_btn.click(
        fn=restore_training_handler,
        inputs=[tr_archive_dd, tr_writeback_cb],
        outputs=[tr_status],
    )
    tr_save_cfg_btn.click(
        fn=save_training_settings_handler,
        inputs=[tr_gsv_root, tr_cleanup_cb, tr_auto_detect, tr_auto_full],
        outputs=[tr_status],
    )

    health_timer = gr.Timer(value=30)
    health_timer.tick(fn=status_and_trash_handler, outputs=[status_text, trash_status])

    training_timer = gr.Timer(value=60)
    training_timer.tick(fn=auto_detect_handler, outputs=[tr_status])

    return wizard_block, main_block, status_text, trash_status


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

    with gr.Blocks(
        title="LLM 角色扮演聊天",
        css=theme.to_css() + SIDEBAR_CSS,
        js=INIT_JS,
    ) as demo:
        _, _, status_text, trash_status = build_wizard()
        demo.load(fn=status_and_trash_handler, outputs=[status_text, trash_status])

    # 并发数接线（高级设置 R10 保存的值真正生效）：LLM 并发 → queue 默认并发；TTS 由
    # TTSClient 内部 TTSSerializer 全局串行化，天然并发=1
    _perf_cfg = config_mgr.get("performance", {})
    _llm_conc = int(_perf_cfg.get("max_llm_concurrency", 2) or 2)
    demo.queue(default_concurrency_limit=max(1, _llm_conc))

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
