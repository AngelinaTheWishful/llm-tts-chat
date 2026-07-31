"""LLMClient：OpenAI 兼容 API 客户端。

- 非流式调用，记录实际 token 用量（章节六十八）
- 指数退避重试 + 速率限制专用重试（章节十四/五十三）
- 多提供商故障转移（章节六十）
- API Key 支持 base64 解密（章节四十三）
"""

import time

from openai import OpenAI

from modules.base_manager import BaseManager
from modules.config_manager import decrypt_api_key

DEFAULT_TIMEOUT = 30


class LLMClient(BaseManager):
    """OpenAI 兼容 API 客户端（每个提供商配置一个实例）。"""

    def __init__(self, provider_config: dict):
        super().__init__("llm")
        self.base_url = provider_config.get("base_url", "").rstrip("/")
        self.api_key = decrypt_api_key(provider_config.get("api_key", ""))
        self.model = provider_config.get("model", "")
        self.max_tokens = provider_config.get("max_tokens", 2048)
        self.temperature = provider_config.get("temperature", 0.8)
        self.text_language = provider_config.get("text_language", "中文")
        self.last_usage: dict = {}
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=DEFAULT_TIMEOUT)

    def chat(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int | None = None,
    ) -> str:
        """调用 LLM 生成回复（非流式），返回文字并记录 token 用量。"""
        full_messages = [{"role": "system", "content": system_prompt}, *messages]

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
        )

        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.last_usage = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
        return resp.choices[0].message.content or ""

    def summarize(self, history: list[dict]) -> str:
        """将历史对话压缩为一段摘要。"""
        summary_prompt = "请将以上对话总结为一段简洁的摘要，保留关键信息："
        return self.chat("你是摘要助手", [*history, {"role": "user", "content": summary_prompt}])

    def get_last_usage(self) -> dict:
        """返回最近一次调用的 token 用量。"""
        return self.last_usage


def _is_rate_limit_error(e: Exception) -> bool:
    error_str = str(e).lower()
    keywords = ["rate limit", "rate_limit", "too many requests", "429", "限流", "频率限制"]
    return any(kw in error_str for kw in keywords)


def call_llm_with_retry(
    llm_client: LLMClient,
    system_prompt: str,
    messages: list[dict],
    max_retries: int = 2,
    base_delay: float = 1.0,
) -> str:
    """自动重试（指数退避）。"""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return llm_client.chat(system_prompt, messages)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                llm_client.log(
                    "warning",
                    f"LLM 调用失败，{delay:.0f}s 后重试 ({attempt + 1}/{max_retries}): {e}",
                )
                time.sleep(delay)
            else:
                llm_client.log("error", f"LLM 调用失败已达最大重试次数: {e}")
    raise last_error


def call_llm_with_rate_limit_retry(
    llm_client: LLMClient,
    system_prompt: str,
    messages: list[dict],
    max_retries: int = 3,
) -> str:
    """指数退避重试，处理 RateLimit 错误（5s→10s→20s）。"""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return llm_client.chat(system_prompt, messages)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                if _is_rate_limit_error(e):
                    delay = 5 * (2**attempt)  # 5s, 10s, 20s
                    llm_client.log(
                        "warning", f"LLM 速率限制，{delay}s 后重试 ({attempt + 1}/{max_retries})"
                    )
                else:
                    delay = 2 * (attempt + 1)  # 2s, 4s, 6s
                    llm_client.log(
                        "warning",
                        f"LLM 调用失败，{delay}s 后重试 ({attempt + 1}/{max_retries}): {e}",
                    )
                time.sleep(delay)
            else:
                llm_client.log("error", f"LLM 调用失败已达最大重试次数: {e}")
    raise last_error


def call_llm_with_fallback(
    providers: dict,
    active_provider: str,
    fallback_enabled: bool,
    system_prompt: str,
    messages: list[dict],
    session_provider: str | None = None,
) -> tuple[str, str]:
    """按优先级尝试各提供商，故障转移。

    Returns:
        (回复文字, 实际使用的提供商名称)
    """
    if session_provider:
        provider_names = [session_provider] if session_provider in providers else []
    else:
        provider_names = sorted(
            providers.keys(),
            key=lambda n: providers[n].get("priority", 99),
        )
        if active_provider and active_provider in provider_names:
            # 活动提供商优先
            provider_names.remove(active_provider)
            provider_names.insert(0, active_provider)
        if not fallback_enabled:
            provider_names = provider_names[:1]

    if not provider_names:
        raise ValueError("没有可用的 LLM 提供商")

    last_error: Exception | None = None
    for name in provider_names:
        config = providers.get(name)
        if not config:
            continue
        try:
            client = LLMClient(config)
            text = call_llm_with_rate_limit_retry(client, system_prompt, messages)
            return text, name
        except Exception as e:
            last_error = e
            continue

    if last_error is None:
        raise ValueError("没有可用的 LLM 提供商")
    raise last_error
