"""TrainingOps CLI 入口（章节八十二）：由 train_pack.bat 调用。

用法:
  python modules/training_cli.py list
  python modules/training_cli.py pack <实验名> [--dry-run] [--cleanup]
  python modules/training_cli.py cleanup <实验名> [--dry-run] [--no-require-archive]
  python modules/training_cli.py restore <zip> [--write-back] [--dry-run]
  python modules/training_cli.py list-archives
  python modules/training_cli.py detect [--idle-minutes N]

常用参数:
  --gsv-root DIR       GPT-SoVITS 根路径（覆盖 config.json）
  --archive-dir DIR    归档目录（覆盖 config.json）
  --restore-dir DIR    恢复目录（覆盖 config.json）
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.config_manager import ConfigManager  # noqa: E402
from modules.training_ops import TrainingOps, format_size  # noqa: E402


def _build_ops(args) -> TrainingOps:
    cfg = ConfigManager().get("gsv_training", {})
    return TrainingOps(
        gsv_root=args.gsv_root or cfg.get("gsv_root", ""),
        archive_dir=args.archive_dir or cfg.get("archive_dir", ""),
        restore_dir=args.restore_dir or cfg.get("restore_dir", ""),
    )


def _cmd_list(ops: TrainingOps) -> int:
    exps = ops.scan_experiments()
    if not exps:
        print("（无实验；请确认 --gsv-root 指向 GPT-SoVITS 根目录）")
        return 0
    print(f"{'实验名':<30} {'结果大小':>10} {'中间素材':>10}")
    for e in exps:
        print(
            f"{e['experiment']:<30} {format_size(e['results_size']):>10} "
            f"{format_size(e['intermediate_size']):>10}"
        )
    return 0


def _cmd_pack(ops: TrainingOps, args) -> int:
    result = ops.pack_experiment(args.experiment, dry_run=args.dry_run)
    if not result["ok"]:
        print(f"[ERROR] {result['error']}")
        return 1
    print(f"[OK] 打包完成: {result['zip']}")
    print(f"     文件数: {len(result['files'])}  大小: {format_size(result['size'])}")
    if args.cleanup and not args.dry_run:
        clean = ops.cleanup_intermediates(args.experiment)
        if clean["ok"]:
            print(f"[OK] 中间素材已清理: {clean.get('cleaned', 0)} 项")
        else:
            print(f"[WARN] 清理失败: {clean.get('error', '')}")
    return 0


def _cmd_cleanup(ops: TrainingOps, args) -> int:
    result = ops.cleanup_intermediates(
        args.experiment, require_archive=not args.no_require_archive, dry_run=args.dry_run
    )
    if not result["ok"]:
        print(f"[ERROR] {result['error']}")
        return 1
    if result.get("dry_run"):
        print(f"[OK] 预览清理 {len(result['files'])} 项（未执行）：")
    else:
        print(f"[OK] 已清理 {result.get('cleaned', 0)} 项：")
    for f in result.get("files", []):
        print(f"  - {f}")
    return 0


def _cmd_restore(ops: TrainingOps, args) -> int:
    result = ops.restore_archive(args.zip, write_back=args.write_back, dry_run=args.dry_run)
    if not result["ok"]:
        print(f"[ERROR] {result['error']}")
        return 1
    if result.get("dry_run"):
        print(f"[OK] 预览恢复: {result['dest']}（未执行）")
    else:
        print(f"[OK] 已恢复到: {result['dest']}")
        if result["written_back"]:
            print(f"     写回 {len(result['written_back'])} 个文件到 GPT-SoVITS")
    return 0


def _cmd_list_archives(ops: TrainingOps) -> int:
    archives = ops.list_archives()
    if not archives:
        print("（暂无归档）")
        return 0
    for a in archives:
        print(f"{a['name']}  {a['size_text']}")
    return 0


def _cmd_detect(ops: TrainingOps, args) -> int:
    completed = ops.detect_completed(idle_minutes=args.idle_minutes)
    if not completed:
        print("（未检测到疑似训练完成）")
        return 0
    for c in completed:
        state = "已归档" if c["has_archive"] else "未归档"
        print(f"{c['experiment']}  大小 {c['size_text']}  {state}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPT-SoVITS 训练结果打包/恢复 + 素材清理工具")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--gsv-root", default="", help="GPT-SoVITS 根路径（覆盖 config）")
    common.add_argument("--archive-dir", default="", help="归档目录（覆盖 config）")
    common.add_argument("--restore-dir", default="", help="恢复目录（覆盖 config）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", parents=[common], help="枚举 logs/ 实验")

    pack = sub.add_parser("pack", parents=[common], help="打包实验结果")
    pack.add_argument("experiment")
    pack.add_argument("--dry-run", action="store_true", help="仅预览")
    pack.add_argument("--cleanup", action="store_true", help="打包成功后清理中间素材")

    cleanup = sub.add_parser("cleanup", parents=[common], help="清理中间素材")
    cleanup.add_argument("experiment")
    cleanup.add_argument("--dry-run", action="store_true", help="仅预览")
    cleanup.add_argument("--no-require-archive", action="store_true", help="跳过归档校验")

    restore = sub.add_parser("restore", parents=[common], help="恢复归档")
    restore.add_argument("zip")
    restore.add_argument("--write-back", action="store_true", help="写回 GPT-SoVITS 权重目录")
    restore.add_argument("--dry-run", action="store_true", help="仅预览")

    sub.add_parser("list-archives", parents=[common], help="列出归档")

    detect = sub.add_parser("detect", parents=[common], help="检测疑似训练完成")
    detect.add_argument("--idle-minutes", type=int, default=10)

    args = parser.parse_args(argv)
    ops = _build_ops(args)

    if args.command == "list":
        return _cmd_list(ops)
    if args.command == "pack":
        return _cmd_pack(ops, args)
    if args.command == "cleanup":
        return _cmd_cleanup(ops, args)
    if args.command == "restore":
        return _cmd_restore(ops, args)
    if args.command == "list-archives":
        return _cmd_list_archives(ops)
    if args.command == "detect":
        return _cmd_detect(ops, args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
