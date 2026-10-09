"""ZzhClaw 命令行入口。"""

import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="zzhclaw",
        description="ZzhClaw - AI 编码助手",
    )
    parser.add_argument(
        "--mode",
        choices=["cli", "tui", "web"],
        default="tui",
        help="运行模式: cli (命令行), tui (终端界面), web (浏览器界面，默认 tui)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Web 模式监听地址 (默认 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Web 模式监听端口 (默认 8000)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Web 模式不自动打开浏览器"
    )
    args = parser.parse_args()

    if args.mode == "cli":
        from zzhclaw.coding.cli import run_cli
        run_cli()
    elif args.mode == "web":
        from zzhclaw.web import run_web
        run_web(host=args.host, port=args.port, open_browser=not args.no_browser)
    else:
        from zzhclaw.tui import run_tui
        run_tui()


if __name__ == "__main__":
    main()
