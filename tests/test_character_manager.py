"""CharManager 单元测试。"""

import json
import sys
from pathlib import Path

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
