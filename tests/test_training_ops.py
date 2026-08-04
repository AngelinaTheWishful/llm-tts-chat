"""TrainingOps 单元测试（章节八十二）。"""

import os
import zipfile
from pathlib import Path

from modules.training_ops import TrainingOps, format_size


def _make_gsv(root: Path) -> Path:
    """构造虚拟 GPT-SoVITS 目录结构。"""
    gsv = root / "gsv"
    exp = gsv / "logs" / "suomiKP31_EXP_01"
    (exp / "3-bert").mkdir(parents=True)
    (exp / "5-wav32k").mkdir(parents=True)
    (exp / "logs_s1_v2Pro" / "ckpt").mkdir(parents=True)
    (exp / "logs_s2_v2Pro").mkdir(parents=True)
    (gsv / "GPT_weights_v2Pro").mkdir(parents=True)
    (gsv / "SoVITS_weights_v2Pro").mkdir(parents=True)

    (exp / "3-bert" / "a.npy").write_bytes(b"bert")
    (exp / "5-wav32k" / "a.wav").write_bytes(b"wav")
    (exp / "2-name2text.txt").write_text("t")
    (exp / "logs_s1_v2Pro" / "ckpt" / "epoch=1.ckpt").write_bytes(b"s1")
    (exp / "logs_s2_v2Pro" / "G_1.pth").write_bytes(b"s2")
    (exp / "logs_s2_v2Pro" / "D_1.pth").write_bytes(b"s2d")
    (gsv / "GPT_weights_v2Pro" / "suomiKP31_EXP_01-e1.ckpt").write_bytes(b"gpt")
    (gsv / "SoVITS_weights_v2Pro" / "suomiKP31_EXP_01_e1_s1.pth").write_bytes(b"sovits")
    return gsv


def _make_ops(tmp_path) -> tuple[TrainingOps, Path]:
    gsv = _make_gsv(tmp_path)
    ops = TrainingOps(
        gsv_root=str(gsv),
        archive_dir=str(tmp_path / "arch"),
        restore_dir=str(tmp_path / "rest"),
    )
    return ops, gsv


# ---------- 扫描 ----------


def test_scan_experiments_finds_exp(tmp_path):
    ops, _ = _make_ops(tmp_path)
    exps = ops.scan_experiments()
    assert len(exps) == 1
    assert exps[0]["experiment"] == "suomiKP31_EXP_01"
    assert exps[0]["has_results"] is True


def test_inspect_intermediates(tmp_path):
    ops, _ = _make_ops(tmp_path)
    info = ops.inspect_experiment("suomiKP31_EXP_01")
    assert len(info["intermediate_items"]) == 3
    assert info["intermediate_size"] > 0
    assert any("3-bert" in p for p in info["intermediate_items"])
    assert any("2-name2text.txt" in p for p in info["intermediate_items"])


def test_inspect_results(tmp_path):
    ops, _ = _make_ops(tmp_path)
    info = ops.inspect_experiment("suomiKP31_EXP_01")
    cats = {r["category"] for r in info["result_files"]}
    assert cats == {"gpt", "sovits", "s1", "s2"}
    rels = {r["rel"] for r in info["result_files"]}
    assert any("GPT_weights_v2Pro" in r for r in rels)
    assert any("logs_s1_v2Pro" in r for r in rels)
    assert any("logs_s2_v2Pro" in r for r in rels)


def test_inspect_missing_experiment(tmp_path):
    ops, _ = _make_ops(tmp_path)
    info = ops.inspect_experiment("不存在的实验")
    assert info["exists"] is False
    assert info["has_results"] is False


# ---------- 打包 ----------


def test_pack_creates_valid_zip(tmp_path):
    ops, _ = _make_ops(tmp_path)
    result = ops.pack_experiment("suomiKP31_EXP_01")
    assert result["ok"] is True
    zip_path = Path(result["zip"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path, "r") as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        # zip 内保留相对 gsv_root 路径
        assert any("GPT_weights_v2Pro" in n for n in names)
        assert any("logs/suomiKP31_EXP_01/logs_s2_v2Pro" in n for n in names)


def test_pack_dry_run_writes_nothing(tmp_path):
    ops, _ = _make_ops(tmp_path)
    result = ops.preview_pack("suomiKP31_EXP_01")
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert not Path(result["zip"]).exists()


def test_pack_no_results(tmp_path):
    ops, _ = _make_ops(tmp_path)
    result = ops.pack_experiment("不存在的实验")
    assert result["ok"] is False


def test_pack_files_in_archive_match(tmp_path):
    ops, _ = _make_ops(tmp_path)
    result = ops.pack_experiment("suomiKP31_EXP_01")
    assert len(result["files"]) == 5  # gpt + sovits + s1 + s2(2)


# ---------- 清理 ----------


def test_cleanup_requires_archive(tmp_path):
    ops, _ = _make_ops(tmp_path)
    result = ops.cleanup_intermediates("suomiKP31_EXP_01")
    assert result["ok"] is False
    assert "归档" in result["error"]


def test_cleanup_deletes_after_pack(tmp_path):
    ops, gsv = _make_ops(tmp_path)
    assert ops.pack_experiment("suomiKP31_EXP_01")["ok"] is True
    result = ops.cleanup_intermediates("suomiKP31_EXP_01")
    assert result["ok"] is True
    assert result["cleaned"] == 3
    exp = gsv / "logs" / "suomiKP31_EXP_01"
    assert not (exp / "3-bert").exists()
    assert not (exp / "2-name2text.txt").exists()
    # 全量 ckpt 保留
    assert (exp / "logs_s2_v2Pro" / "G_1.pth").exists()


def test_cleanup_dry_run(tmp_path):
    ops, gsv = _make_ops(tmp_path)
    assert ops.pack_experiment("suomiKP31_EXP_01")["ok"] is True
    result = ops.cleanup_intermediates("suomiKP31_EXP_01", dry_run=True)
    assert result["dry_run"] is True
    assert (gsv / "logs" / "suomiKP31_EXP_01" / "3-bert").exists()


# ---------- 恢复 ----------


def test_restore_extracts_to_restore_dir(tmp_path):
    ops, _ = _make_ops(tmp_path)
    zip_path = ops.pack_experiment("suomiKP31_EXP_01")["zip"]
    result = ops.restore_archive(zip_path)
    assert result["ok"] is True
    dest = Path(result["dest"])
    assert (dest / "GPT_weights_v2Pro" / "suomiKP31_EXP_01-e1.ckpt").exists()
    assert (dest / "logs" / "suomiKP31_EXP_01" / "logs_s2_v2Pro" / "G_1.pth").exists()


def test_restore_write_back(tmp_path):
    ops, gsv = _make_ops(tmp_path)
    zip_path = ops.pack_experiment("suomiKP31_EXP_01")["zip"]
    result = ops.restore_archive(zip_path, write_back=True)
    assert result["ok"] is True
    assert len(result["written_back"]) == 5
    assert (gsv / "GPT_weights_v2Pro" / "suomiKP31_EXP_01-e1.ckpt").exists()


def test_restore_rejects_unsafe_path(tmp_path):
    ops, _ = _make_ops(tmp_path)
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    result = ops.restore_archive(str(bad_zip))
    assert result["ok"] is False


# ---------- 归档 / 检测 / 联动 ----------


def test_has_archive_and_list_archives(tmp_path):
    ops, _ = _make_ops(tmp_path)
    assert ops.has_archive("suomiKP31_EXP_01") is False
    ops.pack_experiment("suomiKP31_EXP_01")
    assert ops.has_archive("suomiKP31_EXP_01") is True
    archives = ops.list_archives()
    assert len(archives) == 1
    assert archives[0]["size_text"]


def test_detect_completed(tmp_path):
    ops, _ = _make_ops(tmp_path)
    # 将全部 s1/s2 结果文件 mtime 改旧（detect_completed 取 max(mtime)，
    # 只改一个文件会让 newest 取到新建文件、与 now 竞态导致 flaky）
    exp = Path(tmp_path) / "gsv" / "logs" / "suomiKP31_EXP_01"
    old = 1000.0
    for p in exp.rglob("*"):
        if p.is_file() and p.suffix in (".pth", ".ckpt"):
            os.utime(p, (old, old))
    completed = ops.detect_completed(idle_minutes=0)
    assert any(c["experiment"] == "suomiKP31_EXP_01" for c in completed)


def test_find_restored_weights(tmp_path):
    ops, _ = _make_ops(tmp_path)
    zip_path = ops.pack_experiment("suomiKP31_EXP_01")["zip"]
    ops.restore_archive(zip_path)
    weights = ops.find_restored_weights("suomiKP31_EXP_01")
    assert weights["gpt"].endswith(".ckpt")
    assert weights["sovits"].endswith(".pth")


def test_list_restored(tmp_path):
    ops, _ = _make_ops(tmp_path)
    assert ops.list_restored() == []
    zip_path = ops.pack_experiment("suomiKP31_EXP_01")["zip"]
    ops.restore_archive(zip_path)
    assert ops.list_restored() == ["suomiKP31_EXP_01"]


# ---------- 工具 ----------


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024 * 155) == "155.0 MB"
    assert format_size(1024**3) == "1.0 GB"
