"""
zzhclaw.cli - 命令行界面
"""

import sys
import os
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.table import Table
from rich import box
from rich.markup import escape as rich_escape
from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import prompt as pt_prompt
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from ...ai import LLMClient
from ...agent import Agent
from ...coding.tools import (
    set_cwd, get_cwd, set_sandbox,
    list_skills, load_skill, create_skill, get_skills_dirs,
)

console = Console()

# CLI 斜杠命令（用于自动补全）
CLI_COMMANDS = [
    "/help", "/list", "/load", "/new", "/save", "/fork",
    "/delete", "/cd", "/sandbox", "/permission", "/auto",
    "/skills", "/skill", "/quit",
]

# 权限模式中文描述
PERMISSION_MODE_DESC = {
    "confirm": "每个工具都确认",
    "smart": "只读工具自动，写/执行工具确认",
    "auto": "全自动，不再询问",
}


class SlashCommandCompleter(Completer):
    """只在输入以 / 开头且无空格时补全命令名（Tab 触发）"""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text:
            for cmd in CLI_COMMANDS:
                if cmd.startswith(text) and cmd != text:
                    yield Completion(cmd, start_position=-len(text))


def summarize_args(args: dict) -> str:
    """简化工具参数显示：长内容截断 + 转义换行，避免确认提示刷屏（README TODO）"""
    parts = []
    for k, v in args.items():
        sv = str(v).replace("\n", "\\n")
        if len(sv) > 60:
            sv = sv[:57] + f"...({len(str(v))}字符)"
        parts.append(f"{k}={sv!r}")
    return "{" + ", ".join(parts) + "}"


def _html_escape(text: str) -> str:
    """转义 HTML 特殊字符（prompt_toolkit HTML 用）"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def show_sessions(agent: Agent):
    """显示会话列表"""
    sessions = agent.list_sessions()
    if not sessions:
        console.print("[yellow]没有保存的会话[/yellow]")
        return

    table = Table(box=box.ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("名称", style="green")
    table.add_column("分支", style="yellow")
    table.add_column("消息", style="magenta")
    table.add_column("创建时间", style="dim")

    for s in sessions:
        table.add_row(
            s["id"],
            s["name"],
            str(s["branches"]),
            str(s["messages"]),
            s["created_at"][:16]
        )

    console.print(table)


def show_skills():
    """显示两级作用域的 skill 清单"""
    skills = list_skills()
    if not skills:
        dirs = "、".join(d["path"] for d in get_skills_dirs())
        console.print(f"[yellow]没有可用 skill[/yellow]（已扫描: {dirs}）")
        console.print("[dim]用 /skill new <name> 在项目里创建一个[/dim]")
        return
    table = Table(box=box.ROUNDED)
    table.add_column("名称", style="green")
    table.add_column("作用域", style="cyan")
    table.add_column("描述", style="white")
    for s in skills:
        table.add_row(s["name"], s["scope"], s["description"] or "（无描述）")
    console.print(table)


def run_cli():
    """运行命令行界面"""
    llm = LLMClient()
    agent = Agent(llm)

    # 输入会话：历史记录(↑↓翻) + 自动建议 + 斜杠命令补全(Tab)
    history_file = os.path.expanduser("~/.zzhclaw/history")
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    prompt_session = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
        completer=SlashCommandCompleter(),
    )

    console.print(Panel.fit(
        "[bold blue]ZzhClaw[/bold blue]\n"
        f"模型: [green]{llm.model}[/green] | 权限: [yellow]{agent.permission_mode}[/yellow]\n"
        "输入 /help 查看命令 | ↑↓ 翻历史 | Tab 补全命令 | /auto 一键全自动",
        border_style="blue"
    ))

    # 每次请求的 UI 状态（流式输出跟踪）
    ui_state = {"thinking": False, "stream_started": False}

    def clear_thinking():
        """清除\"AI 思考中...\"提示行（\r 回到行首 + \033[K 清到行尾）"""
        if ui_state["thinking"]:
            print("\r\033[K", end="", flush=True)
            ui_state["thinking"] = False

    def on_tool_call(name: str, args: dict):
        clear_thinking()
        # 多轮对话边界：工具调用前结束当前流式文本行，下轮 token 新建一行
        if ui_state["stream_started"]:
            print()
            ui_state["stream_started"] = False
        console.print(f"[dim]执行工具: [bold]{name}[/bold] {rich_escape(summarize_args(args))}[/dim]")

    def on_tool_result(name: str, result: str):
        clear_thinking()
        if result:
            display = result[:500] + "..." if len(result) > 500 else result
            console.print(Panel(
                Syntax(display, "text", theme="monokai"),
                title=f"[green]{name} 结果[/green]",
                border_style="green"
            ))

    def on_token(delta: str):
        """流式 token：第一个 token 清除思考中并打 AI 标签，后续直接追加"""
        clear_thinking()
        if not ui_state["stream_started"]:
            print("\033[35mAI\033[0m ", end="", flush=True)  # 洋红色 AI 标签
            ui_state["stream_started"] = True
        print(delta, end="", flush=True)

    while True:
        try:
            user_input = prompt_session.prompt(HTML('\n<ansicyan><b>你</b></ansicyan> '))

            if not user_input.strip():
                continue

            # 处理命令
            if user_input.startswith("/"):
                cmd = user_input[1:].split()[0]

                if cmd in ["quit", "exit", "q"]:
                    agent.save()
                    console.print("[yellow]再见！[/yellow]")
                    break

                elif cmd in ["help", "h"]:
                    console.print(Panel("""
[bold]命令列表:[/bold]
  /help, /h         - 显示帮助
  /list             - 列出所有会话
  /load <id>        - 加载会话
  /new [name]       - 创建新会话
  /save             - 保存当前会话
  /fork <index> <name> - 从某条消息分支
  /delete, /rm <id> - 删除会话
  /cd [path]        - 查看/切换工作目录
  /sandbox <on|off> - 开关写沙箱（限制写入工作目录内）
  /permission [mode] - 查看/切换权限模式 (confirm|smart|auto)
  /auto             - 一键切换全自动模式
  /skills           - 列出可用 skill（项目级+全局级）
  /skill new <name> [--global] - 创建 skill 模板
  /skill <name>     - 预览指定 skill 内容
  /quit, /exit, /q  - 退出
                    """, title="帮助"))

                elif cmd == "list":
                    show_sessions(agent)

                elif cmd == "load":
                    parts = user_input.split()
                    if len(parts) < 2:
                        console.print("[red]请指定会话 ID: /load <id>[/red]")
                        continue
                    if agent.load_session(parts[1]):
                        console.print(f"[green]已加载会话: {parts[1]}[/green]")
                    else:
                        console.print("[red]无法加载会话[/red]")

                elif cmd == "new":
                    name = " ".join(user_input.split()[1:]) or None
                    agent.new_session(name)
                    console.print("[green]已创建新会话[/green]")

                elif cmd == "save":
                    agent.save()
                    console.print("[green]已保存会话[/green]")

                elif cmd == "fork":
                    parts = user_input.split()
                    if len(parts) < 3:
                        console.print("[red]用法: /fork <消息索引> <分支名>[/red]")
                        continue
                    try:
                        idx = int(parts[1])
                        branch_name = " ".join(parts[2:])
                        agent.fork_branch(idx, branch_name)
                        console.print(f"[green]已创建分支: {branch_name}[/green]")
                    except Exception as e:
                        console.print(f"[red]错误: {e}[/red]")

                elif cmd in ["delete", "rm"]:
                    parts = user_input.split()
                    if len(parts) < 2:
                        console.print("[red]请指定会话 ID: /delete <id>[/red]")
                        continue
                    agent.session_manager.delete_session(parts[1])
                    console.print(f"[green]已删除会话: {parts[1]}[/green]")

                elif cmd == "cd":
                    parts = user_input.split(maxsplit=1)
                    if len(parts) < 2:
                        console.print(f"当前工作目录: [cyan]{get_cwd()}[/cyan]")
                    else:
                        result = set_cwd(parts[1].strip())
                        if result.startswith("错误"):
                            console.print(f"[red]{result}[/red]")
                        else:
                            console.print(f"[green]工作目录已切换: {result}[/green]")

                elif cmd == "sandbox":
                    parts = user_input.split()
                    if len(parts) < 2:
                        from ...coding.tools.registry import _WORKSPACE
                        state = "开启" if _WORKSPACE["sandbox"] else "关闭"
                        console.print(f"写沙箱当前: [cyan]{state}[/cyan]（用法: /sandbox on|off）")
                    elif parts[1].lower() in ("on", "true", "1"):
                        set_sandbox(True)
                        console.print("[green]写沙箱已开启：write_file 只能写工作目录内[/green]")
                    elif parts[1].lower() in ("off", "false", "0"):
                        set_sandbox(False)
                        console.print("[yellow]写沙箱已关闭：write_file 可写任意路径（谨慎）[/yellow]")
                    else:
                        console.print("[red]用法: /sandbox on|off[/red]")

                elif cmd in ["permission", "perm"]:
                    parts = user_input.split()
                    if len(parts) < 2:
                        cur = agent.permission_mode
                        console.print(f"当前权限模式: [cyan]{cur}[/cyan]（{PERMISSION_MODE_DESC[cur]}）")
                        console.print("[dim]用法: /permission confirm|smart|auto，或 /auto 一键全自动[/dim]")
                    else:
                        new_mode = parts[1].lower()
                        result = agent.set_permission_mode(new_mode)
                        if result == new_mode:
                            console.print(f"[green]权限模式已切换: {result}（{PERMISSION_MODE_DESC[result]}）[/green]")
                        else:
                            console.print(f"[red]无效模式: {new_mode}（可选 confirm|smart|auto），当前仍为 {result}[/red]")

                elif cmd == "auto":
                    agent.set_permission_mode("auto")
                    console.print("[green]✅ 已切换全自动模式：agent 将自主执行所有工具[/green]")
                    console.print("[dim]仍受危险命令黑名单 + 写沙箱保护；恢复逐个确认请输入 /permission confirm[/dim]")

                elif cmd == "skills":
                    show_skills()

                elif cmd == "skill":
                    parts = user_input.split()
                    if len(parts) >= 2 and parts[1].lower() == "new":
                        if len(parts) < 3:
                            console.print("[red]用法: /skill new <name> [--global][/red]")
                        else:
                            scope = "global" if "--global" in parts[3:] else "project"
                            ok, msg = create_skill(parts[2], scope)
                            console.print(f"[green]{msg}[/green]" if ok else f"[red]{msg}[/red]")
                    elif len(parts) >= 2:
                        console.print(Panel(
                            rich_escape(load_skill(parts[1])),
                            title=f"[cyan]skill: {parts[1]}[/cyan]",
                            border_style="cyan"
                        ))
                    else:
                        console.print("[dim]用法: /skills 列出 | /skill new <name> [--global] 创建 | /skill <name> 预览[/dim]")

                else:
                    console.print(f"[red]未知命令: {cmd}[/red]")

                continue

            # 普通对话
            def confirm_tool(name: str, args: dict) -> bool:
                clear_thinking()
                args_display = _html_escape(summarize_args(args))
                ans = pt_prompt(HTML(f'<ansiyellow>执行工具 <b>{name}</b> {args_display}? [Y/n]</ansiyellow> '))
                return ans.strip().lower() in ("", "y", "yes")

            # 重置流式状态，显示可被覆盖的"思考中"提示（\r 结尾不换行）
            ui_state["thinking"] = True
            ui_state["stream_started"] = False
            print("\r\033[32mAI 思考中...\033[0m", end="", flush=True)

            response = agent.run(
                user_input,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                confirm_tool=confirm_tool,
                on_token=on_token,
            )

            clear_thinking()
            if ui_state["stream_started"]:
                print()  # 流式输出完毕，换行
            else:
                # 纯工具调用无文本回复，用 Markdown 渲染完整响应
                console.print("[bold magenta]AI[/bold magenta]")
                console.print(Markdown(response))

        except KeyboardInterrupt:
            console.print("\n[yellow]输入 /quit 退出[/yellow]")
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")
