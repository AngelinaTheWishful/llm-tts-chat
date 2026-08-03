"""角色卡导入单元测试（章节六十九~七十一）。"""

import base64
import io
import json
import struct
import sys
import zlib
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.card_importer import (
    detect_card_format,
    extract_avatar_bytes,
    normalize_to_character,
    parse_cards,
)
from modules.character_manager import CharManager


def build_tavern_png(card: dict, size=(16, 16)) -> bytes:
    """构造带 tEXt 'chara' 块的 TavernAI PNG。"""
    img = Image.new("RGBA", size, (200, 100, 50, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    chara = base64.b64encode(json.dumps(card).encode("utf-8")).decode("latin-1")
    payload = b"chara\x00" + chara.encode("latin-1")
    chunk = (
        struct.pack(">I", len(payload))
        + b"tEXt"
        + payload
        + struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xFFFFFFFF)
    )
    iend = data.rfind(b"IEND")
    insert_at = iend - 4
    return data[:insert_at] + chunk + data[insert_at:]


TAVERN_V1 = {
    "name": "测试学姐",
    "description": "长发及肩，戴银框眼镜",
    "personality": "温柔耐心",
    "scenario": "学校天台",
    "first_mes": "你好呀，今天想聊什么？",
    "mes_example": "<START>用户：你好\n学姐：你好呀",
    "system_prompt": "思考后再回答",
    "tags": ["学姐", "校园"],
}

TAVERN_V2 = {
    "spec": "chara_card_v2",
    "data": {
        "name": "V2学姐",
        "description": "冷艳",
        "personality": "高冷",
        "first_mes": "有事？",
    },
}

RISU_CARD = {
    "name": "猫娘小咪",
    "description": "活泼的猫娘",
    "personality": "粘人",
    "scenario": "客厅",
    "first_mes": "喵～你回来啦！",
    "alternate_greetings": ["喵！想我了吗？", "今天去哪里玩了喵？"],
    "creator_notes": "示例角色",
    "character_version": "1.0",
}

CHUB_CARD = {
    "name": "Chub角色",
    "description": "描述",
    "greeting": "你好",
    "definition": "角色定义",
    "avatar_url": "https://example.com/a.png",
    "tags": ["chub"],
}


# ---------- 格式检测 ----------


def test_detect_formats(tmp_path):
    (tmp_path / "t1.png").write_bytes(build_tavern_png(TAVERN_V1))
    (tmp_path / "t2.json").write_text(json.dumps(TAVERN_V1, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "v2.json").write_text(json.dumps(TAVERN_V2, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "risu.json").write_text(json.dumps(RISU_CARD, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "chub.json").write_text(json.dumps(CHUB_CARD, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "bad.txt").write_text("not json", encoding="utf-8")

    assert detect_card_format(tmp_path / "t1.png") == "tavern_png"
    assert detect_card_format(tmp_path / "t2.json") == "tavern_json"
    assert detect_card_format(tmp_path / "v2.json") == "tavern_json"
    assert detect_card_format(tmp_path / "risu.json") == "risu"
    assert detect_card_format(tmp_path / "chub.json") == "chub"
    assert detect_card_format(tmp_path / "bad.txt") == ""


# ---------- 解析 ----------


def test_parse_tavern_png(tmp_path):
    p = tmp_path / "card.png"
    p.write_bytes(build_tavern_png(TAVERN_V1))
    cards, avatar, warnings = parse_cards(p)
    assert len(cards) == 1
    assert cards[0]["name"] == "测试学姐"
    assert avatar is not None  # PNG 本体作为头像


def test_parse_tavern_v2_unwrap(tmp_path):
    p = tmp_path / "v2.json"
    p.write_text(json.dumps(TAVERN_V2, ensure_ascii=False), encoding="utf-8")
    cards, avatar, _ = parse_cards(p)
    assert cards[0]["name"] == "V2学姐"
    assert cards[0]["first_mes"] == "有事？"
    assert avatar is None


def test_parse_risu_list_batch(tmp_path):
    p = tmp_path / "risu.json"
    p.write_text(
        json.dumps([RISU_CARD, {**RISU_CARD, "name": "猫娘二号"}], ensure_ascii=False),
        encoding="utf-8",
    )
    cards, _, warnings = parse_cards(p)
    assert len(cards) == 2
    assert any("批量导入" in w for w in warnings)


def test_parse_invalid(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_cards(p)


# ---------- 字段映射 ----------


def test_normalize_to_character():
    char = normalize_to_character(TAVERN_V1)
    assert char["name"] == "测试学姐"
    assert char["greeting"] == "你好呀，今天想聊什么？"
    assert char["system_prompt_structured"]["personality"] == "温柔耐心"
    assert "学校天台" in char["system_prompt_structured"]["background"]
    assert "长发及肩" in char["system_prompt_structured"]["background"]
    assert char["chain_of_thought"] == "思考后再回答"
    assert char["lorebook"]["enabled"] is True
    assert char["lorebook"]["entries"][0]["content"] == TAVERN_V1["mes_example"]
    assert char["tags"] == ["学姐", "校园"]


def test_normalize_alternate_greetings():
    char = normalize_to_character(RISU_CARD)
    assert char["alternate_greetings"] == RISU_CARD["alternate_greetings"]
    assert char["creator_notes"] == "示例角色"


# ---------- 头像 ----------


def test_extract_avatar_base64():
    png_bytes = build_tavern_png(TAVERN_V1, size=(8, 8))
    card = {"avatar": base64.b64encode(png_bytes).decode()}
    assert extract_avatar_bytes(card) == png_bytes


def test_extract_avatar_data_url():
    png_bytes = build_tavern_png(TAVERN_V1, size=(8, 8))
    png = base64.b64encode(png_bytes).decode()
    card = {"image": f"data:image/png;base64,{png}"}
    assert extract_avatar_bytes(card) == png_bytes


# ---------- CharManager 集成 ----------


def test_import_card_from_png(tmp_path):
    cm = CharManager(tmp_path / "chars")
    p = tmp_path / "card.png"
    p.write_bytes(build_tavern_png(TAVERN_V1, size=(24, 24)))
    imported, warnings = cm.import_card(p)
    assert imported == ["测试学姐"]
    char = cm.get_character("测试学姐")
    assert char is not None
    assert char["greeting"] == TAVERN_V1["first_mes"]
    assert (tmp_path / "chars" / "测试学姐" / "portrait.png").exists()
    assert (tmp_path / "chars" / "测试学姐" / "portrait_thumb.png").exists()


def test_import_card_conflict_suffix(tmp_path):
    cm = CharManager(tmp_path / "chars")
    p = tmp_path / "card.json"
    p.write_text(json.dumps(TAVERN_V1, ensure_ascii=False), encoding="utf-8")
    cm.import_card(p)
    imported2, _ = cm.import_card(p)
    assert imported2 == ["测试学姐_2"]
    assert cm.get_character("测试学姐_2") is not None


def test_import_card_json_list(tmp_path):
    cm = CharManager(tmp_path / "chars")
    p = tmp_path / "risu.json"
    p.write_text(
        json.dumps([RISU_CARD, {**RISU_CARD, "name": "猫娘二号"}], ensure_ascii=False),
        encoding="utf-8",
    )
    imported, _ = cm.import_card(p)
    assert imported == ["猫娘小咪", "猫娘二号"]
    assert len(cm.list_names()) == 2
