"""LLM 角色扮演聊天 + GPT-SoVITS TTS — Gradio 主入口。

Phase 4：左右分栏主界面 + 配置向导（条件可见性）。
"""

import argparse
import ctypes
import json
import os
import socket
import sys
from pathlib import Path

import gradio as gr

from modules.backup import BackupManager
from modules.character_manager import CharManager
from modules.config_manager import ConfigManager, apply_proxy_env, encrypt_api_key
from modules.conversation_manager import ConvManager
from modules.error_codes import format_error
from modules.i18n import I18n
from modules.logger import setup_logger
from modules.migration import MigrationManager
from modules.reporter import write_entry
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
/* 章节八十八 88.4：使用帮助/侧栏说明宽度与面板样式 */
#main-help-panel {{
    max-width: {_SIDEBAR_W}px;
    margin-bottom: 6px;
}}
#main-help-panel .gradio-markdown {{ max-width: {_SIDEBAR_W}px; }}
#side-help-panel {{ margin-bottom: 6px; }}
/* 章节九十二：角色聊天背景（聊天主区域背景 + 遮罩） */
#chat-bg-state {{ display: none !important; }}
#chat-area {{
    position: relative;
    background-repeat: no-repeat;
    background-position: center;
    background-size: cover;
    overflow: hidden;
}}
#chat-area::before {{
    content: "";
    position: absolute;
    inset: 0;
    background-color: var(--chat-overlay-color, #FFFFFF);
    opacity: var(--chat-overlay-opacity, 0.4);
    pointer-events: none;
    z-index: 0;
    display: none;
}}
#chat-area.chat-bg-on::before {{ display: block; }}
#chat-area > * {{ position: relative; z-index: 1; }}
/* 聊天容器背景透明：Gradio 组件外层 .block 有不透明背景（--block-background-fill），
   必须一并透明，否则会盖住 #chat-area 的背景图与遮罩 */
#chat-area > *,
#chat-area .chatbot,
#chat-area .chatbot-wrap,
#chat-area .messages {{ background: transparent !important; }}
/* 章节九十三：聊天窗口左上角角色头像（独立固定头部，透明不遮挡聊天背景） */
#chat-header-wrap {{
    flex: 0 0 auto !important;
    overflow: visible !important;
}}
#chat-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    margin-bottom: 4px;
    background: transparent !important;
    position: relative;
    z-index: 2;
}}
#chat-header .avatar-container {{
    width: var(--chat-avatar-size, 128px);
    height: var(--chat-avatar-size, 128px);
    flex-shrink: 0;
    position: relative;
    border-radius: 50%;
    overflow: hidden;
    background: rgba(128,128,128,0.25);
    display: flex;
    align-items: center;
    justify-content: center;
}}
#chat-header .avatar-container img.chat-avatar-img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 50%;
    display: block;
}}
#chat-header .avatar-container span.avatar-placeholder {{
    font-size: calc(var(--chat-avatar-size, 128px) * 0.42);
    color: #FFFFFF;
    font-weight: 600;
    user-select: none;
}}
#chat-header .chat-avatar-name {{
    font-size: 18px;
    font-weight: 600;
    color: var(--text-color);
    text-shadow: 0 1px 2px rgba(0,0,0,0.25);
}}
/* 头部透明化（组件外层 .block 有 --block-background-fill 不透明背景，须一并透明） */
#chat-area #chat-header-wrap,
#chat-area #chat-header-wrap .block,
#chat-area #chat-header-wrap .gr-html {{ background: transparent !important; }}
#chat-avatar-state {{ display: none !important; }}
#chat-avatar-size-state {{ display: none !important; }}
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
# 章节九十二：增加聊天背景/遮罩应用函数（暴露到 window 供事件 js 调用）
INIT_JS = """
function init_ui() {
    // ---- 章节九十二：角色聊天背景 ----
    function applyChatOverlay(enabled, opacity, mode, color) {
        const area = document.getElementById('chat-area');
        if (!area) return;
        const on = area.classList.contains('chat-bg-on') && !!enabled;
        const op = Math.max(0, Math.min(0.9, parseFloat(opacity) || 0));
        area.style.setProperty('--chat-overlay-opacity', on ? String(op) : '0');
        if (mode === 'custom' && color) {
            area.style.setProperty('--chat-overlay-color', color);
        } else {
            area.style.removeProperty('--chat-overlay-color');
        }
    }
    function applyChatBackground(path, enabled, opacity, mode, color) {
        const area = document.getElementById('chat-area');
        if (!area) return;
        const p = (path || '').trim();
        if (p && enabled) {
            const url = '/file=' + encodeURI(p.replace(/\\\\/g, '/')) + '?ts=' + Date.now();
            area.classList.add('chat-bg-on');
            area.style.backgroundImage = "url('" + url + "')";
        } else {
            area.classList.remove('chat-bg-on');
            area.style.backgroundImage = '';
        }
        applyChatOverlay(enabled, opacity, mode, color);
    }
    window.applyChatBackground = applyChatBackground;
    window.applyChatOverlay = applyChatOverlay;

    // ---- 章节九十三：聊天窗口左上角角色头像 ----
    function applyChatAvatar(path, name) {
        const wrap = document.getElementById('chat-header');
        if (!wrap) return;
        const img = wrap.querySelector('.chat-avatar-img');
        const ph = wrap.querySelector('.avatar-placeholder');
        const nm = wrap.querySelector('.chat-avatar-name');
        if (nm) nm.textContent = (name || '').trim();
        const p = (path || '').trim();
        if (img && p) {
            const url = '/file=' + encodeURI(p.replace(/\\\\/g, '/')) + '?ts=' + Date.now();
            img.src = url;
            img.style.display = 'block';
            if (ph) ph.style.display = 'none';
        } else {
            if (img) { img.src = ''; img.style.display = 'none'; }
            if (ph) {
                const ch = (name || '').trim().charAt(0);
                ph.textContent = ch || '?';
                ph.style.display = 'block';
            }
        }
    }
    function applyChatAvatarSize(size) {
        const wrap = document.getElementById('chat-header');
        if (wrap) {
            wrap.style.setProperty('--chat-avatar-size', (parseInt(size, 10) || 128) + 'px');
        }
    }
    window.applyChatAvatar = applyChatAvatar;
    window.applyChatAvatarSize = applyChatAvatarSize;

    // ---- 章节八十五：侧栏拖动调整宽度 ----
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
        // 章节九十二：初始无角色背景，刷新后恢复主题背景（路径为空则清除）
        const bgWrap = document.getElementById('chat-bg-state');
        const bgInput = bgWrap ? bgWrap.querySelector('input, textarea') : null;
        applyChatBackground(bgInput ? bgInput.value : '', false, 0, 'auto', '');
        // 章节九十三：初始头像状态（路径 + 角色名）+ 持久化尺寸
        const avWrap = document.getElementById('chat-avatar-state');
        const avInput = avWrap ? avWrap.querySelector('input, textarea') : null;
        let av = '';
        let avName = '';
        try {
            const parsed = avInput ? JSON.parse(avInput.value || '{}') : {};
            av = parsed.path || '';
            avName = parsed.name || '';
        } catch (e) { /* 忽略解析错误，回落空状态 */ }
        applyChatAvatar(av, avName);
        const szWrap = document.getElementById('chat-avatar-size-state');
        const szInput = szWrap ? szWrap.querySelector('input') : null;
        applyChatAvatarSize(szInput ? szInput.value : 128);
    }
    init();
}
"""

char_mgr = CharManager(CHARACTERS_DIR, config_manager=config_mgr)
# Q5：会话管理读取 app.max_history_rounds / app.summarize_trigger_rounds 配置（原用默认参数）
_app_cfg = config_mgr.get("app", {})
conv_mgr = ConvManager(
    CONVERSATIONS_DIR,
    max_history_rounds=int(_app_cfg.get("max_history_rounds", 4)),
    summarize_trigger_rounds=int(_app_cfg.get("summarize_trigger_rounds", 20)),
)
tts_client = TTSClient(config_mgr.get("tts", {}).get("api_base_url", "http://127.0.0.1:9880"))
ui_service = UiService(config_mgr, char_mgr, conv_mgr, tts_client)

_gt_cfg = config_mgr.get("gsv_training", {})
# 章节九十四：训练根路径为空时自动继承主 gsv_root
training_ops = TrainingOps(
    gsv_root=config_mgr.get_effective_gsv_root(),
    archive_dir=_gt_cfg.get("archive_dir", ""),
    restore_dir=_gt_cfg.get("restore_dir", ""),
)

# Q8：自动备份（backup/，启动 + 定时）
_bk_cfg = config_mgr.get("backup", {})
backup_mgr = BackupManager(
    PROJECT_ROOT,
    backup_root=PROJECT_ROOT / "backup",
    keep_count=int(_bk_cfg.get("keep_count", 3) or 3),
)

session_options = [(s["name"], s["id"]) for s in conv_mgr.list_sessions()]


def _pid_alive(pid: int) -> bool:
    """检查 PID 是否存活（Windows）。"""
    if not pid or pid <= 0:
        return False
    process_query_limited = 0x1000
    try:
        h = ctypes.windll.kernel32.OpenProcess(process_query_limited, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


def acquire_single_instance(lock_path: Path) -> bool:
    """获取单实例锁（app.lock 含 PID）。

    - 锁存在且 PID 存活 → 已有实例在跑，返回 False（拒绝启动）
    - 锁存在但 PID 已死 → 清除残留锁后重新获取
    - 写锁失败（如权限）→ 不阻塞启动，返回 True
    """
    try:
        if lock_path.exists():
            text = lock_path.read_text(encoding="utf-8").strip()
            if text.isdigit() and _pid_alive(int(text)):
                return False
            lock_path.unlink(missing_ok=True)
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return True


def find_available_port(start_port: int = 7861, max_attempts: int = 10) -> int:
    """检查配置端口是否可用。

    方案 D：配置端口被占用则判定已有实例并抛错（**不再自动换端口**，
    避免多实例并存导致端口错位/配置互相覆盖）。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", start_port)) != 0:
            return start_port
    raise RuntimeError(
        f"端口 {start_port} 已被占用——app 可能已在运行，请勿重复启动（或改用 --port 指定其他端口）"
    )


def list_characters() -> list[str]:
    """扫描 characters/ 下的角色名。"""
    return char_mgr.list_names()


# ---------- 事件处理 ----------


def send_message_handler(user_input, text_lang, voice_lang):
    result = ui_service.send_message(user_input, text_lang, voice_lang)
    if "error" in result:
        # 章节八十八 88.3：失败保留输入，用户点击「发送」即可一键重发（消息已回滚，不会重复）
        return (
            gr.update(visible=True, value=f"🔴 {result['error']}（输入已保留，点击发送可重试）"),
            gr.update(visible=False, value=None),
            gr.update(value=[]),
            _status_text(),
            gr.update(value=user_input),
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


def regenerate_handler(text_lang, voice_lang):
    """Q7：重新生成最后一条 AI 回复。"""
    result = ui_service.regenerate_last_reply(text_lang, voice_lang)
    if "error" in result:
        # 失败时旧回复已恢复，仍显示当前聊天（避免清空历史）
        session_id = ui_service.active_session
        current_msgs = ui_service.conv_mgr.get_messages(session_id) if session_id else []
        return (
            gr.update(visible=True, value=f"🔴 {result['error']}"),
            gr.update(visible=False, value=None),
            gr.update(value=ui_service.messages_to_chatbot(current_msgs)),
            _status_text(),
        )
    chatbot_value = ui_service.messages_to_chatbot(result["messages"])
    notice = result.get("tts_notice") or ""
    banner_value = f"🟡 {notice}" if notice else ""
    return (
        gr.update(visible=bool(notice), value=banner_value),
        gr.update(visible=True, value=result.get("audio_path") or None),
        gr.update(value=chatbot_value),
        _status_text(),
    )


def toggle_edit_handler():
    """显示编辑行。"""
    return gr.update(visible=True)


def confirm_edit_handler(edit_text):
    """Q10：编辑最后一条 AI 回复。返回 (隐藏编辑行, 刷新聊天显示)。"""
    if not edit_text or not edit_text.strip():
        gr.Info("🔴 编辑内容不能为空")
        return gr.update(), gr.update()
    session_id = ui_service.active_session
    if not session_id:
        gr.Info("🔴 尚无会话")
        return gr.update(), gr.update()
    messages = ui_service.conv_mgr.get_messages(session_id)
    if not messages or messages[-1].get("role") != "assistant":
        gr.Info("🔴 最后一条消息不是 AI 回复，无法编辑")
        return gr.update(), gr.update()
    msg_id = messages[-1].get("msg_id")
    updated = ui_service.conv_mgr.edit_message(session_id, msg_id, edit_text.strip())
    if not updated:
        gr.Info("🔴 编辑失败")
        return gr.update(), gr.update()
    gr.Info("🟢 已编辑最后一条 AI 回复")
    return (
        gr.update(visible=False),
        gr.update(
            value=ui_service.messages_to_chatbot(ui_service.conv_mgr.get_messages(session_id))
        ),
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
    """切换角色（章节九十二/九十三）：返回 (状态文字, 聊天背景路径, 头像状态)。

    角色有背景/头像图时经 gr.set_static_paths 注册该单文件（仅暴露该图，不暴露
    characters/ 整目录与 config.json），供前端 /file= 端点加载。
    """
    result = ui_service.select_character(name)
    if "error" in result:
        return gr.update(value=f"🔴 {result['error']}"), "", ""
    bg = result.get("background", "") or ""
    avatar = result.get("avatar", "") or ""
    for p in (bg, avatar):
        if p:
            try:
                gr.set_static_paths([p])
            except Exception as e:
                logger.warning(f"静态文件注册失败: {p}: {e}")
    # 头像状态：JSON 携带头像路径 + 角色名（供首字占位与名字显示）
    avatar_state = json.dumps({"path": avatar, "name": name}, ensure_ascii=False)
    return gr.update(value=f"🟢 角色: {name} | TTS 参数已应用"), bg, avatar_state


def save_chat_overlay_handler(enabled, opacity, mode, color):
    """章节九十二：保存聊天背景遮罩设置（写入 theme_config.json，加锁）。

    mode='auto' → color 存 null（自动随明暗主题）；'custom' → 存所选色值。
    """
    try:
        ov = theme.config.setdefault("chat_overlay", {})
        ov["enabled"] = bool(enabled)
        ov["opacity"] = max(0.0, min(0.9, float(opacity or 0)))
        ov["color"] = (color or "").strip() if mode == "custom" else None
        theme.save()
    except Exception as e:
        logger.warning(f"聊天背景遮罩保存失败: {e}")
        return gr.update(visible=True, value=f"🔴 遮罩设置保存失败: {e}")
    return gr.update(visible=True, value="🟢 遮罩设置已保存")


def save_chat_avatar_size_handler(size):
    """章节九十三：保存聊天窗口头像尺寸（写入 theme_config.json，加锁）。

    尺寸限定 128/256，非法值回落默认 128。
    """
    try:
        size = int(size) if size else 128
        if size not in (128, 256):
            size = 128
        theme.config.setdefault("chat_avatar", {})["size"] = size
        theme.save()
    except Exception as e:
        logger.warning(f"头像尺寸保存失败: {e}")
        return gr.update(visible=True, value=f"🔴 头像尺寸保存失败: {e}")
    return gr.update(visible=True, value=f"🟢 头像尺寸已设为 {size}px")


def preview_chat_bg_handler(file):
    """章节九十二：编辑面板上传背景后即时预览（gr.File 保留动图原始格式）。"""
    if not file:
        return gr.update(value=None)
    return gr.update(value=file)


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
            gr.update(value=f"🔴 {format_error(e, prefix='角色卡导入失败')}"),
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
        return (
            [gr.update(value="") for _ in range(11)]
            + [gr.update(value=None)]
            + [gr.update(value=None)]
            + [gr.update(value=None)]
            + [gr.update(value=None)]
        )

    sc = char.get("system_prompt_structured", {})
    lore = char.get("lorebook", {})
    portrait = char.get("_portrait", None) or None
    background = char.get("_background", None) or None

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
        gr.update(value=None),  # 训练音色：切换角色时重置，避免把上一角色的音色写入当前角色
        gr.update(value=background),  # 聊天背景预览（章节九十二）
        gr.update(value=None),  # 聊天背景上传文件（不预填）
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
    background_upload,
):
    """保存角色编辑表单。"""
    name = (char_name or "").strip()
    if not name:
        return gr.update(value="🔴 [CHR-003] 角色名称不能为空"), gr.update()

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

    # 章节九十二：聊天背景上传（gr.File 保留动图原始格式）
    # 字段写入规范化文件名 background.{ext}（与 update_background 落盘名一致），
    # 避免写成原始上传文件名导致字段指向不存在文件（仅靠固定文件名回退兜底）
    if background_upload:
        try:
            ext = Path(background_upload).suffix.lstrip(".").lower()
            if ext:
                character["background"] = f"background.{ext}"
        except Exception:
            pass

    char_mgr.save_character(character)

    if portrait_path:
        try:
            char_mgr.update_portrait(name, portrait_path)
        except Exception as e:
            logger.warning(f"头像更新失败: {e}")

    if background_upload:
        try:
            char_mgr.update_background(name, background_upload)
        except Exception as e:
            logger.warning(f"聊天背景更新失败: {e}")
            gr.Info(f"🟡 角色已保存，但背景更新失败: {e}")

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
    theme.save()
    return ""


# 章节八十八 88.4/88.3：操作指引内容
MAIN_HELP_TEXT = """
### 快速上手
1. **选角色**：左侧「角色」下拉选择一个角色（首次可能需先导入/创建）
2. **新建会话**：左侧「会话」→「新建会话」，AI 会打招呼
3. **发送消息**：底部输入框打字 → **Enter 发送**，**Shift+Enter 换行**
4. **语音回复**：自动合成语音并播放（若超时 20s 会先回文字）

### 常见问题
- **没有声音**：确认 GPT-SoVITS 已启动，顶栏状态显示 `🟢 TTS API 在线`
- **LLM 调用失败**：到「配置」面板点 **测试连通性** 查看具体错误；`API Key` 不要带多余空格
- **改音色**：「编辑角色」→「训练音色」选择已恢复的实验，或把参考音频放到角色目录
"""

SIDE_HELP_TEXT = """
### 侧栏各区块说明
- **角色**：选择/刷新/导入角色卡（TavernAI/RisuAI/Chub/CAI）
- **编辑角色**：修改角色设定/头像/音色，保存到角色
- **会话**：新建/切换/删除会话，可导出/导入
- **配置**：LLM/TTS 提供商设置 + 连通性测试
- **高级设置**：性能/超时/音效/代理/记忆
- **工具**：导出/导入会话、搜索、统计、回收站
- **训练管理**：训练结果打包/恢复/清理

> 点击 ☰ 可折叠侧栏；拖动右侧分隔条可调整宽度
"""


def main_help_handler():
    """主界面「使用帮助」显示简明操作流程（面板宽度与侧栏一致）。"""
    gr.Info("已打开使用帮助")
    return gr.update(visible=True), gr.update(value=MAIN_HELP_TEXT, visible=True)


def close_main_help_handler():
    """关闭主界面「使用帮助」面板。"""
    return gr.update(visible=False)


def side_help_handler():
    """侧栏「说明」显示各区块用途。"""
    gr.Info("已打开侧栏说明")
    return gr.update(visible=True), gr.update(value=SIDE_HELP_TEXT, visible=True)


def close_side_help_handler():
    """关闭侧栏「说明」面板。"""
    return gr.update(visible=False)


# ---------- 工具：导出/导入/搜索/统计（Phase 6） ----------


def export_session_handler():
    """导出当前会话 zip（章节八十七 87.3：无会话/失败给弹窗提示，成功显示下载链接）。"""
    if not ui_service.active_session:
        gr.Info("请先选择会话后再导出")
        return gr.update(visible=False, value=None)
    path = conv_mgr.export_session(ui_service.active_session)
    if not path:
        gr.Info("导出失败：会话数据不存在")
        return gr.update(visible=False, value=None)
    gr.Info("会话已导出，可点击下方链接下载")
    return gr.update(visible=True, value=path)


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
        return gr.update(value="🔴 请先选择要恢复的会话"), gr.update()
    sid = conv_mgr.restore_from_trash(trash_id)
    if not sid:
        return gr.update(value="🔴 恢复失败"), gr.update()
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
    # 章节九十四：训练根路径为空时自动继承主 gsv_root（保存后即时生效）
    effective = config_mgr.get_effective_gsv_root()
    training_ops.gsv_root = Path(effective).resolve() if effective else Path("")
    gr.Info("🟢 训练配置已保存，即时生效")
    return gr.update(value="🟢 训练配置已保存，即时生效")


def periodic_backup_handler():
    """定时自动备份（Q8），失败仅记日志不阻塞。"""
    try:
        backup_mgr.backup_now()
        logger.info("定时自动备份完成")
    except Exception as e:
        logger.warning(f"定时自动备份失败: {e}")


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


# 章节八十八 88.2：提供商预设模板
PROVIDER_PRESETS = {
    "deepseek": ("https://api.deepseek.com", "deepseek-v4-flash"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
}


def preset_provider_handler(preset):
    """选中提供商模板自动填 base_url 与 model（章节八十八 88.2）。"""
    if preset in PROVIDER_PRESETS:
        url, model = PROVIDER_PRESETS[preset]
        return gr.update(value=url), gr.update(value=model), gr.update(value=preset)
    return gr.update(), gr.update(), gr.update()


def test_connectivity_handler(tts_url, provider_name, base_url, api_key, model):
    """配置面板连通性测试（章节八十八 88.1）：只读测试，不写配置。

    API Key 采用表单值；若留空（R11 遮蔽）则回退使用已保存的 Key。
    """
    lines = []
    # 1) TTS API
    try:
        tts = TTSClient(tts_url or "http://127.0.0.1:9880")
        if tts.check_api():
            lines.append(f"✅ TTS API 在线：{tts.base}")
        else:
            lines.append(f"❌ TTS API 离线：无法连接 {tts.base}（请确认 GPT-SoVITS 已启动）")
    except Exception as e:
        lines.append(f"❌ TTS 测试异常：{str(e)[:100]}")

    # 2) LLM API（用表单当前值发一次极短调用）
    if not base_url or not model:
        lines.append("❌ LLM：请先填写 API Base URL 与模型名称")
    else:
        from modules.error_codes import classify
        from modules.llm_client import LLMClient

        try:
            # R11 遮蔽：表单 Key 为空时回退到已保存 Key
            saved_cfg = config_mgr.get_active_provider_config()
            effective_key = api_key or saved_cfg.get("api_key", "")
            client = LLMClient(
                {
                    "base_url": base_url,
                    "api_key": effective_key,
                    "model": model,
                    "max_tokens": 8,
                    "temperature": 0.0,
                    "text_language": "中文",
                }
            )
            client.chat(
                "你是连通性测试助手",
                [{"role": "user", "content": "只回复两个字：OK"}],
                max_tokens=8,
            )
            lines.append(f"✅ LLM 调用成功：{provider_name or model} · {model}")
        except Exception as e:
            code, msg = classify(e)
            lines.append(f"❌ LLM 调用失败：[{code}] {msg}")

    gr.Info("连通性测试完成")
    return gr.update(value="\n".join(lines), visible=True)


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


def refresh_gsv_root_handler():
    """章节九十四：前端「重新探测」——全量刷新 gsv_root。

    重探测根路径（成功自动写回 config.json）+ 重扫权重列表 + 重应用当前角色音色预设。
    返回 (配置面板 gsv_root 文本框更新, 状态栏文字, 刷新结果提示)。
    """
    result = ui_service.refresh_gsv_root()
    if result.get("ok"):
        gr.Info("🟢 " + result["message"])
        return (
            gr.update(value=result["path"]),
            _status_text(),
            gr.update(value="🟢 " + result["message"], visible=True),
        )
    gr.Info("🔴 " + result["message"])
    return (
        gr.update(),
        _status_text(),
        gr.update(value="🔴 " + result["message"], visible=True),
    )


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
            # 章节八十八 88.4：主界面操作指引按钮
            main_help_btn = gr.Button("❓ 使用帮助", scale=0)
            lang_dd = gr.Dropdown(
                choices=[("中文", "zh_CN"), ("日本語", "ja_JP"), ("English", "en_US")],
                value=config_mgr.get("app", {}).get("language", "zh_CN"),
                label="界面语言",
                scale=1,
            )
            theme_dd = gr.Dropdown(
                choices=[("浅色", "light"), ("深色", "dark"), ("跟随系统", "system")],
                value=theme.mode() if theme.mode() in ("light", "dark") else "system",
                label="主题",
                scale=1,
            )

        # 章节八十八 88.4/88.3：主界面操作指引（含新手引导），宽度与侧栏一致 + 可关闭
        main_help_panel = gr.Column(elem_id="main-help-panel", visible=False)
        with main_help_panel:
            with gr.Row():
                gr.Markdown("### ❓ 使用帮助")
                main_help_close_btn = gr.Button("✖ 关闭", scale=0)
            main_help_md = gr.Markdown(value="", elem_id="main-help-md")

        with gr.Row(elem_id="main-row"):
            # ---- 左栏（可折叠 + 独立滚动条） ----
            # 始终 visible=True，初始折叠由 INIT_JS 依据 sidebar-collapse-state 隐藏（Gradio
            # visible=False 的隐藏无法被前端 js 覆盖，会导致初始折叠后无法展开）
            with gr.Column(scale=1, min_width=200, visible=True, elem_id="sidebar-col"):
                # 章节八十八 88.4：侧栏操作指引按钮（可关闭）
                with gr.Row():
                    side_help_btn = gr.Button("❓ 侧栏说明", scale=1)
                side_help_panel = gr.Row(elem_id="side-help-panel", visible=False)
                with side_help_panel:
                    side_help_close_btn = gr.Button("✖ 关闭", scale=0)
                    side_help_md = gr.Markdown(value="", elem_id="side-help-md")
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
                    editor_bg_upload = gr.File(
                        label=i18n.t("上传聊天背景"),
                        file_types=[".png", ".jpg", ".jpeg", ".webp", ".gif"],
                        type="filepath",
                    )
                    editor_bg_preview = gr.Image(
                        label=i18n.t("聊天背景预览"), type="filepath", interactive=False
                    )
                    editor_voice_dd = gr.Dropdown(
                        choices=training_ops.list_restored(),
                        label=i18n.t("训练音色（已恢复）"),
                        info=i18n.t("选择后保存将写入音色预设"),
                        value=None,
                    )
                    editor_save_btn = gr.Button(i18n.t("保存角色"))
                    editor_status = gr.Markdown(visible=False)

                # 章节九十二：聊天背景设置折叠栏（启用开关 + 遮罩透明度/配色，即时生效并持久化）
                with gr.Accordion(i18n.t("聊天背景"), open=False):
                    _ov_cfg = theme.overlay()
                    chat_bg_enabled = gr.Checkbox(
                        value=bool(_ov_cfg.get("enabled", True)),
                        label=i18n.t("启用角色背景"),
                    )
                    chat_overlay_opacity = gr.Slider(
                        0,
                        0.9,
                        value=float(_ov_cfg.get("opacity", 0.4)),
                        step=0.05,
                        label=i18n.t("遮罩透明度"),
                    )
                    chat_overlay_mode = gr.Dropdown(
                        [("自动（随主题）", "auto"), ("自定义颜色", "custom")],
                        value="custom" if _ov_cfg.get("color") else "auto",
                        label=i18n.t("遮罩配色"),
                    )
                    chat_overlay_color = gr.ColorPicker(
                        value=_ov_cfg.get("color") or "#000000",
                        label=i18n.t("自定义遮罩色"),
                    )
                    chat_overlay_status = gr.Markdown(visible=False)
                    # 章节九十三：聊天窗口头像尺寸（128/256 两档，即时生效并持久化）
                    chat_avatar_size_dd = gr.Dropdown(
                        [("128px", 128), ("256px", 256)],
                        value=int(theme.avatar_size()),
                        label=i18n.t("头像尺寸"),
                    )
                    chat_avatar_status = gr.Markdown(visible=False)

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
                    # 章节九十四：配置面板「重新探测」按钮（自动探测 + 写回 config.json）
                    gsv_refresh_btn1 = gr.Button(
                        "🔍 重新探测 GPT-SoVITS 路径（自动检测并写回）", scale=1
                    )
                    gsv_refresh_status = gr.Markdown(visible=False)
                    cfg_tts_url = gr.Textbox(
                        label="TTS API 地址",
                        value=config_mgr.get("tts", {}).get(
                            "api_base_url", "http://127.0.0.1:9880"
                        ),
                    )
                    cfg_provider = gr.Textbox(label="提供商名称", value=_active_name)
                    # 章节八十八 88.2：提供商预设模板（选中自动填 URL/模型）
                    cfg_preset_dd = gr.Dropdown(
                        choices=[
                            ("DeepSeek", "deepseek"),
                            ("OpenAI", "openai"),
                            ("通义千问", "qwen"),
                            ("智谱", "zhipu"),
                        ],
                        value=None,
                        label="提供商模板（选填，自动填 URL 与模型）",
                        info="选中后自动填入 API Base URL 与模型名称，只需填 API Key",
                    )
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
                    # 章节八十八 88.1：连通性测试按钮
                    cfg_test_btn = gr.Button("测试连通性（LLM / TTS）", variant="secondary")
                    cfg_test_status = gr.Markdown(visible=False)
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

                with gr.Accordion(i18n.t("训练管理"), open=False):
                    tr_gsv_root = gr.Textbox(
                        label=i18n.t("GPT-SoVITS 路径"),
                        value=_gt_cfg.get("gsv_root", ""),
                        placeholder="C:/.../GPT-SoVITS-v2pro-20250604",
                    )
                    with gr.Row():
                        tr_exp_dd = gr.Dropdown(
                            label=i18n.t("训练实验"),
                            choices=[e["experiment"] for e in training_ops.scan_experiments()],
                            value=None,
                        )
                        tr_refresh_btn = gr.Button("刷新")
                    with gr.Row():
                        tr_preview_btn = gr.Button(i18n.t("预览打包"))
                        tr_pack_btn = gr.Button(i18n.t("打包并清理"))
                    tr_cleanup_cb = gr.Checkbox(
                        label=i18n.t("打包后清理中间素材"),
                        value=_gt_cfg.get("cleanup_after_pack", True),
                    )
                    tr_auto_detect = gr.Checkbox(
                        label=i18n.t("自动检测训练完成（提醒）"),
                        value=_gt_cfg.get("auto_detect", False),
                    )
                    tr_auto_full = gr.Checkbox(
                        label=i18n.t("全自动打包清理（auto_full）"),
                        value=_gt_cfg.get("auto_full", False),
                    )
                    tr_save_cfg_btn = gr.Button(i18n.t("保存训练配置"))
                    with gr.Row():
                        tr_archive_dd = gr.Dropdown(
                            label=i18n.t("归档 zip"),
                            choices=[a["path"] for a in training_ops.list_archives()],
                            value=None,
                        )
                        tr_writeback_cb = gr.Checkbox(label=i18n.t("写回 GPT-SoVITS"), value=False)
                    tr_restore_btn = gr.Button(i18n.t("恢复归档"))
                    tr_status = gr.Markdown(visible=False)

                # 章节九十四：侧栏状态栏区域「重新探测」按钮（与配置面板共用同一 handler）
                gsv_refresh_btn2 = gr.Button("🔍 重新探测 GPT-SoVITS 路径")
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
                # 章节九十二：聊天背景路径同步组件（隐藏，前端 JS 读取后经 /file= 加载）
                chat_bg_state = gr.Textbox(elem_id="chat-bg-state")
                # 章节九十三：头像状态同步组件（隐藏，JSON {path, name}，
                # 前端 JS 读取后经 /file= 加载）
                chat_avatar_state = gr.Textbox(elem_id="chat-avatar-state")
                # 章节九十三：头像尺寸同步组件（隐藏，仅前端 JS 经 elem_id 读取）
                gr.Number(value=int(theme.avatar_size()), elem_id="chat-avatar-size-state")
                # 章节九十二：聊天主区域（背景图 + 遮罩应用在此容器）
                with gr.Column(elem_id="chat-area"):
                    # 章节九十三：聊天窗口左上角角色头像（独立固定头部，透明不遮挡聊天背景）
                    gr.HTML(
                        '<div id="chat-header-wrap"><div id="chat-header">'
                        '<div class="avatar-container">'
                        '<img class="chat-avatar-img" src="" alt="" style="display:none" />'
                        '<span class="avatar-placeholder" style="display:none"></span>'
                        "</div>"
                        '<span class="chat-avatar-name"></span>'
                        "</div></div>",
                        elem_id="chat-header-wrap",
                    )
                    chatbot = gr.Chatbot(
                        label=i18n.t("聊天"),
                        type="tuples",
                        render_markdown=True,
                        height=CHAT_HEIGHT,
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
                with gr.Row():
                    send_btn = gr.Button(i18n.t("发送"), variant="primary")
                    regen_btn = gr.Button(i18n.t("重新生成最后回复"))
                    edit_btn = gr.Button(i18n.t("编辑最后一条 AI 回复"))

                # Q10：编辑最后一条 AI 回复（编辑内容输入框 + 确认按钮）
                with gr.Row(visible=False) as edit_row:
                    edit_input = gr.Textbox(label="编辑内容", lines=2)
                    edit_confirm_btn = gr.Button("确认编辑", variant="primary")
                    edit_cancel_btn = gr.Button("取消")

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

    # Q7：重新生成最后一条 AI 回复
    regen_outputs = [banner, audio_player, chatbot, status_text]
    regen_inputs = [text_lang_dd, voice_lang_dd]
    regen_btn.click(fn=regenerate_handler, inputs=regen_inputs, outputs=regen_outputs)

    # Q10：编辑最后一条 AI 回复
    edit_btn.click(fn=toggle_edit_handler, outputs=[edit_row])
    edit_confirm_btn.click(
        fn=confirm_edit_handler,
        inputs=[edit_input],
        outputs=[edit_row, chatbot],
    )
    edit_cancel_btn.click(fn=lambda: gr.update(visible=False), outputs=[edit_row])

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
        outputs=[status_text, chat_bg_state, chat_avatar_state],
    )
    # 章节九十二：背景路径更新后前端即时应用（不刷新页面）
    chat_bg_state.change(
        fn=None,
        inputs=[
            chat_bg_state,
            chat_bg_enabled,
            chat_overlay_opacity,
            chat_overlay_mode,
            chat_overlay_color,
        ],
        outputs=[],
        js=(
            "(p, enabled, opacity, mode, color) => "
            "{ window.applyChatBackground(p, enabled, opacity, mode, color); }"
        ),
    )
    # 章节九十三：头像状态（JSON {path,name}）更新后前端即时应用（不刷新页面）
    chat_avatar_state.change(
        fn=None,
        inputs=[chat_avatar_state],
        outputs=[],
        js=(
            "(state) => { try { const d = JSON.parse(state || '{}');"
            " window.applyChatAvatar(d.path || '', d.name || ''); } catch(e) {} }"
        ),
    )
    # 章节九十三：头像尺寸选择即时应用 + 持久化
    chat_avatar_size_dd.change(
        fn=None,
        inputs=[chat_avatar_size_dd],
        outputs=[],
        js="(size) => { window.applyChatAvatarSize(size); }",
    )
    chat_avatar_size_dd.change(
        fn=save_chat_avatar_size_handler,
        inputs=[chat_avatar_size_dd],
        outputs=[chat_avatar_status],
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
            editor_voice_dd,
            editor_bg_preview,
            editor_bg_upload,
        ],
    )
    # 章节九十二：编辑面板上传背景后即时预览
    editor_bg_upload.change(
        fn=preview_chat_bg_handler,
        inputs=[editor_bg_upload],
        outputs=[editor_bg_preview],
    )
    # 章节九十二：遮罩设置——前端即时应用 + 持久化
    _overlay_inputs = [chat_bg_enabled, chat_overlay_opacity, chat_overlay_mode, chat_overlay_color]
    for _ctrl in (chat_bg_enabled, chat_overlay_opacity, chat_overlay_mode, chat_overlay_color):
        _ctrl.change(
            fn=None,
            inputs=_overlay_inputs,
            outputs=[],
            js=(
                "(enabled, opacity, mode, color) => "
                "{ window.applyChatOverlay(enabled, opacity, mode, color); }"
            ),
        )
        _ctrl.change(
            fn=save_chat_overlay_handler,
            inputs=_overlay_inputs,
            outputs=[chat_overlay_status],
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
            editor_bg_upload,
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
    # 章节八十八 88.2：提供商模板自动填 URL/模型
    cfg_preset_dd.change(
        fn=preset_provider_handler,
        inputs=[cfg_preset_dd],
        outputs=[cfg_base_url, cfg_model, cfg_provider],
    )
    # 章节八十八 88.1：连通性测试
    cfg_test_btn.click(
        fn=test_connectivity_handler,
        inputs=[cfg_tts_url, cfg_provider, cfg_base_url, cfg_api_key, cfg_model],
        outputs=[cfg_test_status],
    )
    # 章节九十四：前端「重新探测」按钮（配置面板 + 状态栏区域，同一 handler）
    _gsv_refresh_outputs = [cfg_gsv_root, status_text, gsv_refresh_status]
    gsv_refresh_btn1.click(fn=refresh_gsv_root_handler, outputs=_gsv_refresh_outputs)
    gsv_refresh_btn2.click(fn=refresh_gsv_root_handler, outputs=_gsv_refresh_outputs)
    # 章节八十八 88.4：操作指引按钮（可关闭）
    main_help_btn.click(
        fn=main_help_handler,
        outputs=[main_help_panel, main_help_md],
    )
    main_help_close_btn.click(
        fn=close_main_help_handler,
        outputs=[main_help_panel],
    )
    side_help_btn.click(
        fn=side_help_handler,
        outputs=[side_help_panel, side_help_md],
    )
    side_help_close_btn.click(
        fn=close_side_help_handler,
        outputs=[side_help_panel],
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

    # Q8：定时自动备份（默认每 24h，由 backup.interval_hours 控制）
    if config_mgr.get("backup", {}).get("enabled", True):
        _bk_interval = float(config_mgr.get("backup", {}).get("interval_hours", 24) or 24)
        backup_timer = gr.Timer(value=_bk_interval * 3600)
        backup_timer.tick(fn=periodic_backup_handler)

    return wizard_block, main_block, status_text, trash_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM 角色扮演聊天 + GPT-SoVITS TTS")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--share", action="store_true", help="启用 Gradio 公网分享")
    parser.add_argument("--port", type=int, default=None, help="指定端口（默认自动寻找）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_entry("startup_report", "应用进程启动", "OK", detail=f"args={vars(args)}")
    if args.debug:
        setup_logger("app", debug=True)

    # 方案 D：单实例锁（杜绝重复启动多实例导致端口错位/配置覆盖）
    lock_path = PROJECT_ROOT / "app.lock"
    if not acquire_single_instance(lock_path):
        msg = "检测到 app 已在运行（app.lock 存在且进程存活），请勿重复启动"
        logger.error(msg)
        print(f"[ERROR] {msg}")
        sys.exit(1)
    try:
        _main_impl(args)
    finally:
        lock_path.unlink(missing_ok=True)


def _main_impl(args: argparse.Namespace) -> None:
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
        write_entry("startup_report", "数据迁移", "FAIL", code="SYS-004", detail=msg)
    else:
        write_entry("startup_report", "数据迁移", "OK", detail=msg or "无需迁移")

    # Q8：启动时执行一次自动备份（失败不阻断启动）
    if config_mgr.get("backup", {}).get("enabled", True):
        try:
            backup_mgr.backup_now()
            write_entry("startup_report", "自动备份", "OK")
        except Exception as e:
            logger.warning(f"启动自动备份失败: {e}")
            write_entry("startup_report", "自动备份", "WARN", detail=str(e)[:120])

    # 章节九十四：启动时自动探测 gsv_root（配置优先 → startup_report → 同级只读扫描），
    # 成功自动写回 config.json；失败保留旧值并告警（前端可点击「重新探测」或手动输入）
    gsv_path, gsv_source = config_mgr.resolve_gsv_root()
    if gsv_path:
        logger.info(f"GPT-SoVITS 根路径已就绪（来源：{gsv_source}）: {gsv_path}")
        write_entry(
            "startup_report",
            "探测 GPT-SoVITS 路径",
            "OK",
            detail=f"{gsv_path}（{gsv_source}）",
        )
    else:
        logger.warning(
            "[CFG-008] 未找到 GPT-SoVITS 目录（含 api_v2.py），TTS 相关功能不可用，"
            "可点击「重新探测」或在前端手动输入路径"
        )
        write_entry(
            "startup_report",
            "探测 GPT-SoVITS 路径",
            "WARN",
            code="CFG-008",
            detail="未找到含 api_v2.py 的 GPT-SoVITS 目录",
        )

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
    write_entry("startup_report", "Gradio 启动", "OK", detail=f"端口 {port}")
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
