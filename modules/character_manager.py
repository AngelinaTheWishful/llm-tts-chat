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

REQUIRED_FILES = ["character.json"]
PORTRAIT_SIZE = (512, 512)
THUMB_SIZE = (64, 64)
DEFAULT_SANITIZE = "[^\\w\\u4e00-\\u9fff-]+"


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
                    for member in zf.namelist():
                        mp = Path(member)
                        if mp.is_absolute() or ".." in mp.parts:
                            warnings.append(f"跳过不安全路径: {member}")
                    zf.extractall(tmp)

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
        """
        rs = char.get("recommended_settings", {})
        if rs.get("gpt_model"):
            tts_client.set_gpt_weights(self._resolve_preset_path(rs["gpt_model"], gsv_root))
        if rs.get("sovits_model"):
            tts_client.set_sovits_weights(self._resolve_preset_path(rs["sovits_model"], gsv_root))
        if rs.get("ref_audio") and rs.get("ref_text") and rs.get("ref_language"):
            ref_audio = rs["ref_audio"]
            if not Path(ref_audio).is_absolute():
                char_dir = Path(char.get("_dir", ""))
                resolved = char_dir / ref_audio
                if resolved.exists():
                    ref_audio = str(resolved)
            tts_client.set_refer_audio(ref_audio, rs["ref_text"], rs["ref_language"])

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
