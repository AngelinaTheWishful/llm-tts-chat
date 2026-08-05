"""一键启动报告 CLI 入口（章节八十九/九十）。

供 go-llm-tts.bat 调用：
    python -m modules.report_cli <report> <status> <step> [--detail ...] [--code ...]

独立于 reporter.py：避免 `python -m modules.reporter` 时被包 __init__ 桶式导入
先加载导致 sys.modules RuntimeWarning（cosmetic，但会污染一键启动控制台）。
"""

import sys

from modules.reporter import _cli

if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
