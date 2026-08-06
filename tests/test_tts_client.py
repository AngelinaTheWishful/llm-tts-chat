"""TTSClient 单元测试（mock API）。"""

import io
import struct
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.tts_client import (
    TTSClient,
    _concat_wav,
    normalize_audio,
    split_tts_text,
    strip_markdown_for_tts,
)

# ---------- 工具函数 ----------


def test_strip_markdown_removes_code_and_links():
    text = "你好```code\nblock```再见[链接](http://x.com)结束"
    assert "code" not in strip_markdown_for_tts(text)
    assert "block" not in strip_markdown_for_tts(text)
    assert "链接" in strip_markdown_for_tts(text)
    assert "http://x.com" not in strip_markdown_for_tts(text)


def test_strip_markdown_keeps_bold_italic_text():
    text = "这是**加粗**和*斜体*文字"
    result = strip_markdown_for_tts(text)
    assert "加粗" in result
    assert "斜体" in result
    assert "*" not in result


def test_strip_markdown_removes_heading_list_quote():
    text = "# 标题\n> 引用\n- 列表项\n1. 编号项"
    result = strip_markdown_for_tts(text)
    assert "#" not in result
    assert ">" not in result
    assert "-" not in result
    assert "标题" in result
    assert "列表项" in result


def test_strip_markdown_removes_image_entirely():
    text = "前面![图片说明](http://x/img.png)后面"
    result = strip_markdown_for_tts(text)
    assert "图片说明" not in result
    assert "http://x" not in result
    assert "前面" in result
    assert "后面" in result


def test_split_tts_text_short_single():
    assert split_tts_text("你好，世界。") == ["你好，世界。"]


def test_split_tts_text_long_chunks():
    text = "第一句话。" * 200  # 1000 字
    chunks = split_tts_text(text, max_chars=300)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)
    assert "".join(chunks) == text.replace("\n", "")


def test_concat_wav_single():
    data = b"wav-data"
    assert _concat_wav([data]) == data


def test_concat_wav_multi():
    def make_wav(frames: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(frames)
        return buf.getvalue()

    part1 = make_wav(struct.pack("<10h", *([100] * 10)))
    part2 = make_wav(struct.pack("<10h", *([200] * 10)))
    result = _concat_wav([part1, part2])
    with wave.open(io.BytesIO(result), "rb") as w:
        assert w.getnframes() == 20


# ---------- mock API 测试 ----------


class MockResponse:
    def __init__(self, content=b"", json_data=None, status_code=200):
        self.content = content
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_check_api(monkeypatch):
    client = TTSClient("http://127.0.0.1:9880")

    def fake_get(url, params=None, timeout=30):
        assert url.endswith("/")  # api_v2 无健康接口，请求根路径判断存活
        return MockResponse(json_data={"status": "ok"})

    monkeypatch.setattr("requests.get", fake_get)
    assert client.check_api() is True


def test_check_api_offline(monkeypatch):
    client = TTSClient()

    def fake_get(url, params=None, timeout=30):
        raise ConnectionError("connection refused")

    monkeypatch.setattr("requests.get", fake_get)
    assert client.check_api() is False


def test_check_api_5xx_not_online(monkeypatch):
    """Q1：服务器返回 5xx 视为服务异常而非在线。"""
    client = TTSClient()

    def fake_get(url, params=None, timeout=30):
        return MockResponse(status_code=500)

    monkeypatch.setattr("requests.get", fake_get)
    assert client.check_api() is False


def test_set_refer_audio_params(monkeypatch):
    client = TTSClient()
    captured = {}

    def fake_get(url, params=None, timeout=30):
        captured["url"] = url
        captured["params"] = params
        return MockResponse(json_data={"status": "ok"})

    monkeypatch.setattr("requests.get", fake_get)
    ok = client.set_refer_audio("ref.wav", "今天天气好", "中文")
    assert ok is True
    assert captured["url"].endswith("/set_refer_audio")
    assert captured["params"] == {"refer_audio_path": "ref.wav"}  # api_v2 仅接受该参数
    assert client.prompt_text == "今天天气好"
    assert client.prompt_lang == "zh"  # 中文 → zh


def test_synthesize_sends_api_v2_params(monkeypatch):
    """api_v2 的 /tts 需携带 ref_audio_path / prompt_lang / text_lang / speed_factor。"""
    client = TTSClient()
    client.set_refer_audio("ref.wav", "提示文本", "中文")
    captured = {}

    def fake_get(url, params=None, timeout=30):
        captured["url"] = url
        captured["params"] = params
        return MockResponse(content=b"WAVDATA")

    monkeypatch.setattr("requests.get", fake_get)
    data = client.synthesize("你好", "日本語", speed=1.2)
    assert data == b"WAVDATA"
    assert captured["url"].endswith("/tts")
    p = captured["params"]
    assert p["text_lang"] == "ja"  # 日本語 → ja
    assert p["ref_audio_path"] == "ref.wav"
    assert p["prompt_lang"] == "zh"
    assert p["prompt_text"] == "提示文本"
    assert p["speed_factor"] == 1.2


def test_synthesize_retry_then_success(monkeypatch):
    client = TTSClient()
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=30):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("server busy")
        return MockResponse(content=b"WAVDATA")

    monkeypatch.setattr("requests.get", fake_get)
    data = client.synthesize("你好", "中文")
    assert data == b"WAVDATA"
    assert calls["n"] == 3


def test_synthesize_fail_raises(monkeypatch):
    client = TTSClient()

    def fake_get(url, params=None, timeout=30):
        raise RuntimeError("always fail")

    monkeypatch.setattr("requests.get", fake_get)
    with pytest.raises(RuntimeError):
        client.synthesize("你好", "中文")


def test_synthesize_serialized(monkeypatch):
    """验证串行化：同一时间只有一个 TTS 请求。"""
    import threading
    import time

    client = TTSClient()
    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def fake_get(url, params=None, timeout=30):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.05)
        with lock:
            active["n"] -= 1
        return MockResponse(content=b"WAV")

    monkeypatch.setattr("requests.get", fake_get)

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(client.synthesize("x", "中文")))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert active["max"] == 1  # 并发峰值恒为 1
    assert all(r == b"WAV" for r in results)


def test_list_gpt_models(tmp_path):
    (tmp_path / "GPT_weights_v2Pro").mkdir(parents=True)
    (tmp_path / "GPT_weights_v2Pro" / "a.ckpt").write_bytes(b"")
    (tmp_path / "GPT_weights_v2Pro" / "b.ckpt").write_bytes(b"")
    (tmp_path / "GPT_weights_v2Pro" / "ignore.pth").write_bytes(b"")
    (tmp_path / "GPT_weights_v2").mkdir()
    (tmp_path / "GPT_weights_v2" / "c.ckpt").write_bytes(b"")

    models = TTSClient.list_gpt_models(str(tmp_path))
    assert len(models) == 3
    assert all(m.endswith(".ckpt") for m in models)


def test_list_sovits_models(tmp_path):
    (tmp_path / "SoVITS_weights_v2Pro").mkdir(parents=True)
    (tmp_path / "SoVITS_weights_v2Pro" / "x.pth").write_bytes(b"")

    models = TTSClient.list_sovits_models(str(tmp_path))
    assert models == [str(tmp_path / "SoVITS_weights_v2Pro" / "x.pth")]


# ---------- 音量标准化（章节七十五） ----------


def make_sine_wav(peak_amp: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack("<200h", *([peak_amp] * 200)))
    return buf.getvalue()


def test_normalize_audio_boosts_quiet_to_target():
    # 峰值 8000 约 -12dB，标准化到 -3dB 应放大
    wav = make_sine_wav(8000)
    out = normalize_audio(wav, target_db=-3.0)
    with wave.open(io.BytesIO(out), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    assert max(abs(s) for s in samples) > 8000  # 被放大


def test_normalize_audio_clamps_no_clip():
    # 峰值接近满幅，标准化不应导致超出 32767
    wav = make_sine_wav(32000)
    out = normalize_audio(wav, target_db=-3.0)
    with wave.open(io.BytesIO(out), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    assert all(-32768 <= s <= 32767 for s in samples)


def test_normalize_audio_noop_when_already_at_target():
    # 峰值接近 -3dB（23198 约等于 32768*10^(-3/20)），增益应接近 1
    wav = make_sine_wav(23198)
    out = normalize_audio(wav, target_db=-3.0)
    with wave.open(io.BytesIO(out), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    assert abs(max(abs(s) for s in samples) - 23198) <= 2  # 峰值基本不变


def test_normalize_audio_applies_global_volume():
    wav = make_sine_wav(16000)
    out_full = normalize_audio(wav, target_db=0.0, global_volume=1.0)
    out_half = normalize_audio(wav, target_db=0.0, global_volume=0.5)

    def peak(data):
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.readframes(w.getnframes())
        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
        return max(abs(s) for s in samples)

    assert peak(out_full) > peak(out_half)  # 全局倍率 0.5 显著降低输出峰值


def test_set_gpt_weights_serialized(monkeypatch):
    """set_* 方法应经过串行化执行器。"""
    client = TTSClient()
    captured = {}

    def fake_get(url, params=None, timeout=30):
        captured["url"] = url
        captured["params"] = params
        return MockResponse(json_data={"status": "ok"})

    monkeypatch.setattr("requests.get", fake_get)
    ok = client.set_gpt_weights("GPT_weights_v2Pro/a.ckpt")
    assert ok is True
    assert captured["url"].endswith("/set_gpt_weights")
    assert captured["params"]["weights_path"] == "GPT_weights_v2Pro/a.ckpt"
