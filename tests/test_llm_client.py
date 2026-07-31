"""LLMClient 单元测试（mock OpenAI）。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.config_manager import encrypt_api_key
from modules.llm_client import (
    LLMClient,
    call_llm_with_fallback,
    call_llm_with_rate_limit_retry,
    call_llm_with_retry,
)

PROVIDER = {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": encrypt_api_key("sk-test"),
    "model": "deepseek-chat",
    "max_tokens": 2048,
    "temperature": 0.8,
    "text_language": "中文",
}


class FakeUsage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class FakeCompletion:
    def __init__(self, content, usage=None):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]
        self.usage = usage


def make_fake_client(monkeypatch, responses, usage=None):
    """构造一个 LLMClient，其 OpenAI 客户端 create 返回 responses 队列。"""

    client = LLMClient(PROVIDER)
    iter_responses = iter(responses)

    def fake_create(model=None, messages=None, max_tokens=None, temperature=None):
        try:
            return next(iter_responses)
        except StopIteration:
            raise RuntimeError("unexpected extra call")

    monkeypatch.setattr(
        client,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )
    return client


def test_chat_returns_text_and_usage(monkeypatch):
    client = make_fake_client(monkeypatch, [FakeCompletion("你好", usage=FakeUsage(100, 50))])
    text = client.chat("你是助手", [{"role": "user", "content": "hi"}])
    assert text == "你好"
    assert client.get_last_usage()["total_tokens"] == 150


def test_retry_succeeds_on_second_attempt(monkeypatch):
    client = LLMClient(PROVIDER)
    calls = {"n": 0}

    def fake_create(model=None, messages=None, max_tokens=None, temperature=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("temporary error")
        return FakeCompletion("ok", usage=FakeUsage(1, 1))

    monkeypatch.setattr(
        client,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )

    result = call_llm_with_retry(
        client, "sys", [{"role": "user", "content": "q"}], max_retries=2, base_delay=0
    )
    assert result == "ok"
    assert calls["n"] == 2


def test_retry_fails_raises(monkeypatch):
    client = LLMClient(PROVIDER)

    def fake_create(model=None, messages=None, max_tokens=None, temperature=None):
        raise RuntimeError("persistent failure")

    monkeypatch.setattr(
        client,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )

    with pytest.raises(RuntimeError):
        call_llm_with_retry(
            client, "sys", [{"role": "user", "content": "q"}], max_retries=1, base_delay=0
        )


def test_rate_limit_retry_detects_429(monkeypatch):
    client = LLMClient(PROVIDER)
    calls = {"n": 0}

    def fake_create(model=None, messages=None, max_tokens=None, temperature=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Error code: 429 - rate limit")
        return FakeCompletion("ok", usage=FakeUsage(1, 1))

    monkeypatch.setattr(
        client,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )

    result = call_llm_with_rate_limit_retry(
        client, "sys", [{"role": "user", "content": "q"}], max_retries=1
    )
    assert result == "ok"
    assert calls["n"] == 2


def test_fallback_uses_active_first(monkeypatch):
    import modules.llm_client as llm_module

    monkeypatch.setattr(llm_module.time, "sleep", lambda s: None)  # 加速重试等待

    providers = {
        "a": {**PROVIDER, "priority": 2, "_name": "a"},
        "b": {**PROVIDER, "priority": 1, "_name": "b"},
    }
    used = []

    class FakeLLMClient(llm_module.LLMClient):
        def __init__(self, config):
            super().__init__(config)
            self._name = config.get("_name")

        def chat(self, *args, **kwargs):
            used.append(self._name)
            if self._name == "a":
                raise RuntimeError("provider a failed")
            return f"from-{self._name}"

    monkeypatch.setattr(llm_module, "LLMClient", FakeLLMClient)

    text, name = call_llm_with_fallback(
        providers,
        active_provider="a",
        fallback_enabled=True,
        system_prompt="sys",
        messages=[{"role": "user", "content": "q"}],
    )
    assert text == "from-b"
    assert name == "b"
    assert used[0] == "a"  # 活动提供商优先尝试
    assert "b" in used  # 失败后转移到 b


def test_fallback_disabled_only_active(monkeypatch):
    import modules.llm_client as llm_module

    monkeypatch.setattr(llm_module.time, "sleep", lambda s: None)

    providers = {
        "a": {**PROVIDER, "priority": 1, "_name": "a"},
        "b": {**PROVIDER, "priority": 2, "_name": "b"},
    }
    used = []

    class FakeLLMClient(llm_module.LLMClient):
        def __init__(self, config):
            super().__init__(config)
            self._name = config.get("_name")

        def chat(self, *args, **kwargs):
            used.append(self._name)
            raise RuntimeError("fail")

    monkeypatch.setattr(llm_module, "LLMClient", FakeLLMClient)

    with pytest.raises(RuntimeError):
        call_llm_with_fallback(
            providers,
            active_provider="a",
            fallback_enabled=False,
            system_prompt="sys",
            messages=[{"role": "user", "content": "q"}],
        )
    assert set(used) == {"a"}  # 仅尝试活动提供商


def test_fallback_no_providers_raises_valueerror():
    with pytest.raises(ValueError):
        call_llm_with_fallback(
            {},
            active_provider="none",
            fallback_enabled=True,
            system_prompt="sys",
            messages=[{"role": "user", "content": "q"}],
        )
