"""全系统自动化端到端测试（e2e_live）——不依赖人工/外部服务。

覆盖：子系统直检（R1/R9/R10/章节84）→ 应用启动 → 主界面渲染 → 健康检查 →
会话 CRUD + 回收站 → 角色切换 → 配置保存 → 高级设置 → 记忆清空 → 搜索/统计 →
发送消息错误路径（R4 回滚）→ API Key 遮蔽（R11）→ 优雅关闭。

- 每个操作均设置超时（run_with_timeout / requests / queue_timeout），全程自动
- 运行于临时副本目录，不污染真实数据
- 用法：venv\\Scripts\\python.exe tests/e2e_live.py
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
VENV_PY = PROJECT / "venv" / "Scripts" / "python.exe"
PORT_BASE = 7890

sys.path.insert(0, str(PROJECT))

COPY_DIRS = ["modules", "locales", "migrations", "characters", "tests"]
COPY_FILES = [
    "app.py",
    "requirements.txt",
    "pyproject.toml",
    "pytest.ini",
    "config.example.json",
    "go-llm-tts.bat",
    "install_deps.bat",
    "train_pack.bat",
]

RESULTS = []


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    RESULTS.append((name, ok))
    print(f"  [{tag}] {name}" + (f" | {detail}" if detail else ""), flush=True)
    return ok


def run_with_timeout(fn, timeout, *args, **kwargs):
    """在线程中执行并强制超时，超时抛 TimeoutError。"""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args, **kwargs).result(timeout=timeout)


# ---------- A. 子系统直接检查（无需服务器） ----------


def subsystem_checks():
    log("A. 子系统直接检查（模块级）")

    # R1: sanitize_input 保留原文
    from modules.ui_service import sanitize_input

    t, w = sanitize_input("<script>alert(1)</script>")
    check("R1 sanitize 保留原始文本", t == "<script>alert(1)</script>", t)

    # R10: apply_proxy_env 注入环境变量
    from modules.config_manager import apply_proxy_env

    apply_proxy_env(
        {
            "enabled": True,
            "http": "http://p:8080",
            "https": "http://p:8443",
            "no_proxy": ["localhost", "127.0.0.1"],
        }
    )
    ok = "HTTP_PROXY" in __import__("os").environ and "NO_PROXY" in __import__("os").environ
    check("R10 代理环境变量注入", ok, __import__("os").environ.get("HTTP_PROXY", ""))
    apply_proxy_env({"enabled": False})
    check("R10 代理禁用清除变量", "HTTP_PROXY" not in __import__("os").environ)

    # 章节84: MemoryStore 规则提取 + 召回
    from modules.memory_store import MemoryStore, extract_rule_memories

    mem = extract_rule_memories("我喜欢弹钢琴，我住在北京。")
    ok = any("我喜欢弹钢琴" in m for m in mem) and any("我住在北京" in m for m in mem)
    check("章节84 规则提取", ok, str(mem))
    ms = MemoryStore(Path(tempfile.mkdtemp()) / "mem")
    ms.add_entry("用户喜欢弹钢琴", scope="character", key="暴行")
    recalled = ms.recall("你会弹钢琴吗", scope="character", key="暴行", limit=3)
    check("章节84 关键词召回", "用户喜欢弹钢琴" in recalled, str(recalled))

    # R9: training_ops 轻量扫描（空目录不报错）
    from modules.training_ops import TrainingOps

    to = TrainingOps(gsv_root=str(Path(tempfile.mkdtemp()) / "gsv"))
    ok = to.detect_completed() == []
    check("R9 轻量自动检测（空）", ok)

    # R3: 会话回收站
    from modules.conversation_manager import ConvManager

    base = Path(tempfile.mkdtemp())
    cm = ConvManager(base / "convs")
    sid = cm.create_session("回收测试")
    cm.add_message(sid, "user", "hi")
    cm.delete_session(sid)
    ok = len(cm.list_trash()) == 1 and not cm.session_exists(sid)
    check("R3 删除入回收站", ok)
    restored = cm.restore_from_trash(cm.list_trash()[0]["id"])
    check("R3 回收站恢复", restored == sid and cm.session_exists(sid))

    # R5: 收藏 msg_id 跨摘要压缩
    cm2 = ConvManager(base / "convs2", max_history_rounds=1, summarize_trigger_rounds=2)
    s2 = cm2.create_session()
    cm2.add_message(s2, "user", "q0")
    cm2.add_message(s2, "assistant", "a0")
    cm2.add_message(s2, "user", "q1")
    cm2.add_message(s2, "assistant", "a1")
    cm2.add_favorite(s2, 3)
    cm2.maybe_summarize(s2, summarize_fn=lambda h: "摘要")
    ok = cm2.is_favorite(s2, 1) and len(cm2.list_favorites(s2)) == 1
    check("R5 收藏 msg_id 保留", ok)

    # R4: remove_last_message 回滚
    removed = cm2.remove_last_message(s2, role="assistant")
    check("R4 消息回滚", removed is not None and removed["content"] == "a1")


# ---------- B. 服务器端到端 ----------


def copy_project(work: Path):
    (work / "logs").mkdir()
    for d in COPY_DIRS:
        shutil.copytree(PROJECT / d, work / d)
    for f in COPY_FILES:
        shutil.copy2(PROJECT / f, work / f)


def write_config(work: Path, port: int):
    cfg = {
        "data_version": "1.0",
        "llm": {"active_provider": "test", "fallback_enabled": True},
        "llm_providers": {
            "test": {
                "base_url": "http://127.0.0.1:1",
                "api_key": "",
                "model": "m",
                "max_tokens": 128,
                "temperature": 0.8,
                "text_language": "中文",
                "priority": 1,
            }
        },
        "tts": {
            "api_base_url": "http://127.0.0.1:9880",
            "version": "v2Pro",
            "voice_language": "中文",
            "top_k": 15,
            "top_p": 1.0,
            "temperature": 1.0,
            "speed": 1.0,
        },
        "app": {
            "port": port,
            "max_history_rounds": 4,
            "summarize_trigger_rounds": 20,
            "max_input_length": 2000,
            "sensitive_words": [],
            "language": "zh_CN",
            "sidebar_collapsed": False,
            "sidebar_width": 320,
        },
        "memory": {
            "enabled": True,
            "scope": "character",
            "recall_limit": 5,
            "extract_with_llm": False,
        },
        "gsv_root": "",
        "external_characters": [],
        "trash": {"auto_clean_days": 30, "max_size_mb": 500},
        "session_timeout": {"idle_minutes": 30, "warning_minutes": 25},
        "performance": {"device": "auto", "max_llm_concurrency": 2, "max_tts_concurrency": 1},
        "prompt_protection": {"mode": "A"},
        "notification_sound": {"enabled": True, "sound_file": "", "volume": 0.7},
        "audio_normalization": {"enabled": True, "target_dB": -3.0, "global_volume": 1.0},
        "proxy": {
            "enabled": False,
            "http": "",
            "https": "",
            "no_proxy": ["localhost", "127.0.0.1"],
        },
        "gsv_training": {
            "gsv_root": "",
            "archive_dir": "",
            "restore_dir": "",
            "cleanup_after_pack": True,
            "auto_detect": False,
            "auto_full": False,
        },
    }
    (work / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def wait_http(url: str, timeout: float = 60.0) -> bool:
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(url, timeout=5)
            return True
        except Exception:
            time.sleep(1)
    return False


def server_checks(work: Path, port: int, proc: subprocess.Popen):
    import requests
    from gradio_client import Client

    base = f"http://127.0.0.1:{port}"
    log("B. 服务器端到端")

    if not wait_http(base, timeout=60):
        check("B1 应用启动 HTTP 200", False, "启动超时")
        return
    try:
        r = requests.get(base, timeout=10)
        check("B1 应用启动 HTTP 200", r.status_code == 200, f"status={r.status_code}")
    except Exception as e:
        check("B1 应用启动 HTTP 200", False, str(e))
        return

    # R11: 配置面板 API Key 遮蔽（页面含占位提示，不含明文）
    try:
        html = requests.get(base, timeout=10).text
        check("R11 API Key 前端遮蔽（占位符）", "已保存密钥，留空保持不变" in html)
    except Exception as e:
        check("R11 API Key 前端遮蔽", False, str(e))

    # 章节八十五：侧栏拖动调整宽度 + 折叠（页面元素与初始化 JS）
    try:
        html = requests.get(base, timeout=10).text
        check("B16 侧栏分隔条元素", "sidebar-resizer" in html)
        check("B16 侧栏宽度隐藏组件", "sidebar-width-state" in html)
        check("B16 侧栏初始化 JS", "llm_tts_sidebar_width" in html)
    except Exception as e:
        check("B16 侧栏元素与 JS", False, str(e))

    # 发现 API 端点（Gradio 4 的 info 在 /info）
    try:
        info = requests.get(f"{base}/info", timeout=10).json()
        named = info.get("named_endpoints", {}) or {}
        log(f"  gradio 命名端点数: {len(named)}")
    except Exception as e:
        check("B2 gradio API info 可访问", False, str(e))
        return
    check("B2 gradio API info 可访问", True)

    has = lambda n: ("/" + n) in named  # noqa: E731

    def call(name, *args, timeout=30):
        # predict 无 timeout 参数（**kwargs 会转发给 handler），HTTP 超时由 httpx_kwargs 控制，
        # 硬超时由 run_with_timeout 兜底（超时后跳过，不阻塞后续）。
        return run_with_timeout(
            lambda: client.predict(api_name="/" + name, *args),
            timeout,
        )

    try:
        client = Client(base, verbose=False, httpx_kwargs={"timeout": 30})
    except Exception as e:
        check("B3 gradio_client 连接", False, str(e))
        return
    check("B3 gradio_client 连接", True)

    def flatten_updates(r):
        """将 predict 返回扁平化为 dict 列表（gradio 会省略无变化的 update）。

        兼容 list/tuple/dict/None 四种返回形态。
        """
        out = []
        if r is None:
            return out
        if isinstance(r, dict):
            out.append(r)
            return out
        for item in r if isinstance(r, (list, tuple)) else [r]:
            if isinstance(item, dict):
                out.append(item)
        return out

    # 先选角色（B7）再建会话，保证问候语进入会话
    if has("select_character_handler"):
        try:
            r = call("select_character_handler", "暴行", timeout=30)
            flat = flatten_updates(r)
            status = flat[0].get("value", "") if flat else str(r)
            check("B4 角色切换（暴行）", "角色: 暴行" in str(status), str(status)[:40])
        except Exception as e:
            check("B4 角色切换（暴行）", False, str(e))
    else:
        check("B4 角色切换（暴行）", False, "端点缺失")

    # 会话流程
    if has("new_session_handler"):
        try:
            r = call("new_session_handler", timeout=30)
            flat = flatten_updates(r)
            has_choices = any("choices" in u for u in flat)
            check("B5 新建会话（问候语）", has_choices and len(flat) >= 2, f"updates={len(flat)}")
        except Exception as e:
            check("B5 新建会话（问候语）", False, str(e))
    else:
        check("B5 新建会话（问候语）", False, "端点缺失")

    if has("favorite_last_message_handler"):
        try:
            r = call("favorite_last_message_handler", timeout=30)
            val = r[0]["value"] if isinstance(r, list) and r else str(r)
            check("B6 收藏最后一条回复", "已收藏" in str(val), str(val)[:40])
        except Exception as e:
            check("B6 收藏最后一条回复", False, str(e))

    if has("stats_handler"):
        try:
            r = call("stats_handler", timeout=30)
            txt = r[0]["value"] if isinstance(r, list) and r else str(r)
            check("B7 统计看板", "消息数" in str(txt), str(txt)[:40])
        except Exception as e:
            check("B7 统计看板", False, str(e))

    # 发送消息错误路径（R4 回滚：无真实 LLM → 返回错误横幅）
    if has("send_message_handler"):
        try:
            r = call("send_message_handler", "测试消息", "中文", "中文", timeout=60)
            flat = flatten_updates(r)
            check("B8 发送消息（错误路径有提示）", len(flat) >= 4, f"updates={len(flat)}")
            banner = ""
            for u in flat:
                if "value" in u:
                    banner = u["value"]
                    break
            check(
                "B8 错误横幅可见",
                "🔴" in str(banner) or "LLM 调用失败" in str(banner),
                str(banner)[:60],
            )
        except Exception as e:
            check("B8 发送消息（错误路径）", False, str(e))
    else:
        check("B8 发送消息（错误路径）", False, "端点缺失")

    # R4 强验证：发送失败后用户消息被回滚（会话应仅剩问候语，用户消息数=0）
    if has("stats_handler"):
        try:
            r = call("stats_handler", timeout=30)
            txt = r[0]["value"] if isinstance(r, list) and r else str(r)
            check("B8-R4 失败后消息回滚", "用户: 0" in str(txt), str(txt)[:60])
        except Exception as e:
            check("B8-R4 失败后消息回滚", False, str(e))

    # 会话删除（入回收站）
    if has("delete_session_handler"):
        try:
            r = call("delete_session_handler", timeout=30)
            val = r[4]["value"] if isinstance(r, list) and len(r) > 4 else str(r)
            check("B9 删除会话（入回收站）", "回收站" in str(val), str(val)[:50])
        except Exception as e:
            check("B9 删除会话（入回收站）", False, str(e))

    if has("refresh_trash_handler"):
        try:
            r = call("refresh_trash_handler", timeout=30)
            flat = flatten_updates(r)
            has_choices = any("choices" in u for u in flat)
            check("B10 回收站列表刷新", has_choices, f"updates={len(flat)}")
        except Exception as e:
            check("B10 回收站列表刷新", False, str(e))

    # B10a 盲区：未选择会话时点「恢复会话」不应 500（修复：错误分支补全返回值）
    if has("restore_trash_handler"):
        try:
            r = call("restore_trash_handler", "", timeout=30)
            val = "".join(str(u) for u in flatten_updates(r))
            check("B10a 回收站恢复-空选择不报错", "请先选择" in val, val[:40])
        except Exception as e:
            check("B10a 回收站恢复-空选择不报错", False, str(e))
    else:
        check("B10a 回收站恢复-空选择不报错", False, "端点缺失")

    if has("empty_trash_handler"):
        try:
            r = call("empty_trash_handler", timeout=30)
            val = "".join(str(u) for u in flatten_updates(r))
            check("B11 清空回收站", "清空" in val, val[:50])
        except Exception as e:
            check("B11 清空回收站", False, str(e))

    # 配置保存（R11：空 key 保持；R12 提供商）
    if has("save_settings_handler"):
        try:
            r = call(
                "save_settings_handler",
                "",
                "http://127.0.0.1:9880",
                "test",
                "http://127.0.0.1:1",
                "",
                "m",
                128,
                0.8,
                "中文",
                timeout=30,
            )
            val = "".join(str(u) for u in flatten_updates(r))
            check("B12 配置保存（API Key 留空）", "已保存" in val, val[:40])
        except Exception as e:
            check("B12 配置保存（API Key 留空）", False, str(e))

    # 高级设置（R10：性能/会话超时/通知音效/代理/记忆）
    if has("save_advanced_settings_handler"):
        try:
            r = call(
                "save_advanced_settings_handler",
                "auto",
                2,
                1,
                30,
                25,
                True,
                "",
                0.7,
                True,
                "http://127.0.0.1:8080",
                "http://127.0.0.1:8443",
                "localhost,127.0.0.1",
                True,
                "character",
                5,
                False,
                timeout=30,
            )
            val = "".join(str(u) for u in flatten_updates(r))
            check("B13 高级设置保存（含代理开启）", "已保存" in val, val[:40])
        except Exception as e:
            check("B13 高级设置保存（含代理开启）", False, str(e))

    # 记忆清空（章节84）
    if has("clear_memory_handler"):
        try:
            r = call("clear_memory_handler", timeout=30)
            val = "".join(str(u) for u in flatten_updates(r))
            check("B14 清空当前记忆", "已清空记忆" in val, val[:40])
        except Exception as e:
            check("B14 清空当前记忆", False, str(e))

    # 训练面板（空环境不报错）
    if has("refresh_training_choices"):
        try:
            r = call("refresh_training_choices", timeout=30)
            flat = flatten_updates(r)
            has_choices = all("choices" in u for u in flat) and len(flat) >= 1
            check("B15 训练面板刷新（空环境）", has_choices, f"updates={len(flat)}")
        except Exception as e:
            check("B15 训练面板刷新（空环境）", False, str(e))

    # B15a 盲区/覆盖：训练面板错误路径（未选实验预览/打包不报 500）
    if has("preview_training_handler"):
        try:
            r = call("preview_training_handler", None, timeout=30)
            val = "".join(str(u) for u in flatten_updates(r))
            check("B15a 训练预览-未选实验", "请先选择" in val, val[:40])
        except Exception as e:
            check("B15a 训练预览-未选实验", False, str(e))
    else:
        check("B15a 训练预览-未选实验", False, "端点缺失")

    if has("pack_training_handler"):
        try:
            r = call("pack_training_handler", None, timeout=30)
            val = "".join(str(u) for u in flatten_updates(r))
            check("B15b 训练打包-未选实验", "请先选择" in val, val[:40])
        except Exception as e:
            check("B15b 训练打包-未选实验", False, str(e))
    else:
        check("B15b 训练打包-未选实验", False, "端点缺失")

    if has("save_training_settings_handler"):
        try:
            r = call("save_training_settings_handler", "", False, False, False, timeout=30)
            val = "".join(str(u) for u in flatten_updates(r))
            check("B15c 训练配置保存", "已保存" in val, val[:40])
        except Exception as e:
            check("B15c 训练配置保存", False, str(e))
    else:
        check("B15c 训练配置保存", False, "端点缺失")

    # 章节八十五：折叠修复验证
    # 折叠改用隐藏 gr.Number(sidebar-collapse-state) + js 切换 DOM（避免 gr.State 触发 Gradio
    # "Too many arguments" 导致事件失效），验证隐藏组件与修复 JS 已注入前端 + 端点存在
    if has("persist_sidebar_state"):
        try:
            html = requests.get(base, timeout=10).text
            has_fix_js = "sidebar-collapse-state" in html and "return next" in html
            has_toggle = "sidebar-col" in html
            check("B17 侧栏折叠修复（隐藏组件 + JS 切换）", has_fix_js and has_toggle)
        except Exception as e:
            check("B17 侧栏折叠修复（隐藏组件 + JS 切换）", False, str(e))
    else:
        check("B17 侧栏折叠修复（隐藏组件 + JS 切换）", False, "端点缺失")

    if has("save_sidebar_width"):
        try:
            r = call("save_sidebar_width", 420, timeout=30)
            check("B18 侧栏宽度保存", True, f"handler_ok={r is not None}")
        except Exception as e:
            check("B18 侧栏宽度保存", False, str(e))
    else:
        check("B18 侧栏宽度保存", False, "端点缺失")

    # 章节八十六：移动端响应式 CSS 注入
    try:
        html = requests.get(base, timeout=10).text
        check("B19 移动端媒体查询", "@media (max-width: 900px)" in html and "main-row" in html)
    except Exception as e:
        check("B19 移动端媒体查询", False, str(e))

    # 章节六十九~七十一：角色卡导入（JSON 卡 → 导入 → 角色列表出现）
    if has("import_card_handler") and has("refresh_characters_handler"):
        import json as _json

        from gradio_client import utils as _gc_utils

        card_path = work / "import_card.json"
        card_path.write_text(
            _json.dumps(
                {
                    "name": "e2e测试卡",
                    "description": "自动导入验证",
                    "personality": "测试",
                    "scenario": "测试场景",
                    "first_mes": "你好，测试导入成功。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        try:
            call("import_card_handler", _gc_utils.handle_file(str(card_path)), timeout=30)
            r = call("refresh_characters_handler", timeout=30)
            choices = []
            for u in flatten_updates(r):
                choices.extend(u.get("choices") or [])
            names = [c[1] if isinstance(c, (list, tuple)) else str(c) for c in choices]
            check("B20 角色卡导入", any("e2e测试卡" in n for n in names), f"names={names[:3]}")
        except Exception as e:
            check("B20 角色卡导入", False, str(e))
    else:
        check("B20 角色卡导入", False, "端点缺失")

    # 章节九十：报告系统验证（startup_report + run_report 文本/JSONL 双份，含错误码）
    try:
        report_dir = work / "logs"
        startup_txt = sorted(report_dir.glob("startup_report_*.txt"))
        run_txt = sorted(report_dir.glob("run_report_*.txt"))
        run_json = sorted(report_dir.glob("run_report_*.jsonl"))
        check(
            "B21 报告文件生成（文本+JSONL）",
            bool(startup_txt and run_txt and run_json),
            f"startup={len(startup_txt)} run_txt={len(run_txt)} run_jsonl={len(run_json)}",
        )
        content = ""
        if run_txt:
            content = run_txt[-1].read_text(encoding="utf-8")
        has_code = bool(re.search(r"\[(?:LLM|CFG|TTS|UI|STP|SYS|CHR|CONV|MEM|TRN)-\d+\]", content))
        check(
            "B21 报告含步骤与错误码",
            ("LLM 调用" in content or "输入校验" in content) and has_code,
            content.splitlines()[0][:80] if content else "（无内容）",
        )
    except Exception as e:
        check("B21 报告系统", False, str(e))

    # B22 盲区：角色名称为空时点「保存角色」不应 500（修复：错误分支补全返回值）
    if has("save_character_handler"):
        try:
            r = call(
                "save_character_handler",
                "",
                "",  # 空角色名 → CHR-003
                "你好",
                "温柔",
                "柔和",
                "",
                "学生",
                "",
                "",
                "",
                "",
                "",
                None,
                None,
                None,  # background_upload（章节九十二）
                timeout=30,
            )
            flat = flatten_updates(r)
            val = "".join(str(u) for u in flat)
            check("B22 角色保存-空名称不报错", "CHR-003" in val, val[:40])
        except Exception as e:
            check("B22 角色保存-空名称不报错", False, str(e))
    else:
        check("B22 角色保存-空名称不报错", False, "端点缺失")

    # B23 章节九十二：角色聊天背景——背景路径返回/遮罩保存/背景文件经 /file= 加载
    if has("select_character_handler") and has("save_chat_overlay_handler"):
        try:
            # 写入 1x1 透明 PNG 作为角色背景，验证静态注册与 /file= 加载
            import base64

            bg_dir = work / "characters" / "暴行"
            bg_dir.mkdir(parents=True, exist_ok=True)
            one_px = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            )
            (bg_dir / "background.png").write_bytes(one_px)
            r = call("select_character_handler", "暴行", timeout=30)
            flat = flatten_updates(r)
            bg_path = ""
            # 输出[1]（chat_bg_state Textbox）可能以原始 string 返回（非 update dict）
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                item = r[1]
                if isinstance(item, dict):
                    bg_path = str(item.get("value", "") or "")
                else:
                    bg_path = str(item or "")
            check("B23a 角色切换返回背景路径", bg_path.endswith("background.png"), f"bg={bg_path}")
            # 遮罩设置持久化（auto 模式 → color 应存 null）
            r2 = call("save_chat_overlay_handler", True, 0.5, "auto", "#000000", timeout=30)
            flat2 = flatten_updates(r2)
            val2 = "".join(str(u) for u in flat2)
            check("B23b 遮罩设置保存", "已保存" in val2, val2[:40])
            # 背景静态注册后 /file= 可访问
            if bg_path:
                import urllib.request
                from urllib import parse as urlparse

                url = base + "/file=" + urlparse.quote(bg_path.replace("\\", "/"))
                with urllib.request.urlopen(url, timeout=15) as resp:
                    ok_serve = resp.status == 200
                check("B23c 背景图经 /file= 加载", ok_serve, f"status={resp.status}")
            else:
                check("B23c 背景图经 /file= 加载", False, "未获取到背景路径")
        except Exception as e:
            check("B23 角色聊天背景", False, str(e))
    else:
        check("B23 角色聊天背景", False, "端点缺失")


def run_server_checks():
    work = Path(tempfile.mkdtemp(prefix="llm_tts_e2e_"))
    port = PORT_BASE
    for p in range(PORT_BASE, PORT_BASE + 10):
        with __import__("socket").socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                port = p
                break

    log(f"临时工作目录: {work}（端口 {port}）")
    try:
        copy_project(work)
        write_config(work, port)
        proc = subprocess.Popen(
            [str(VENV_PY), "app.py", "--port", str(port)],
            cwd=str(work),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            server_checks(work, port, proc)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        check(
            "C1 服务器优雅关闭",
            proc.returncode in (0, 1, -15) or proc.returncode is None,
            f"rc={proc.returncode}",
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        log(f"已清理临时目录: {work}")


def main():
    t0 = time.time()
    subsystem_checks()
    run_server_checks()
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = len(RESULTS) - passed
    log(
        f"===== 结果: {passed}/{len(RESULTS)} 通过, {failed} 失败 "
        f"({time.time() - t0:.1f}s) ====="
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
