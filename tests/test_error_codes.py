"""错误码系统单元测试（章节九十）。"""

import sys
from pathlib import Path

import httpx
import openai
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.error_codes import (  # noqa: E402
    ERROR_CODES,
    AppError,
    classify,
    format_error,
)


def _http_req() -> httpx.Request:
    return httpx.Request("GET", "http://x")


def _http_resp() -> httpx.Response:
    return httpx.Response(200, request=_http_req())


def test_registry_has_expected_codes():
    for code in (
        "SYS-001",
        "STP-001",
        "CFG-006",
        "LLM-004",
        "TTS-003",
        "UI-002",
        "MEM-001",
        "GEN-001",
    ):
        assert code in ERROR_CODES
        assert "desc" in ERROR_CODES[code]
        assert "hint" in ERROR_CODES[code]


def test_app_error_str_includes_code():
    e = AppError("LLM-004")
    assert e.code == "LLM-004"
    assert "[LLM-004]" in str(e)
    assert "没有可用的 LLM 提供商" in str(e)


def test_classify_llm_connection():
    code, _ = classify(openai.APIConnectionError(message="conn", request=None))
    assert code == "LLM-001"


def test_classify_llm_timeout():
    code, _ = classify(openai.APITimeoutError(request=_http_req()))
    assert code == "LLM-002"


def test_classify_rate_limit():
    code, _ = classify(openai.RateLimitError("429", response=_http_resp(), body={}))
    assert code == "LLM-003"


def test_classify_invalid_key():
    code, _ = classify(openai.AuthenticationError("401", response=_http_resp(), body={}))
    assert code == "CFG-004"


def test_classify_model_not_found():
    # Q4：404 消息含 model 相关关键词 → 模型名不可用
    code, _ = classify(openai.NotFoundError("model not found", response=_http_resp(), body={}))
    assert code == "CFG-005"


def test_classify_not_found_without_model_hint():
    # Q4：404 消息不含 model（如 base_url 配错）→ 接口/服务不可用（CFG-007）
    code, _ = classify(openai.NotFoundError("404 Not Found", response=_http_resp(), body={}))
    assert code == "CFG-007"


def test_classify_missing_credentials():
    code, _ = classify(openai.OpenAIError("Missing credentials. Please pass an api_key"))
    assert code == "CFG-006"


def test_classify_no_providers_valueerror():
    code, _ = classify(ValueError("[LLM-004] 没有可用的 LLM 提供商"))
    assert code == "LLM-004"


def test_classify_tts_connection():
    code, _ = classify(requests.ConnectionError("boom"))
    assert code == "TTS-002"


def test_classify_tts_synthesis():
    code, _ = classify(RuntimeError("[TTS-003] TTS 合成失败已达最大重试次数: x"))
    assert code == "TTS-003"


def test_classify_unknown_falls_back():
    code, _ = classify(RuntimeError("some weird thing"))
    assert code == "GEN-001"


def test_classify_app_error_passthrough():
    code, msg = classify(AppError("UI-002"))
    assert code == "UI-002"
    assert msg == ERROR_CODES["UI-002"]["desc"]


def test_format_error_with_prefix():
    text = format_error(ValueError("没有可用的 LLM 提供商"), prefix="LLM 调用失败")
    assert text.startswith("LLM 调用失败 [LLM-004]")
