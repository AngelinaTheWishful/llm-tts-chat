"""CharManager：角色管理（章节五 5.4 / 二十六 / 三十二）。

- 内置角色 + 外部注册角色合并
- 角色文件夹验证 / 头像处理 / 导入导出（zip）
- 删除移入回收站 trash/characters/
"""

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from modules.base_manager import BaseManager
from modules.card_importer import (
    card_to_avatar_png,
    normalize_to_character,
    parse_cards,
)

REQUIRED_FILES = ["character.json"]
PORTRAIT_SIZE = (512, 512)
THUMB_SIZE = (64, 64)
DEFAULT_SANITIZE = "[^\\w\\u4e00-\\u9fff-]+"

# 默认权重扫描目录（与 tts_client.GSV_SCAN_DIRS_* 保持一致，供无音色预设角色回退）
_GSV_SCAN_DIRS_GPT = [
    "GPT_weights",
    "GPT_weights_v2",
    "GPT_weights_v2Pro",
    "GPT_weights_v2ProPlus",
    "GPT_weights_v3",
    "GPT_weights_v4",
]
_GSV_SCAN_DIRS_SOVITS = [
    "SoVITS_weights",
    "SoVITS_weights_v2",
    "SoVITS_weights_v2Pro",
    "SoVITS_weights_v2ProPlus",
    "SoVITS_weights_v3",
    "SoVITS_weights_v4",
]


class CharManager(BaseManager):
    """角色管理。"""

    def __init__(
        self, chars_dir: str | Path, config_manager=None, trash_dir: str | Path | None = None
    ):
        super().__init__("character")
        self.dir = Path(chars_dir)
        self.dir.mkdir(exist_ok=True)
        self.config_mgr = config_manager
        self.trash_dir = (
            Path(trash_dir) if trash_dir else (self.dir.parent / "trash" / "characters")
        )

    # ---------- 列表与读取 ----------

    def list_characters(self) -> list[dict]:
        """合并内置角色 + 外部注册角色，返回角色配置列表。"""
        characters: list[dict] = []

        for char_dir in sorted(self.dir.iterdir()):
            if char_dir.is_dir():
                char = self._load_character_dir(char_dir)
                if char:
                    characters.append(char)

        if self.config_mgr:
            for ext in self.config_mgr.get("external_characters", []):
                ext_path = Path(ext.get("path", ""))
                if ext_path.exists():
                    char = self._load_character_dir(ext_path)
                    if char:
                        characters.append(char)

        return characters

    def list_names(self) -> list[str]:
        """返回角色名列表。"""
        return [c.get("name", "") for c in self.list_characters()]

    def get_character(self, name: str) -> dict | None:
        """按名称加载角色配置。"""
        for char_dir in self._iter_all_dirs():
            char = self._load_character_dir(char_dir)
            if char and char.get("name") == name:
                return char
        return None

    def get_character_dir(self, name: str) -> Path | None:
        """按名称返回角色文件夹路径。"""
        for char_dir in self._iter_all_dirs():
            char = self._load_character_dir(char_dir)
            if char and char.get("name") == name:
                return char_dir
        return None

    def _iter_all_dirs(self):
        """迭代内置 + 外部角色文件夹。"""
        if self.dir.exists():
            yield from (d for d in self.dir.iterdir() if d.is_dir())
        if self.config_mgr:
            for ext in self.config_mgr.get("external_characters", []):
                ext_path = Path(ext.get("path", ""))
                if ext_path.exists():
                    yield ext_path

    def _load_character_dir(self, char_dir: Path) -> dict | None:
        json_path = char_dir / "character.json"
        if not json_path.exists():
            return None
        try:
            char = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.log("error", f"角色配置解析失败: {char_dir}")
            return None

        char.setdefault("name", char_dir.name)
        char["_dir"] = str(char_dir)
        char["_portrait"] = self._resolve_file(char_dir, "portrait.png")
        char["_portrait_thumb"] = self._resolve_file(char_dir, "portrait_thumb.png")
        char["_ref_audio"] = self._resolve_file(char_dir, "ref.wav")
        char["_greeting_audio"] = self._resolve_file(char_dir, "greeting.wav")
        char["_voice_sample"] = self._resolve_file(char_dir, "voice_sample.wav")
        return char

    @staticmethod
    def _resolve_file(char_dir: Path, filename: str) -> str:
        path = char_dir / filename
        return str(path) if path.exists() else ""

    # ---------- 保存 / 删除 ----------

    def save_character(self, char: dict) -> None:
        """保存/更新角色配置（写入 character.json）。"""
        char_dir = self.get_character_dir(char.get("name", ""))
        if not char_dir:
            char_dir = self.dir / self._sanitize_name(char.get("name", "角色"))
        char_dir.mkdir(parents=True, exist_ok=True)

        json_path = char_dir / "character.json"
        json_path.write_text(
            json.dumps(char, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.log("info", f"角色已保存: {char.get('name')}")

    def delete_character(self, name: str) -> bool:
        """删除角色（移至回收站）。"""
        char_dir = self.get_character_dir(name)
        if not char_dir:
            return False

        target = self.trash_dir / f"{self._sanitize_name(name)}_deleted_{_now_stamp()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(char_dir), str(target))
        self.log("info", f"角色已删除（移入回收站）: {name}")
        return True

    # ---------- 导入 / 导出 ----------

    def export_character(self, name: str) -> str | None:
        """导出角色为 zip 包，返回路径。"""
        char_dir = self.get_character_dir(name)
        if not char_dir:
            return None

        exports_dir = self.dir.parent / "exports"
        exports_dir.mkdir(exist_ok=True)
        zip_path = exports_dir / f"{self._sanitize_name(name)}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in char_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(char_dir))

        return str(zip_path)

    def import_character(self, source: str | Path) -> list[str]:
        """导入角色（文件夹或 zip 路径），返回警告列表。

        - 文件夹：source 即角色文件夹（含 character.json）
        - zip：解压到临时目录，自动定位 character.json 并按其 name 建目录
        """
        source = Path(source)
        warnings: list[str] = []

        if source.is_dir():
            name = self._sanitize_name(source.name)
            target = self.dir / name
            if target.exists():
                warnings.append(f"目标角色已存在: {name}（需由调用方处理冲突）")
                return warnings
            shutil.copytree(str(source), str(target))
        elif source.is_file() and source.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                with zipfile.ZipFile(source, "r") as zf:
                    names = zf.namelist()
                    if not names:
                        warnings.append("导入包为空 zip")
                        return warnings
                    # zip 炸弹防护：成员数 / 总解压大小 / 单文件大小上限
                    info_list = zf.infolist()
                    total_size = sum(i.file_size for i in info_list)
                    if len(names) > 1000:
                        warnings.append("导入包成员数超过 1000，已拒绝")
                        return warnings
                    if total_size > 500 * 1024 * 1024:
                        warnings.append("导入包解压总大小超过 500MB，已拒绝")
                        return warnings
                    if any(i.file_size > 100 * 1024 * 1024 for i in info_list):
                        warnings.append("导入包存在超过 100MB 的单文件，已拒绝")
                        return warnings
                    # zip-slip：逐成员校验，仅解压安全路径，恶意成员直接跳过
                    for info in info_list:
                        mp = Path(info.filename)
                        if info.is_dir() or mp.is_absolute() or ".." in mp.parts:
                            warnings.append(f"跳过不安全路径: {info.filename}")
                            continue
                        try:
                            zf.extract(info, tmp)
                        except Exception as e:  # noqa: BLE001
                            warnings.append(f"解压失败已跳过: {info.filename}: {e}")
                            continue
                    # 解压后再次确认所有落盘文件都在临时目录内（防御双保险），越界文件直接删除
                    for f in tmp.rglob("*"):
                        if f.is_file() and not str(f.resolve()).startswith(str(tmp.resolve())):
                            warnings.append(f"已删除解压越界文件: {f}")
                            try:
                                f.unlink(missing_ok=True)
                            except OSError:
                                pass

                char_json = tmp / "character.json"
                if not char_json.exists():
                    candidates = list(tmp.rglob("character.json"))
                    char_json = candidates[0] if candidates else None
                if char_json is None:
                    warnings.append("导入包中未找到 character.json")
                    return warnings

                try:
                    char_name = json.loads(char_json.read_text(encoding="utf-8")).get("name", "")
                except (json.JSONDecodeError, OSError):
                    char_name = ""
                name = self._sanitize_name(char_name or char_json.parent.name)

                target = self.dir / name
                if target.exists():
                    warnings.append(f"目标角色已存在: {name}（需由调用方处理冲突）")
                    return warnings
                shutil.copytree(str(char_json.parent), str(target))
        else:
            raise ValueError(f"不支持的导入来源: {source}")

        warnings.extend(self.validate_package(name))
        return warnings

    def import_card(self, source: str | Path) -> tuple[list[str], list[str]]:
        """导入角色卡（TavernAI/RisuAI/Chub/CAI，章节六十九~七十一）。

        返回 (成功导入的角色名列表, 警告列表)。
        """
        source = Path(source)
        cards, png_avatar, parse_warnings = parse_cards(source)
        warnings: list[str] = list(parse_warnings)
        imported: list[str] = []

        for idx, card in enumerate(cards):
            character = normalize_to_character(card)
            name = character["name"]
            # 同名冲突：追加后缀
            if (self.dir / self._sanitize_name(name)).exists():
                suffix = f"_{idx}" if len(cards) > 1 else "_2"
                name = f"{name}{suffix}"
                character["name"] = name

            char_dir = self.dir / self._sanitize_name(name)
            char_dir.mkdir(parents=True, exist_ok=True)
            (char_dir / "character.json").write_text(
                json.dumps(character, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 头像：PNG 卡使用图片本身；JSON 卡提取内嵌头像
            avatar = card_to_avatar_png(card, png_avatar if (png_avatar and idx == 0) else None)
            if avatar:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                    tf.write(avatar)
                    tmp_path = tf.name
                try:
                    self.update_portrait(name, tmp_path)
                except Exception as e:
                    warnings.append(f"{name} 头像处理失败: {e}")
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
            else:
                warnings.append(f"{name} 无头像数据（可稍后在编辑中上传）")

            imported.append(name)
            self.log("info", f"角色卡已导入: {name}")

        if not imported:
            warnings.append("未导入任何角色")
        return imported, warnings

    def validate_package(self, name: str) -> list[str]:
        """验证角色文件夹完整性，返回警告列表。"""
        warnings: list[str] = []
        char_dir = self.get_character_dir(name)
        if not char_dir:
            warnings.append(f"角色不存在: {name}")
            return warnings

        for f in REQUIRED_FILES:
            if not (char_dir / f).exists():
                warnings.append(f"缺少必要文件: {f}")
        if not (char_dir / "portrait.png").exists():
            warnings.append("缺少头像文件，将使用默认头像")

        return warnings

    # ---------- 头像处理 ----------

    def update_portrait(self, name: str, upload_path: str) -> dict:
        """处理上传头像：1:1 居中裁切 + 缩放 + 转 PNG，返回 {main, thumb}。"""
        char_dir = self.get_character_dir(name)
        if not char_dir:
            raise FileNotFoundError(f"角色不存在: {name}")

        # Q6：限制上传图片大小（≤80MB），防止超大图片耗尽内存
        upload = Path(upload_path)
        if upload.is_file() and upload.stat().st_size > 80 * 1024 * 1024:
            raise ValueError("上传图片超过 80MB 限制，请压缩后重试")

        img = Image.open(upload_path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        min_side = min(img.size)
        left = (img.width - min_side) // 2
        top = (img.height - min_side) // 2
        img_cropped = img.crop((left, top, left + min_side, top + min_side))

        main_path = char_dir / "portrait.png"
        img_cropped.resize(PORTRAIT_SIZE, Image.LANCZOS).save(main_path, "PNG")

        thumb_path = char_dir / "portrait_thumb.png"
        img_cropped.resize(THUMB_SIZE, Image.LANCZOS).save(thumb_path, "PNG")

        return {"main": str(main_path), "thumb": str(thumb_path)}

    # ---------- 角色预设应用 ----------

    def apply_preset(self, char: dict, tts_client, gsv_root: str = "") -> None:
        """自动加载角色预设的模型和参考音频。

        - 模型路径若为相对路径，尝试按 gsv_root 解析
        - 参考音频相对路径按角色目录解析
        - 角色无预设（或预设缺参考音频）时，回退到训练实验的默认权重与参考音频，
          保证 TTS 可用（v1.1.4）
        """
        rs = char.get("recommended_settings", {})
        gpt = rs.get("gpt_model", "")
        sovits = rs.get("sovits_model", "")

        resolved_gpt = ""
        resolved_sovits = ""
        if gpt:
            resolved_gpt = self._resolve_preset_path(gpt, gsv_root)
            tts_client.set_gpt_weights(resolved_gpt)
        else:
            resolved_gpt = self._first_scan_model(gsv_root, _GSV_SCAN_DIRS_GPT, "*.ckpt")
            if resolved_gpt:
                tts_client.set_gpt_weights(resolved_gpt)
        if sovits:
            resolved_sovits = self._resolve_preset_path(sovits, gsv_root)
            tts_client.set_sovits_weights(resolved_sovits)
        else:
            resolved_sovits = self._first_scan_model(gsv_root, _GSV_SCAN_DIRS_SOVITS, "*.pth")
            if resolved_sovits:
                tts_client.set_sovits_weights(resolved_sovits)

        ref_audio = rs.get("ref_audio", "")
        ref_text = rs.get("ref_text", "")
        ref_lang = rs.get("ref_language", "")
        if not (ref_audio and ref_text):
            # 从训练实验日志推导参考音频（5-wav32k 首条 + 2-name2text.txt 文本）
            exp = self._experiment_name(resolved_gpt or resolved_sovits)
            ref_audio, ref_text = self._exp_ref_audio(gsv_root, exp)
            if ref_text and any("\u3040" <= ch <= "\u30ff" for ch in ref_text):
                ref_lang = "ja"
        if ref_audio and ref_text:
            if not Path(ref_audio).is_absolute():
                char_dir = Path(char.get("_dir", ""))
                resolved = char_dir / ref_audio
                if resolved.exists():
                    ref_audio = str(resolved)
            tts_client.set_refer_audio(ref_audio, ref_text, ref_lang or "zh")

    @staticmethod
    def _first_scan_model(gsv_root: str, scan_dirs: list[str], pattern: str) -> str:
        """扫描 gsv_root 下权重目录，返回第一个匹配文件。"""
        root = Path(gsv_root)
        for d in scan_dirs:
            target = root / d
            if target.exists():
                matches = sorted(target.glob(pattern))
                if matches:
                    return str(matches[0])
        return ""

    @staticmethod
    def _experiment_name(weights_path: str) -> str:
        """从权重文件名解析实验名（如 suomiKP31_EXP_01-e10.ckpt → suomiKP31_EXP_01）。"""
        stem = Path(weights_path).stem
        m = re.match(r"(.+?)-e\d+", stem)
        return m.group(1) if m else stem

    @staticmethod
    def _exp_ref_audio(gsv_root: str, exp_name: str) -> tuple[str, str]:
        """从训练实验日志推导参考音频：5-wav32k 首条 wav + 2-name2text.txt 对应文本。"""
        if not gsv_root or not exp_name:
            return "", ""
        logs = Path(gsv_root) / "logs" / exp_name
        wav_dir = logs / "5-wav32k"
        if not wav_dir.exists():
            return "", ""
        wavs = sorted(wav_dir.glob("*.wav"))
        if not wavs:
            return "", ""
        wav = str(wavs[0])
        text = ""
        name2text = logs / "2-name2text.txt"
        if name2text.exists():
            try:
                for line in name2text.read_text(encoding="utf-8").splitlines():
                    if line.startswith(wavs[0].name + "\t"):
                        parts = line.split("\t")
                        if len(parts) >= 4 and parts[3].strip():
                            text = parts[3].strip()
                        break
            except Exception:
                text = ""
        return wav, text

    @staticmethod
    def _resolve_preset_path(path: str, gsv_root: str) -> str:
        """相对路径按 gsv_root 解析，不存在则原样返回。"""
        p = Path(path)
        if p.is_absolute() or not gsv_root:
            return path
        candidate = Path(gsv_root) / path
        return str(candidate) if candidate.exists() else path

    # ---------- 工具 ----------

    @staticmethod
    def _sanitize_name(name: str) -> str:
        return re.sub(DEFAULT_SANITIZE, "_", name).strip("_") or "角色"


def _now_stamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")
