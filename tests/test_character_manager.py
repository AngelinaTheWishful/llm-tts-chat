"""CharManager 单元测试。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.character_manager import CharManager

SAMPLE_CHAR = {
    "name": "测试角色",
    "basic": {"nickname": "测试", "gender": "女", "age": "18", "appearance": "长发"},
    "system_prompt_structured": {
        "personality": "温柔",
        "speaking_style": "柔和",
        "speech_quirks": [],
        "background": "学生",
        "likes": ["阅读"],
        "dislikes": [],
        "behavior_rules": [],
    },
    "chain_of_thought": "",
    "greeting": "你好",
    "recommended_settings": {},
}


def make_char_dir(base: Path, name: str) -> Path:
    char_dir = base / name
    char_dir.mkdir(parents=True)
    (char_dir / "character.json").write_text(
        json.dumps({**SAMPLE_CHAR, "name": name}, ensure_ascii=False), encoding="utf-8"
    )
    return char_dir


def test_list_and_get_character(tmp_path):
    make_char_dir(tmp_path, "角色A")
    make_char_dir(tmp_path, "角色B")
    mgr = CharManager(tmp_path)
    names = mgr.list_names()
    assert "角色A" in names
    assert "角色B" in names
    char = mgr.get_character("角色A")
    assert char["name"] == "角色A"
    assert char["_dir"].endswith("角色A")
    assert mgr.get_character("不存在") is None


def test_save_and_update_character(tmp_path):
    mgr = CharManager(tmp_path)
    mgr.save_character(SAMPLE_CHAR)
    char = mgr.get_character("测试角色")
    assert char is not None
    assert char["greeting"] == "你好"


def test_delete_character_moves_to_trash(tmp_path):
    make_char_dir(tmp_path, "待删角色")
    mgr = CharManager(tmp_path, trash_dir=tmp_path.parent / "trash" / "characters")
    assert mgr.delete_character("待删角色") is True
    assert mgr.get_character("待删角色") is None
    assert any(p.name.startswith("待删角色") for p in mgr.trash_dir.iterdir())


def test_export_and_import_character(tmp_path):
    src = tmp_path / "chars"
    make_char_dir(src, "导出角色")
    mgr = CharManager(src)
    zip_path = mgr.export_character("导出角色")
    assert zip_path is not None and Path(zip_path).exists()

    # 导入到新目录
    dst = tmp_path / "chars2"
    mgr2 = CharManager(dst)
    warnings = mgr2.import_character(zip_path)
    assert mgr2.get_character("导出角色") is not None
    assert any("头像" in w for w in warnings)  # 仅缺头像文件


def test_import_character_zip_slip_guarded(tmp_path):
    """恶意 zip 含 ../ 路径时跳过该成员，不越界写出（zip-slip 修复）。"""
    import zipfile

    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("character.json", json.dumps({**SAMPLE_CHAR, "name": "越界测试"}))
        zf.writestr("../evil.txt", "pwned")

    mgr = CharManager(tmp_path / "chars")
    warnings = mgr.import_character(evil_zip)
    assert mgr.get_character("越界测试") is not None  # 正常成员仍导入
    assert not (tmp_path / "evil.txt").exists()  # 越界成员未写出
    assert any("不安全" in w for w in warnings)


def test_import_character_rejects_zip_bomb(tmp_path):
    """超大/超多成员的 zip 拒绝导入（zip 炸弹防护，修复）。"""
    import zipfile

    bomb_zip = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        zf.writestr("character.json", json.dumps({**SAMPLE_CHAR, "name": "炸弹"}))
        zf.writestr("big.bin", b"\0" * (101 * 1024 * 1024))

    mgr = CharManager(tmp_path / "chars")
    warnings = mgr.import_character(bomb_zip)
    assert mgr.get_character("炸弹") is None  # 拒绝导入
    assert any("超大" in w or "超过" in w for w in warnings)


def test_import_character_folder(tmp_path):
    src = tmp_path / "ext_source"
    make_char_dir(src, "外部角色")
    mgr = CharManager(tmp_path / "chars")
    warnings = mgr.import_character(src / "外部角色")
    assert mgr.get_character("外部角色") is not None
    assert any("缺少" in w for w in warnings)  # 无头像/参考音频警告


def test_update_portrait(tmp_path):
    from PIL import Image

    make_char_dir(tmp_path, "头像角色")
    upload = tmp_path / "upload.png"
    Image.new("RGB", (100, 200), (255, 0, 0)).save(upload)

    mgr = CharManager(tmp_path)
    result = mgr.update_portrait("头像角色", str(upload))
    assert Path(result["main"]).exists()
    assert Path(result["thumb"]).exists()
    with Image.open(result["main"]) as img:
        assert img.size == (512, 512)
    with Image.open(result["thumb"]) as img:
        assert img.size == (64, 64)


def test_update_portrait_rejects_oversize(tmp_path):
    """Q6：上传头像超过 80MB 限制时拒绝。"""
    import pytest

    make_char_dir(tmp_path, "大头像")
    upload = tmp_path / "huge.png"
    # 用稀疏文件模拟超大文件（无需真实 80MB）
    with open(upload, "wb") as f:
        f.seek(80 * 1024 * 1024)
        f.write(b"\x00")

    mgr = CharManager(tmp_path)
    with pytest.raises(ValueError, match="80MB"):
        mgr.update_portrait("大头像", str(upload))


def test_validate_package_warns_missing_files(tmp_path):
    char_dir = tmp_path / "不完整"
    char_dir.mkdir()
    (char_dir / "character.json").write_text("{}", encoding="utf-8")
    mgr = CharManager(tmp_path)
    warnings = mgr.validate_package("不完整")
    assert any("头像" in w for w in warnings)


def test_apply_preset_resolves_model_against_gsv_root(tmp_path):
    gsv = tmp_path / "gsv"
    (gsv / "GPT_weights_v2Pro").mkdir(parents=True)
    (gsv / "GPT_weights_v2Pro" / "a.ckpt").write_bytes(b"")
    (gsv / "SoVITS_weights_v2Pro").mkdir(parents=True)
    (gsv / "SoVITS_weights_v2Pro" / "a.pth").write_bytes(b"")

    char_dir = make_char_dir(tmp_path, "预设角色")
    (char_dir / "ref.wav").write_bytes(b"WAV")
    char = {
        **SAMPLE_CHAR,
        "name": "预设角色",
        "recommended_settings": {
            "gpt_model": "GPT_weights_v2Pro/a.ckpt",  # 相对 gsv_root
            "sovits_model": "SoVITS_weights_v2Pro/a.pth",
            "ref_audio": "ref.wav",
            "ref_text": "测试",
            "ref_language": "中文",
        },
    }
    mgr = CharManager(tmp_path)
    calls = []

    class FakeTTS:
        def set_gpt_weights(self, p):
            calls.append(("gpt", p))

        def set_sovits_weights(self, p):
            calls.append(("sovits", p))

        def set_refer_audio(self, p, t, lang):
            calls.append(("ref", p, t, lang))

    mgr.apply_preset(char, FakeTTS(), gsv_root=str(gsv))
    gpt_call = next(c for c in calls if c[0] == "gpt")
    assert gpt_call[1] == str(gsv / "GPT_weights_v2Pro" / "a.ckpt")  # 相对路径已解析
    ref_call = next(c for c in calls if c[0] == "ref")
    assert ref_call[1].endswith("ref.wav")


def test_apply_preset(tmp_path):
    char_dir = make_char_dir(tmp_path, "预设角色")
    (char_dir / "ref.wav").write_bytes(b"WAV")
    char = {
        **SAMPLE_CHAR,
        "name": "预设角色",
        "recommended_settings": {
            "gpt_model": "GPT_weights_v2Pro/a.ckpt",
            "sovits_model": "SoVITS_weights_v2Pro/a.pth",
            "ref_audio": "ref.wav",
            "ref_text": "测试",
            "ref_language": "中文",
        },
    }
    mgr = CharManager(tmp_path)
    calls = []

    class FakeTTS:
        def set_gpt_weights(self, p):
            calls.append(("gpt", p))

        def set_sovits_weights(self, p):
            calls.append(("sovits", p))

        def set_refer_audio(self, p, t, lang):
            calls.append(("ref", p, t, lang))

    mgr.apply_preset(char, FakeTTS())
    assert ("gpt", "GPT_weights_v2Pro/a.ckpt") in calls
    assert ("sovits", "SoVITS_weights_v2Pro/a.pth") in calls
    ref_call = next(c for c in calls if c[0] == "ref")
    assert ref_call[1].endswith("ref.wav")  # 相对路径解析为绝对路径
    assert ref_call[2] == "测试"


def test_apply_preset_defaults_weights_and_ref_audio(tmp_path):
    """角色无音色预设时回退默认权重与训练日志参考音频（v1.1.4）。"""
    gsv = tmp_path / "gsv"
    (gsv / "GPT_weights_v2Pro").mkdir(parents=True)
    (gsv / "GPT_weights_v2Pro" / "EXP01-e10.ckpt").write_bytes(b"")
    (gsv / "SoVITS_weights_v2Pro").mkdir(parents=True)
    (gsv / "SoVITS_weights_v2Pro" / "EXP01_e8_s248.pth").write_bytes(b"")
    wav_dir = gsv / "logs" / "EXP01" / "5-wav32k"
    wav_dir.mkdir(parents=True)
    wav = wav_dir / "sample1.wav"
    wav.write_bytes(b"WAV")
    (gsv / "logs" / "EXP01" / "2-name2text.txt").write_text(
        "sample1.wav\tph\tNone\t日本語のテキストです\n", encoding="utf-8"
    )

    char_dir = make_char_dir(tmp_path, "无预设角色")
    char = {**SAMPLE_CHAR, "name": "无预设角色", "recommended_settings": {}}
    assert char_dir.exists()
    mgr = CharManager(tmp_path)
    calls = []

    class FakeTTS:
        def set_gpt_weights(self, p):
            calls.append(("gpt", p))

        def set_sovits_weights(self, p):
            calls.append(("sovits", p))

        def set_refer_audio(self, p, t, lang):
            calls.append(("ref", p, t, lang))

    mgr.apply_preset(char, FakeTTS(), gsv_root=str(gsv))
    assert ("gpt", str(gsv / "GPT_weights_v2Pro" / "EXP01-e10.ckpt")) in calls
    assert ("sovits", str(gsv / "SoVITS_weights_v2Pro" / "EXP01_e8_s248.pth")) in calls
    ref_call = next(c for c in calls if c[0] == "ref")
    assert ref_call[1] == str(wav)  # 从训练日志推导参考音频
    assert ref_call[2] == "日本語のテキストです"
    assert ref_call[3] == "ja"  # 日文文本自动判定 ref_lang


def test_experiment_name_parsing():
    from modules.character_manager import CharManager

    assert CharManager._experiment_name("GPT_weights_v2Pro/EXP01-e10.ckpt") == "EXP01"
    assert CharManager._experiment_name("EXP01") == "EXP01"


# ---------- 章节九十二：角色聊天背景 ----------


def test_background_fixed_filename(tmp_path):
    char_dir = make_char_dir(tmp_path, "背景A")
    (char_dir / "background.png").write_bytes(b"\x89PNG fake")
    mgr = CharManager(tmp_path)
    char = mgr.get_character("背景A")
    assert char["_background"].endswith("background.png")


def test_background_field_priority_over_fixed(tmp_path):
    char_dir = make_char_dir(tmp_path, "背景B")
    (char_dir / "background.png").write_bytes(b"\x89PNG fixed")
    (char_dir / "bg_custom.jpg").write_bytes(b"JPG custom")
    jp = char_dir / "character.json"
    char = json.loads(jp.read_text(encoding="utf-8"))
    char["background"] = "bg_custom.jpg"
    jp.write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")
    mgr = CharManager(tmp_path)
    assert mgr.get_character("背景B")["_background"].endswith("bg_custom.jpg")


def test_background_ext_priority_order(tmp_path):
    char_dir = make_char_dir(tmp_path, "背景C")
    (char_dir / "background.gif").write_bytes(b"GIF89a")
    (char_dir / "background.png").write_bytes(b"\x89PNG")
    mgr = CharManager(tmp_path)
    # png 优先于 gif（按 png→jpg→jpeg→webp→gif 顺序）
    assert mgr.get_character("背景C")["_background"].endswith("background.png")


def test_background_unsafe_field_falls_back(tmp_path):
    char_dir = make_char_dir(tmp_path, "背景D")
    (char_dir / "background.webp").write_bytes(b"WEBP")
    jp = char_dir / "character.json"
    char = json.loads(jp.read_text(encoding="utf-8"))
    char["background"] = "../../config.json"
    jp.write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")
    mgr = CharManager(tmp_path)
    # 不安全路径字段被忽略，回落固定文件名
    assert mgr.get_character("背景D")["_background"].endswith("background.webp")


def test_background_missing_returns_empty(tmp_path):
    mgr = CharManager(tmp_path)
    assert mgr.get_character("不存在") is None


def test_update_background_valid(tmp_path):
    make_char_dir(tmp_path, "背景E")
    src = tmp_path / "upload.gif"
    src.write_bytes(b"GIF89a animated")
    mgr = CharManager(tmp_path)
    target = mgr.update_background("背景E", str(src))
    assert target.endswith("background.gif")
    assert Path(target).read_bytes() == b"GIF89a animated"


def test_update_background_too_large(tmp_path):
    make_char_dir(tmp_path, "背景F")
    src = tmp_path / "big.png"
    src.write_bytes(b"\x00" * (201 * 1024 * 1024))
    mgr = CharManager(tmp_path)
    try:
        with pytest.raises(ValueError, match="200MB"):
            mgr.update_background("背景F", str(src))
    finally:
        src.unlink(missing_ok=True)


def test_update_background_bad_format(tmp_path):
    make_char_dir(tmp_path, "背景G")
    src = tmp_path / "bad.txt"
    src.write_text("not image", encoding="utf-8")
    mgr = CharManager(tmp_path)
    with pytest.raises(ValueError, match="不支持"):
        mgr.update_background("背景G", str(src))
