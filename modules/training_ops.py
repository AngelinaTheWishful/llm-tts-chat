"""TrainingOps：GPT-SoVITS 训练结果打包/恢复 + 中间素材清理工具（章节八十二）。

功能：
- scan/inspect：枚举 logs/ 实验并生成产物清单
- pack：打包精简权重 + 全量 ckpt → gsv_training/archives/
- cleanup：校验归档 zip 存在后删除中间素材
- restore：解压权重到 gsv_training/restored/，可选写回 GPT-SoVITS 权重目录
- list_archives：列出归档
- detect_completed：检测疑似训练完成（自动提醒/全自动触发）
- find_restored / list_restored：角色系统联动

安全规则：
- 仅删除可再生成的中间产物
- 删除前必须存在对应归档 zip（校验通过才删）
- 全程记录 logs/app.log
"""

import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from modules.base_manager import BaseManager

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARCHIVE_DIR = PROJECT_ROOT / "gsv_training" / "archives"
DEFAULT_RESTORE_DIR = PROJECT_ROOT / "gsv_training" / "restored"

# 中间素材（可再生成，打包校验后可删除）
INTERMEDIATE_DIRS = ["3-bert", "4-cnhubert", "5-wav32k", "7-sv_cn", "eval"]
INTERMEDIATE_FILES = ["2-name2text.txt", "6-name2semantic.tsv"]

# 精简权重目录（对外使用）
GPT_WEIGHT_DIRS = [
    "GPT_weights",
    "GPT_weights_v2",
    "GPT_weights_v2Pro",
    "GPT_weights_v2ProPlus",
    "GPT_weights_v3",
    "GPT_weights_v4",
]
SOVITS_WEIGHT_DIRS = [
    "SoVITS_weights",
    "SoVITS_weights_v2",
    "SoVITS_weights_v2Pro",
    "SoVITS_weights_v2ProPlus",
    "SoVITS_weights_v3",
    "SoVITS_weights_v4",
]

# 全量训练 ckpt 子目录（logs/<实验名>/ 下）
S1_CKPT_SUBDIRS = [
    "logs_s1",
    "logs_s1_v2",
    "logs_s1_v2Pro",
    "logs_s1_v2ProPlus",
    "logs_s1_v3",
    "logs_s1_v4",
]
S2_CKPT_SUBDIRS = [
    "logs_s2",
    "logs_s2_v2",
    "logs_s2_v2Pro",
    "logs_s2_v2ProPlus",
    "logs_s2_v3",
    "logs_s2_v4",
]


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_size(num_bytes: float) -> str:
    """将字节数格式化为可读大小。"""
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


class TrainingOps(BaseManager):
    """训练产物扫描 / 打包 / 清理 / 恢复 / 归档管理。"""

    def __init__(self, gsv_root: str = "", archive_dir: str = "", restore_dir: str = ""):
        super().__init__("training")
        self.gsv_root = Path(gsv_root) if gsv_root else Path("")
        self.archive_dir = Path(archive_dir) if archive_dir else DEFAULT_ARCHIVE_DIR
        self.restore_dir = Path(restore_dir) if restore_dir else DEFAULT_RESTORE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.restore_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 扫描 ----------

    def scan_experiments(self) -> list[dict]:
        """枚举 logs/ 下实验，返回 [inspect_experiment(...), ...]。"""
        logs_dir = self.gsv_root / "logs"
        if not logs_dir.exists():
            return []
        experiments = []
        for exp_dir in sorted(logs_dir.iterdir()):
            if not exp_dir.is_dir():
                continue
            info = self.inspect_experiment(exp_dir.name)
            if info["has_results"] or info["intermediate_items"]:
                experiments.append(info)
        return experiments

    def inspect_experiment(self, experiment: str) -> dict:
        """生成单个实验的产物清单。"""
        exp_dir = self.gsv_root / "logs" / experiment
        info = {
            "experiment": experiment,
            "exp_dir": str(exp_dir),
            "exists": exp_dir.exists(),
            "intermediate_items": [],
            "intermediate_size": 0,
            "result_files": [],
            "results_size": 0,
            "has_results": False,
        }
        if not exp_dir.exists():
            return info

        # 中间素材
        for d in INTERMEDIATE_DIRS:
            p = exp_dir / d
            if p.exists():
                size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                info["intermediate_items"].append(str(p))
                info["intermediate_size"] += size
        for f in INTERMEDIATE_FILES:
            p = exp_dir / f
            if p.exists():
                info["intermediate_items"].append(str(p))
                info["intermediate_size"] += p.stat().st_size

        # 精简权重（GPT / SoVITS，文件名以实验名开头）
        for d in GPT_WEIGHT_DIRS:
            self._collect(
                dirpath=self.gsv_root / d,
                pattern=f"{experiment}-e*.ckpt",
                category="gpt",
                info=info,
            )
        for d in SOVITS_WEIGHT_DIRS:
            self._collect(
                dirpath=self.gsv_root / d,
                pattern=f"{experiment}_e*_s*.pth",
                category="sovits",
                info=info,
            )

        # 全量训练 ckpt
        for d in S1_CKPT_SUBDIRS:
            self._collect(dirpath=exp_dir / d / "ckpt", pattern="*.ckpt", category="s1", info=info)
        for d in S2_CKPT_SUBDIRS:
            for pattern in ["G_*.pth", "D_*.pth"]:
                self._collect(dirpath=exp_dir / d, pattern=pattern, category="s2", info=info)

        info["has_results"] = bool(info["result_files"])
        return info

    def _collect(self, dirpath: Path, pattern: str, category: str, info: dict) -> None:
        """收集匹配文件到 info['result_files']，记录相对 gsv_root 路径。"""
        if not dirpath.exists():
            return
        for f in sorted(dirpath.glob(pattern)):
            if not f.is_file():
                continue
            info["result_files"].append(
                {
                    "abs": str(f),
                    "rel": str(f.relative_to(self.gsv_root)),
                    "category": category,
                }
            )
            info["results_size"] += f.stat().st_size

    # ---------- 打包 ----------

    def preview_pack(self, experiment: str) -> dict:
        """打包预览（dry-run），不写入任何文件。"""
        return self.pack_experiment(experiment, dry_run=True)

    def pack_experiment(self, experiment: str, dry_run: bool = False) -> dict:
        """打包精简权重 + 全量 ckpt 为 zip 归档到 archive_dir。"""
        info = self.inspect_experiment(experiment)
        if not info["exists"]:
            return {"ok": False, "error": f"实验不存在: {experiment}"}
        if not info["has_results"]:
            return {"ok": False, "error": f"实验 {experiment} 无训练结果可打包"}
        if not self.gsv_root.exists():
            return {"ok": False, "error": f"GPT-SoVITS 路径不存在: {self.gsv_root}"}

        zip_path = self.archive_dir / f"{experiment}_{_now_stamp()}.zip"
        files = [r["abs"] for r in info["result_files"]]
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "experiment": experiment,
                "zip": str(zip_path),
                "files": files,
                "size": info["results_size"],
            }

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for r in info["result_files"]:
                zf.write(r["abs"], r["rel"])

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad = zf.testzip()
        except zipfile.BadZipFile as e:
            zip_path.unlink(missing_ok=True)
            self.log("error", f"zip 创建失败: {e}")
            return {"ok": False, "error": f"zip 创建失败: {e}"}
        if bad is not None:
            zip_path.unlink(missing_ok=True)
            self.log("error", f"zip 校验失败: {bad}")
            return {"ok": False, "error": f"zip 校验失败: {bad}"}

        self.log(
            "info",
            f"打包完成: {zip_path}（{len(files)} 文件，{format_size(info['results_size'])}）",
        )
        return {
            "ok": True,
            "experiment": experiment,
            "zip": str(zip_path),
            "files": files,
            "size": info["results_size"],
        }

    # ---------- 清理 ----------

    def cleanup_intermediates(
        self, experiment: str, require_archive: bool = True, dry_run: bool = False
    ) -> dict:
        """校验归档 zip 存在后删除中间素材。"""
        info = self.inspect_experiment(experiment)
        items = info["intermediate_items"]
        if not items:
            return {"ok": True, "message": "无中间素材可清理", "cleaned": 0}
        if require_archive and not self.has_archive(experiment):
            return {"ok": False, "error": f"缺少 {experiment} 的归档 zip，拒绝清理（安全规则）"}
        if dry_run:
            return {"ok": True, "dry_run": True, "experiment": experiment, "files": items}

        cleaned = 0
        for p in items:
            target = Path(p)
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
                cleaned += 1
            except OSError as e:
                self.log("warning", f"清理失败 {p}: {e}")
        self.log("info", f"中间素材清理完成: {experiment}（{cleaned} 项）")
        return {"ok": True, "experiment": experiment, "cleaned": cleaned, "files": items}

    # ---------- 恢复 ----------

    def restore_archive(
        self, zip_path: str, write_back: bool = False, dry_run: bool = False
    ) -> dict:
        """从归档 zip 解压权重到 restore_dir/<实验名>/，可选写回权重目录。"""
        zip_path = Path(zip_path)
        if not zip_path.exists():
            return {"ok": False, "error": f"归档不存在: {zip_path}"}

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if not names:
                return {"ok": False, "error": "空归档 zip"}
            for n in names:
                p = Path(n)
                if p.is_absolute() or ".." in p.parts:
                    return {"ok": False, "error": f"归档含不安全路径: {n}"}

        # 实验名从 zip 文件名解析：<实验名>_YYYYMMDD_HHMMSS.zip
        match = re.match(r"^(.*)_\d{8}_\d{6}$", zip_path.stem)
        experiment = match.group(1) if match else zip_path.stem

        dest = self.restore_dir / experiment
        if dry_run:
            return {"ok": True, "dry_run": True, "experiment": experiment, "dest": str(dest)}

        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)

        written_back = []
        if write_back:
            root_res = self.gsv_root.resolve()
            with zipfile.ZipFile(zip_path, "r") as zf:
                for n in zf.namelist():
                    rel = Path(n)
                    target = (self.gsv_root / rel).resolve()
                    if not str(target).startswith(str(root_res)):
                        self.log("warning", f"跳过越界写回: {n}")
                        continue
                    source = dest / rel
                    if not source.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    written_back.append(str(target))

        self.log("info", f"归档已恢复: {experiment} → {dest}（写回 {len(written_back)} 文件）")
        return {
            "ok": True,
            "experiment": experiment,
            "dest": str(dest),
            "written_back": written_back,
        }

    # ---------- 归档查询 ----------

    def has_archive(self, experiment: str) -> bool:
        """判断实验是否存在对应归档 zip。"""
        return bool(list(self.archive_dir.glob(f"{experiment}_*.zip")))

    def list_archives(self) -> list[dict]:
        """列出归档 zip 及大小。"""
        if not self.archive_dir.exists():
            return []
        return [
            {
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "size_text": format_size(f.stat().st_size),
            }
            for f in sorted(self.archive_dir.glob("*.zip"), reverse=True)
        ]

    # ---------- 自动检测 ----------

    def _scan_result_files_lite(self, experiment: str) -> list[dict]:
        """轻量扫描：仅枚举结果文件路径与 mtime，不计算任何大小（R9）。

        避免自动检测每 60s 触发时对中间素材目录做全量 rglob 统计大小。
        """
        exp_dir = self.gsv_root / "logs" / experiment
        results: list[dict] = []
        for d in GPT_WEIGHT_DIRS:
            self._collect_lite(self.gsv_root / d, f"{experiment}-e*.ckpt", "gpt", results)
        for d in SOVITS_WEIGHT_DIRS:
            self._collect_lite(self.gsv_root / d, f"{experiment}_e*_s*.pth", "sovits", results)
        for d in S1_CKPT_SUBDIRS:
            self._collect_lite(exp_dir / d / "ckpt", "*.ckpt", "s1", results)
        for d in S2_CKPT_SUBDIRS:
            for pattern in ["G_*.pth", "D_*.pth"]:
                self._collect_lite(exp_dir / d, pattern, "s2", results)
        return results

    @staticmethod
    def _collect_lite(dirpath: Path, pattern: str, category: str, results: list[dict]) -> None:
        if not dirpath.exists():
            return
        for f in sorted(dirpath.glob(pattern)):
            if not f.is_file():
                continue
            results.append({"abs": str(f), "category": category, "mtime": f.stat().st_mtime})

    def detect_completed(self, idle_minutes: int = 10) -> list[dict]:
        """检测疑似训练完成：存在全量 ckpt 且 idle_minutes 分钟未更新（轻量扫描 R9）。"""
        now = time.time()
        completed = []
        logs_dir = self.gsv_root / "logs"
        if not logs_dir.exists():
            return []
        for exp_dir in sorted(logs_dir.iterdir()):
            if not exp_dir.is_dir():
                continue
            results = self._scan_result_files_lite(exp_dir.name)
            s1s2 = [r for r in results if r["category"] in ("s1", "s2")]
            if not s1s2:
                continue
            newest = max(r["mtime"] for r in s1s2)
            if (now - newest) >= idle_minutes * 60:
                size = sum(
                    Path(r["abs"]).stat().st_size for r in results if Path(r["abs"]).exists()
                )
                completed.append(
                    {
                        "experiment": exp_dir.name,
                        "results_size": size,
                        "size_text": format_size(size),
                        "has_archive": self.has_archive(exp_dir.name),
                    }
                )
        return completed

    # ---------- 角色系统联动 ----------

    def list_restored(self) -> list[str]:
        """列出 restore_dir 下已恢复的实验名。"""
        if not self.restore_dir.exists():
            return []
        return sorted(d.name for d in self.restore_dir.iterdir() if d.is_dir())

    def find_restored_weights(self, experiment: str) -> dict:
        """在 restore_dir/<实验名>/ 下查找 gpt/sovits 权重绝对路径。"""
        root = self.restore_dir / experiment
        gpt = ""
        sovits = ""
        if root.exists():
            for f in root.rglob("*.ckpt"):
                if f.is_file():
                    gpt = str(f)
                    break
            for f in root.rglob("*.pth"):
                if f.is_file():
                    sovits = str(f)
                    break
        return {"gpt": gpt, "sovits": sovits}
