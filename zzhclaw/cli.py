"""
cli.py - 命令行界面 (对应 coding-agent)
"""

import sys
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.table import Table
from rich import box
from .ai import LLMClient
from .agent import Agent

console = Console()


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


def run_cli():
    """运行命令行界面"""
    llm = LLMClient()
    agent = Agent(llm)

    console.print(Panel.fit(
        "[bold blue]ZzhClaw[/bold blue] - Python MVP (Step 3)\n"
        f"模型: [green]{llm.model}[/green]\n"
        "输入 /help 查看命令",
        border_style="blue"
    ))

    def on_tool_call(name: str, args: dict):
        console.print(f"\n[dim]执行工具: [bold]{name}[/bold] {args}[/dim]")

    def on_tool_result(name: str, result: str):
        if result:
            display = result[:500] + "..." if len(result) > 500 else result
            console.print(Panel(
                Syntax(display, "text", theme="monokai"),
                title=f"[green]{name} 结果[/green]",
                border_style="green"
            ))

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]你[/bold cyan]")

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

                else:
                    console.print(f"[red]未知命令: {cmd}[/red]")

                continue

            # 普通对话
            def confirm_tool(name: str, args: dict) -> bool:
                return Confirm.ask(f"[yellow]执行工具 [bold]{name}[/bold] {args}?[/yellow]", default=True)

            console.print("[bold green]AI 思考中...[/bold green]")
            response = agent.run(
                user_input,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                confirm_tool=confirm_tool
            )

            console.print("\n[bold magenta]AI[/bold magenta]")
            console.print(Markdown(response))

        except KeyboardInterrupt:
            console.print("\n[yellow]输入 /quit 退出[/yellow]")
        except Exception as e:
            console.print(f"[red]错误: {e}[/red]")
