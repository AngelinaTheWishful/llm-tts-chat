"""card_importer：角色卡格式兼容导入（章节六十九~七十一）。

支持格式（自动检测，无需用户选择）：
- TavernAI PNG：tEXt chunk "chara" 内 base64 JSON（chara_card_v1/v2/v3）
- TavernAI / RisuAI / Chub / CAI JSON：按结构自动识别
- RisuAI 列表：批量导入多个角色
"""

import base64
import io
import json
import re
from pathlib import Path

from PIL import Image

FORMAT_TAVERN_PNG = "tavern_png"
FORMAT_TAVERN_JSON = "tavern_json"
FORMAT_RISU = "risu"
FORMAT_CHUB = "chub"
FORMAT_CAI = "cai"

_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def _png_text_chunks(raw: bytes) -> dict:
    """按 PNG chunk 结构提取 tEXt/iTXt 文本块（返回 keyword→text）。"""
    chunks: dict = {}
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return chunks
    pos = 8
    while pos + 12 <= len(raw):
        length = int.from_bytes(raw[pos : pos + 4], "big")
        ctype = raw[pos + 4 : pos + 8]
        if pos + 8 + length > len(raw):
            break
        data = raw[pos + 8 : pos + 8 + length]
        if ctype == b"tEXt":
            null = data.find(b"\x00")
            if null > 0:
                kw = data[:null].decode("latin-1", "replace")
                txt = data[null + 1 :].decode("latin-1", "replace")
                chunks[kw] = txt
        elif ctype == b"iTXt":
            null = data.find(b"\x00")
            if null > 0:
                kw = data[:null].decode("latin-1", "replace")
                parts = data[null + 1 :].split(b"\x00", 4)
                if len(parts) >= 5:
                    chunks[kw] = parts[4].decode("utf-8", "replace")
        if ctype == b"IEND":
            break
        pos += 12 + length
    return chunks


def detect_json_format(data) -> str:
    """根据 JSON 结构判断角色卡格式。"""
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return ""
    spec = str(data.get("spec", "") or "")
    if spec.startswith("chara_card") or isinstance(data.get("data"), dict):
        return FORMAT_TAVERN_JSON
    if "alternate_greetings" in data or "character_version" in data or "extensions" in data:
        return FORMAT_RISU
    if "first_mes" in data or "personality" in data or "mes_example" in data:
        return FORMAT_TAVERN_JSON
    if "greeting" in data and "definition" in data:
        return FORMAT_CHUB if "avatar_url" in data else FORMAT_CAI
    if "name" in data and ("description" in data or "personality" in data):
        return FORMAT_TAVERN_JSON
    return ""


def detect_card_format(path) -> str:
    """根据扩展名与内容自动检测角色卡格式。"""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    if suffix == ".png":
        return FORMAT_TAVERN_PNG if "chara" in _png_text_chunks(raw) else ""
    if suffix in (".json", ".risuai", ".txt"):
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return ""
        return detect_json_format(data)
    return ""


def _unwrap_v2(card: dict) -> dict:
    """chara_card_v2/v3：data 为内层字段，顶层保留 creator/character_book 等。"""
    if not isinstance(card, dict):
        return card
    spec = str(card.get("spec", "") or "")
    if spec.startswith("chara_card") and isinstance(card.get("data"), dict):
        merged = dict(card)
        merged.update(card["data"])
        merged.pop("data", None)
        merged.pop("spec", None)
        return merged
    return card


def parse_cards(path) -> tuple[list[dict], bytes | None, list[str]]:
    """解析角色卡文件。

    Returns:
        (角色卡 dict 列表, PNG 头像字节|None, 警告列表)
    """
    p = Path(path)
    # Q11：单文件大小限制（≤50MB，用户选定），防止超大文件耗尽内存
    if p.is_file() and p.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("角色卡文件超过 50MB 限制，拒绝导入")

    fmt = detect_card_format(path)
    if not fmt:
        raise ValueError("无法识别角色卡格式（支持 TavernAI PNG/JSON、RisuAI、Chub、CAI）")

    if fmt == FORMAT_TAVERN_PNG:
        raw = p.read_bytes()
        chara = _png_text_chunks(raw).get("chara", "")
        if not chara:
            raise ValueError("PNG 中未找到 chara 角色数据")
        try:
            card = json.loads(base64.b64decode(chara).decode("utf-8", "replace"))
        except Exception:
            try:
                card = json.loads(chara)
            except Exception:
                raise ValueError("PNG 内嵌角色数据解析失败")
        return [_unwrap_v2(card)], raw, []

    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError):
        raise ValueError("JSON 解析失败")

    if isinstance(data, list):
        if not data:
            return [], None, ["角色列表为空"]
        cards = [_unwrap_v2(c) for c in data if isinstance(c, dict)]
        return cards, None, [f"检测到 {len(cards)} 个角色，将批量导入"]
    if isinstance(data, dict) and isinstance(data.get("characters"), list):
        cards = [_unwrap_v2(c) for c in data["characters"] if isinstance(c, dict)]
        return cards, None, [f"检测到 {len(cards)} 个角色，将批量导入"]
    return [_unwrap_v2(data)], None, []


def _looks_base64(text: str) -> bool:
    return len(text) >= 32 and bool(_B64_RE.match(text))


def extract_avatar_bytes(card: dict) -> bytes | None:
    """从 JSON 角色卡中提取头像（data:image 或 base64）。"""
    for key in ("avatar", "avatar_base64", "image", "char_image", "portrait"):
        val = card.get(key)
        if not isinstance(val, str) or not val:
            continue
        if val.startswith("data:image"):
            try:
                return base64.b64decode(val.split(",", 1)[1])
            except Exception:
                return None
        if _looks_base64(val):
            try:
                return base64.b64decode(val)
            except Exception:
                return None
    return None


def normalize_to_character(card: dict) -> dict:
    """将角色卡字段映射为本项目 character.json 格式（章节 69.2/70.2/71.1）。"""
    name = str(card.get("name") or "").strip() or "未知角色"
    desc = str(card.get("description") or "").strip()
    personality = str(card.get("personality") or "").strip()
    scenario = str(card.get("scenario") or "").strip()
    first_mes = str(card.get("first_mes") or card.get("greeting") or "").strip()
    mes_example = str(card.get("mes_example") or "").strip()
    system_prompt = str(card.get("system_prompt") or "").strip()
    post_history = str(card.get("post_history_instructions") or "").strip()
    alternate = [
        g for g in (card.get("alternate_greetings") or []) if isinstance(g, str) and g.strip()
    ]
    tags = [t for t in (card.get("tags") or []) if isinstance(t, str)]
    creator_notes = str(
        card.get("creator_notes") or card.get("notes") or card.get("creator_comment") or ""
    ).strip()

    character: dict = {
        "name": name,
        "greeting": first_mes,
        "basic": {"appearance": desc},
        "system_prompt_structured": {
            "personality": personality,
            "speaking_style": "",
            "speech_quirks": [],
            "background": "\n".join(x for x in (desc, scenario) if x),
            "likes": [],
            "dislikes": [],
            "behavior_rules": [],
        },
        "lorebook": {"enabled": False, "entries": []},
    }

    cot = "\n".join(x for x in (system_prompt, post_history) if x)
    if cot:
        character["chain_of_thought"] = cot
    if mes_example:
        character["lorebook"]["enabled"] = True
        character["lorebook"]["entries"] = [{"keywords": [], "content": mes_example}]
    if alternate:
        character["alternate_greetings"] = alternate
    if tags:
        character["tags"] = tags
    if creator_notes:
        character["creator_notes"] = creator_notes
    return character


def card_to_avatar_png(card: dict, avatar_bytes: bytes | None = None) -> bytes | None:
    """将头像字节统一转 PNG 并返回（失败返回 None）。"""
    data = avatar_bytes or extract_avatar_bytes(card)
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA")
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None
