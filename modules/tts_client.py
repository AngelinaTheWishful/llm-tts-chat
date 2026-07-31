"""TTSClient：GPT-SoVITS REST API 客户端。

- 串行化执行（TTSSerializer）：set_* 为全局状态，避免并发覆盖
- 自动重试（指数退避）
- 长文本分片合成（800 字/片）+ WAV 拼接
- TTS 前剥离影响语音的 Markdown 语法
- 模型列表本地只读扫描
"""

import io
import math
import re
import struct
import threading
import time
import wave
from pathlib import Path

import requests

from modules.base_manager import BaseManager

DEFAULT_TIMEOUT = 30  # 所有网络请求 30s 超时

GSV_SCAN_DIRS_GPT = [
    "GPT_weights",
    "GPT_weights_v2",
    "GPT_weights_v2Pro",
    "GPT_weights_v2ProPlus",
    "GPT_weights_v3",
    "GPT_weights_v4",
]
GSV_SCAN_DIRS_SOVITS = [
    "SoVITS_weights",
    "SoVITS_weights_v2",
    "SoVITS_weights_v2Pro",
    "SoVITS_weights_v2ProPlus",
    "SoVITS_weights_v3",
    "SoVITS_weights_v4",
]

DEFAULT_MAX_CHUNK_CHARS = 800

# GPT-SoVITS api_v2.py 语言代码（TTS_infer_pack v2 系列）
LANG_MAP = {
    "中文": "zh",
    "日本語": "ja",
    "English": "en",
    "한국어": "ko",
    "粤语": "yue",
    "自动": "auto",
    "auto": "auto",
    "zh": "zh",
    "ja": "ja",
    "en": "en",
    "ko": "ko",
    "yue": "yue",
}


def map_tts_lang(lang: str) -> str:
    """将界面语种名（如"中文"）映射为 api_v2 的语言代码（zh）。"""
    return LANG_MAP.get(str(lang).strip(), "zh")


def strip_markdown_for_tts(text: str) -> str:
    """剥离影响 TTS 的 Markdown 语法，返回纯文本。

    剥离范围：代码块/行内代码/图片/链接/分隔线/标题/引用/列表标记。
    保留：加粗/斜体的文字内容（仅去除标记）。
    """
    if not text:
        return ""

    # 1. 移除代码块（含内容）
    text = re.sub(r"```[\s\S]*?```", "", text)
    # 2. 行内代码标记，保留内容
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # 3. 图片：整条移除（需求 81.1）
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", "", text)
    # 4. 链接：只保留显示文字
    text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # 5. 分隔线
    text = re.sub(r"\n---+\n", "\n", text)
    # 6. 标题标记
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 7. 引用标记
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # 8. 列表标记
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # 9. 保留加粗/斜体文字，去除标记
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)

    # 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_tts_text(text: str, max_chars: int = DEFAULT_MAX_CHUNK_CHARS) -> list[str]:
    """将长文本按句子边界分片，每片不超过 max_chars 字。"""
    sentences = re.split(r"(?<=[。！？.!?\n])", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if not sentence.strip():
            continue
        if len(current) + len(sentence) <= max_chars:
            current += sentence
        else:
            if current:
                chunks.append(current.strip())
            # 单句超限则强制截断
            while len(sentence) > max_chars:
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            current = sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _concat_wav(audio_parts: list[bytes]) -> bytes:
    """拼接多段 wav 为完整 wav。"""
    if not audio_parts:
        return b""
    if len(audio_parts) == 1:
        return audio_parts[0]

    with wave.open(io.BytesIO(audio_parts[0]), "rb") as w0:
        channels = w0.getnchannels()
        sampwidth = w0.getsampwidth()
        framerate = w0.getframerate()

    output = io.BytesIO()
    with wave.open(output, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        for part in audio_parts:
            with wave.open(io.BytesIO(part), "rb") as wp:
                out.writeframes(wp.readframes(wp.getnframes()))

    return output.getvalue()


def normalize_audio(wav_bytes: bytes, target_db: float = -3.0, global_volume: float = 1.0) -> bytes:
    """将 wav 音频峰值标准化到 target_db，并应用全局音量倍率。

    - 仅处理 16-bit PCM（其他格式原样返回）
    - 采样钳制到 [-32768, 32767] 防削波
    """
    if not wav_bytes:
        return wav_bytes

    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        frames = w.readframes(w.getnframes())

    if sampwidth != 2:
        return wav_bytes

    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    peak = max((abs(s) for s in samples), default=0)
    if peak == 0:
        return wav_bytes

    # 峰值标准化增益 + 全局音量倍率
    current_db = 20 * math.log10(peak / 32768)
    gain = 10 ** ((target_db - current_db) / 20)
    gain *= global_volume

    if abs(gain - 1.0) < 1e-6:
        return wav_bytes

    normalized = struct.pack(
        f"<{len(samples)}h",
        *[max(-32768, min(32767, int(s * gain))) for s in samples],
    )

    output = io.BytesIO()
    with wave.open(output, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(normalized)
    return output.getvalue()


class TTSSerializer:
    """TTS 串行化执行器：全局锁确保同一时间只处理一个 TTS 请求。"""

    def __init__(self):
        self._lock = threading.Lock()

    def execute(self, func, *args, **kwargs):
        with self._lock:
            return func(*args, **kwargs)


class TTSClient(BaseManager):
    """GPT-SoVITS REST API 客户端。"""

    def __init__(
        self, api_base_url: str = "http://127.0.0.1:9880", serializer: TTSSerializer | None = None
    ):
        super().__init__("tts")
        self.base = api_base_url.rstrip("/")
        self.timeout = DEFAULT_TIMEOUT
        self.serializer = serializer or TTSSerializer()
        # 参考音频状态（api_v2 的 /tts 每次调用都需携带）
        self.ref_audio_path = ""
        self.prompt_text = ""
        self.prompt_lang = "zh"

    # ---------- 基础请求 ----------

    def _get(self, endpoint: str, params: dict | None = None) -> requests.Response:
        """GET 请求并检查 HTTP 状态。"""
        resp = requests.get(f"{self.base}{endpoint}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def check_api(self) -> bool:
        """检查 GPT-SoVITS API 是否存活。

        api_v2.py 无独立健康接口，/control 需 command 参数。
        以"服务器是否有任何 HTTP 响应"作为存活判据（404 即服务在线）。
        """
        try:
            requests.get(f"{self.base}/", timeout=min(10, self.timeout))
            return True
        except requests.ConnectionError:
            return False
        except Exception as e:
            self.log("warning", f"TTS API 健康检查失败: {e}")
            return False

    def set_refer_audio(
        self, ref_audio_path: str, prompt_text: str = "", prompt_lang: str = "zh"
    ) -> bool:
        """设置参考音频（串行化执行）。

        api_v2 的 /set_refer_audio 仅接受 refer_audio_path；
        prompt_text/prompt_lang 由本客户端暂存，/tts 调用时自动携带。
        """
        self.ref_audio_path = ref_audio_path
        self.prompt_text = prompt_text
        if prompt_lang:
            self.prompt_lang = map_tts_lang(prompt_lang)
        return self.serializer.execute(self._set_refer_audio, ref_audio_path)

    def _set_refer_audio(self, ref_audio_path: str) -> bool:
        try:
            self._get("/set_refer_audio", {"refer_audio_path": ref_audio_path})
            self.log("debug", f"参考音频已设置: {ref_audio_path}")
            return True
        except Exception as e:
            self.log("error", f"设置参考音频失败: {e}")
            return False

    def set_gpt_weights(self, weights_path: str) -> bool:
        """GET /set_gpt_weights 设置 GPT 模型权重（串行化执行）。"""
        return self.serializer.execute(self._set_gpt_weights, weights_path)

    def _set_gpt_weights(self, weights_path: str) -> bool:
        try:
            self._get("/set_gpt_weights", {"weights_path": weights_path})
            self.log("debug", f"GPT 权重已设置: {weights_path}")
            return True
        except Exception as e:
            self.log("error", f"设置 GPT 权重失败: {e}")
            return False

    def set_sovits_weights(self, weights_path: str) -> bool:
        """GET /set_sovits_weights 设置 SoVITS 模型权重（串行化执行）。"""
        return self.serializer.execute(self._set_sovits_weights, weights_path)

    def _set_sovits_weights(self, weights_path: str) -> bool:
        try:
            self._get("/set_sovits_weights", {"weights_path": weights_path})
            self.log("debug", f"SoVITS 权重已设置: {weights_path}")
            return True
        except Exception as e:
            self.log("error", f"设置 SoVITS 权重失败: {e}")
            return False

    # ---------- 语音合成 ----------

    def synthesize(
        self,
        text: str,
        text_language: str,
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
        speed: float = 1.0,
    ) -> bytes:
        """GET /tts 合成语音，返回 wav 二进制（串行化执行）。"""
        return self.serializer.execute(
            self._synthesize, text, text_language, top_k, top_p, temperature, speed
        )

    def _synthesize(self, text: str, text_language: str, top_k, top_p, temperature, speed) -> bytes:
        last_error: Exception | None = None
        for attempt in range(3):  # 指数退避重试
            try:
                params = {
                    "text": text,
                    "text_lang": map_tts_lang(text_language),
                    "ref_audio_path": self.ref_audio_path,
                    "prompt_text": self.prompt_text,
                    "prompt_lang": self.prompt_lang,
                    "top_k": top_k,
                    "top_p": top_p,
                    "temperature": temperature,
                    "speed_factor": speed,
                    "text_split_method": "cut5",
                    "batch_size": 1,
                    "media_type": "wav",
                }
                resp = self._get("/tts", params)
                self.log(
                    "debug",
                    f"TTS 合成成功: {len(text)}字 / {len(resp.content)} bytes",
                )
                return resp.content
            except Exception as e:
                last_error = e
                if attempt < 2:
                    delay = 1.0 * (2**attempt)
                    self.log("warning", f"TTS 合成失败，{delay:.0f}s 后重试 ({attempt + 1}/3): {e}")
                    time.sleep(delay)
        raise RuntimeError(f"TTS 合成失败已达最大重试次数: {last_error}")

    def synthesize_long(self, text: str, text_language: str, params: dict | None = None) -> bytes:
        """长文本分片合成并拼接为完整 wav。"""
        params = params or {}
        text = strip_markdown_for_tts(text)
        chunks = split_tts_text(text)

        if len(chunks) == 1:
            return self.synthesize(chunks[0], text_language, **params)

        self.log("info", f"长文本分片合成: {len(chunks)} 片")
        audio_parts = []
        for i, chunk in enumerate(chunks):
            self.log("debug", f"合成分片 {i + 1}/{len(chunks)} ({len(chunk)}字)")
            audio_parts.append(self.synthesize(chunk, text_language, **params))

        return _concat_wav(audio_parts)

    def synthesize_normalized(
        self,
        text: str,
        text_language: str,
        params: dict | None = None,
        target_db: float = -3.0,
        global_volume: float = 1.0,
    ) -> bytes:
        """合成后做峰值标准化（章节七十五）。"""
        wav_bytes = self.synthesize_long(text, text_language, params)
        return normalize_audio(wav_bytes, target_db=target_db, global_volume=global_volume)

    # ---------- 模型列表（本地只读扫描） ----------

    @staticmethod
    def list_gpt_models(gsv_root: str) -> list[str]:
        """扫描 GPT 权重目录，返回 .ckpt 绝对路径列表。"""
        return TTSClient._scan_models(gsv_root, GSV_SCAN_DIRS_GPT, "*.ckpt")

    @staticmethod
    def list_sovits_models(gsv_root: str) -> list[str]:
        """扫描 SoVITS 权重目录，返回 .pth 绝对路径列表。"""
        return TTSClient._scan_models(gsv_root, GSV_SCAN_DIRS_SOVITS, "*.pth")

    @staticmethod
    def _scan_models(gsv_root: str, scan_dirs: list[str], pattern: str) -> list[str]:
        root = Path(gsv_root)
        models: list[str] = []
        for d in scan_dirs:
            target = root / d
            if target.exists():
                models.extend(str(f) for f in sorted(target.glob(pattern)))
        return models
