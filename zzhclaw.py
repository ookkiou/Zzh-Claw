#!/usr/bin/env python3
"""ZzhClaw - 入口文件"""

import sys
import argparse


def main():
    parser = argparse.ArgumentParser(description="ZzhClaw - AI 编码助手")
    parser.add_argument(
        "--mode",
        choices=["cli", "tui"],
        default="tui",
        help="运行模式: cli (命令行) 或 tui (终端界面，默认)"
    )
    args = parser.parse_args()

    if args.mode == "cli":
        from zzhclaw.cli import run_cli
        run_cli()
    else:
        from zzhclaw.tui import run_tui
        run_tui()


if __name__ == "__main__":
    main()
