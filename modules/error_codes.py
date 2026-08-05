"""全系统错误码注册表 + 异常归类（章节九十）。

- 错误码：模块前缀 + 编号，如 LLM-001 / TTS-003 / STP-004 / CFG-006
- ERROR_CODES：集中注册表 码 -> {module, desc, hint}
- AppError：携带 code/message/hint 的异常，str() 输出 "[CODE] 文案"
- classify(exc)：将任意异常归类为稳定错误码 + 友好文案（不改变原异常类型，保证既有测试兼容）
- format_error(exc, prefix)：输出 "[CODE] 友好文案"（可选前缀），供 UI/日志/报告统一使用
"""

import requests
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAIError,
    RateLimitError,
)

ERROR_CODES = {
    # 系统 / 启动
    "SYS-001": {"module": "系统", "desc": "应用启动失败", "hint": "查看 logs/error.log 最近错误"},
    "SYS-002": {"module": "系统", "desc": "已有实例在运行（单实例锁）", "hint": "请勿重复启动"},
    "SYS-003": {"module": "系统", "desc": "端口被占用", "hint": "改用 --port 或关闭占用程序"},
    "SYS-004": {"module": "系统", "desc": "数据迁移失败", "hint": "已尝试从 backup 恢复"},
    # 一键启动脚本
    "STP-001": {
        "module": "启动脚本",
        "desc": "未检测到 GPT-SoVITS 目录",
        "hint": "确认 GPT-SoVITS 与 llm_tts_update 位于同一父目录",
    },
    "STP-002": {
        "module": "启动脚本",
        "desc": "未找到 api_v2.py",
        "hint": "GPT-SoVITS 需 v2Pro 版本",
    },
    "STP-003": {
        "module": "启动脚本",
        "desc": "未找到 runtime Python",
        "hint": "GPT-SoVITS runtime 环境缺失",
    },
    "STP-004": {
        "module": "启动脚本",
        "desc": "TTS API 启动超时",
        "hint": "检查 api_v2.py 窗口/日志",
    },
    "STP-005": {"module": "启动脚本", "desc": "venv 环境缺失", "hint": "先运行 install_deps.bat"},
    "STP-006": {
        "module": "启动脚本",
        "desc": "端口检测失败",
        "hint": "请手动确认 9880/7861 端口状态",
    },
    # 配置
    "CFG-001": {"module": "配置", "desc": "config.json 加载失败", "hint": "已回退默认配置启动"},
    "CFG-002": {"module": "配置", "desc": "config.json 保存失败", "hint": "检查文件写权限"},
    "CFG-003": {"module": "配置", "desc": "缺少 LLM 提供商", "hint": "在配置面板填写提供商"},
    "CFG-004": {"module": "配置", "desc": "LLM API Key 无效", "hint": "检查 Key 是否过期或正确"},
    "CFG-005": {"module": "配置", "desc": "LLM 模型名不可用", "hint": "查询服务商可用模型"},
    "CFG-006": {"module": "配置", "desc": "未填写 LLM API Key", "hint": "在配置面板填写 API Key"},
    # LLM
    "LLM-001": {"module": "LLM", "desc": "LLM 连接失败", "hint": "检查 base_url 与网络/代理"},
    "LLM-002": {"module": "LLM", "desc": "LLM 请求超时", "hint": "网络慢或服务繁忙，稍后重试"},
    "LLM-003": {"module": "LLM", "desc": "LLM 速率限制（429）", "hint": "降低发送频率或稍后重试"},
    "LLM-004": {"module": "LLM", "desc": "没有可用的 LLM 提供商", "hint": "在配置面板添加提供商"},
    "LLM-005": {"module": "LLM", "desc": "LLM 重试耗尽", "hint": "多次尝试仍失败，检查服务状态"},
    "LLM-006": {"module": "LLM", "desc": "会话级提供商不存在", "hint": "切换会话或改为跟随全局"},
    # TTS
    "TTS-001": {"module": "TTS", "desc": "TTS API 离线", "hint": "启动 api_v2.py 服务"},
    "TTS-002": {"module": "TTS", "desc": "TTS 连接失败", "hint": "检查 api_base_url 与网络"},
    "TTS-003": {"module": "TTS", "desc": "TTS 合成失败", "hint": "确认参考音频/权重已配置"},
    "TTS-004": {"module": "TTS", "desc": "TTS 请求超时", "hint": "已先回复文字，可稍后重试语音"},
    "TTS-005": {"module": "TTS", "desc": "参考音频设置失败", "hint": "检查参考音频路径"},
    "TTS-006": {"module": "TTS", "desc": "模型权重设置失败", "hint": "检查权重文件"},
    # 角色
    "CHR-001": {"module": "角色", "desc": "角色不存在", "hint": "刷新角色列表或重新导入"},
    "CHR-002": {"module": "角色", "desc": "角色卡导入失败", "hint": "检查卡片格式"},
    "CHR-003": {"module": "角色", "desc": "角色名称不能为空", "hint": "填写角色名称"},
    # 会话
    "CONV-001": {"module": "会话", "desc": "会话不存在", "hint": "刷新会话列表"},
    "CONV-002": {"module": "会话", "desc": "会话导出失败", "hint": "会话数据可能缺失"},
    "CONV-003": {"module": "会话", "desc": "会话导入失败", "hint": "zip 内 messages.json 无效"},
    # 记忆
    "MEM-001": {"module": "记忆", "desc": "记忆存储失败", "hint": "检查记忆目录写入权限"},
    # 训练
    "TRN-001": {"module": "训练", "desc": "训练打包失败", "hint": "查看具体错误信息"},
    "TRN-002": {"module": "训练", "desc": "训练恢复失败", "hint": "检查归档 zip"},
    "TRN-003": {"module": "训练", "desc": "中间素材清理失败", "hint": "存在归档后才可清理"},
    # 界面
    "UI-001": {"module": "界面", "desc": "输入校验失败", "hint": "按提示修正输入"},
    "UI-002": {"module": "界面", "desc": "未选择角色", "hint": "先选择一个角色"},
    "UI-003": {"module": "界面", "desc": "未选择会话", "hint": "先新建或选择会话"},
    # 通用
    "GEN-001": {"module": "通用", "desc": "未知异常", "hint": "查看 logs/error.log"},
}


class AppError(Exception):
    """携带错误码的应用异常。

    Attributes:
        code: 稳定错误码（如 LLM-001）
        message: 人类可读文案
        hint: 建议处理方式
    """

    def __init__(self, code: str, message: str | None = None, hint: str | None = None):
        self.code = code
        info = ERROR_CODES.get(code, {})
        self.message = message or info.get("desc", code)
        self.hint = hint or info.get("hint", "")
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def classify(exc: BaseException) -> tuple[str, str]:
    """将任意异常归类为 (稳定错误码, 友好文案)。

    - 不改动原异常：调用方仍保留原始异常类型抛出（既有测试兼容）
    - 优先按类型匹配，其次按文案关键字兜底
    """
    if isinstance(exc, AppError):
        return exc.code, exc.message

    # ---- openai 错误 ----
    if isinstance(exc, RateLimitError):
        return "LLM-003", "LLM 速率限制（429）"
    if isinstance(exc, AuthenticationError):
        return "CFG-004", "LLM API Key 无效（401）"
    if isinstance(exc, NotFoundError) or "model_not_found" in str(exc).lower():
        return "CFG-005", "LLM 模型名不可用"
    if isinstance(exc, APITimeoutError):
        return "LLM-002", "LLM 请求超时"
    if isinstance(exc, APIConnectionError):
        return "LLM-001", "LLM 连接失败"
    if isinstance(exc, OpenAIError):
        msg = str(exc).lower()
        if "credentials" in msg or "api_key" in msg or "缺少" in msg:
            return "CFG-006", "未填写 LLM API Key"
        return "LLM-001", "LLM 调用失败"

    # ---- requests 错误 ----
    if isinstance(exc, requests.ConnectionError):
        return "TTS-002", "TTS 连接失败"
    if isinstance(exc, requests.Timeout):
        return "TTS-004", "TTS 请求超时"

    # ---- 业务/其他 ----
    msg = str(exc)
    if isinstance(exc, ValueError):
        if "没有可用的 LLM 提供商" in msg:
            return "LLM-004", "没有可用的 LLM 提供商"
        if "模型" in msg:
            return "CFG-005", msg[:120]
        return "UI-001", msg[:120]
    if isinstance(exc, RuntimeError) and "TTS 合成失败" in msg:
        return "TTS-003", "TTS 合成失败"
    if isinstance(exc, TimeoutError):
        return "SYS-001", "操作超时"
    return "GEN-001", (msg or exc.__class__.__name__)[:140]


def format_error(exc: BaseException, prefix: str = "") -> str:
    """格式化错误为 "[CODE] 文案"（可带前缀），供 UI 横幅/日志/报告使用。

    Args:
        exc: 异常对象
        prefix: 可选前缀（如 "LLM 调用失败"）
    """
    code, message = classify(exc)
    text = f"[{code}] {message}"
    return f"{prefix} {text}".strip() if prefix else text
