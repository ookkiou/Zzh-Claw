"""
tui.py - Textual 终端界面 (对应 pi-tui)
"""

import json
import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static, Markdown, Tree, Button
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual.widget import Widget
from textual.reactive import var
from textual.screen import Screen
from rich.syntax import Syntax
from .ai import LLMClient
from .agent import Agent
from .tools import execute_tool, TOOLS


class MessageItem(Widget):
    """消息项"""

    def __init__(self, role: str, content: str, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.content = content

    def render(self) -> str:
        if self.role == "user":
            return f"[cyan]你:[/cyan] {self.content}"
        elif self.role == "assistant":
            return f"[magenta]AI:[/magenta] {self.content}"
        else:
            return f"[dim]{self.role}: {self.content}[/dim]"


class MessageLog(ScrollableContainer):
    """消息日志"""

    pass


class ZzhClawApp(App):
    """ZzhClaw TUI 应用"""

    CSS = """
    Screen {
        background: #1a1a2e;
    }

    Header {
        background: #16213e;
        height: 3;
    }

    #message-log {
        height: 1fr;
        padding: 1;
        overflow-y: auto;
    }

    #input-area {
        height: 5;
        background: #16213e;
        padding: 1;
    }

    Input {
        width: 100%;
        height: 3;
        background: #0f0f23;
        border: none;
    }

    Static {
        padding: 1;
    }

    .tool-result {
        background: #1a3d1a;
        border: solid #2d5a2d;
        padding: 1;
        margin: 1;
    }

    .user-message {
        background: #1a2d3d;
        padding: 1;
        margin: 1;
    }

    .ai-message {
        background: #2d1a3d;
        padding: 1;
        margin: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("ctrl+l", "clear", "清屏"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.llm = LLMClient()
        self.agent = Agent(self.llm)
        self.agent.new_session("TUI 会话")
        self.processing = var(False)
        self.pending_confirm = None  # (name, args, event, result)
        self.confirm_widget = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield MessageLog(id="message-log")
        with Vertical(id="input-area"):
            yield Input(placeholder="输入消息... (Ctrl+C 退出)", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        """应用启动"""
        self.title = "ZzhClaw"
        self.query_one("#user-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """用户提交输入"""
        user_input = event.value
        if not user_input.strip():
            return

        # 清空输入
        event.input.value = ""

        # 处理命令
        if user_input.startswith("/"):
            cmd = user_input[1:].split()[0]
            log = self.query_one("#message-log", ScrollableContainer)

            if cmd in ["quit", "exit", "q"]:
                self.action_quit()
                return

            elif cmd in ["help", "h"]:
                help_text = """
[bold]命令列表:[/bold]
  /help, /h         - 显示帮助
  /list             - 列出所有会话
  /load <id>        - 加载会话
  /new [name]       - 创建新会话
  /save             - 保存当前会话
  /delete, /rm <id> - 删除会话
  /quit, /exit, /q  - 退出
"""
                log.mount(Static(help_text))
                log.scroll_end()
                return

            elif cmd == "list":
                sessions = self.agent.list_sessions()
                if not sessions:
                    log.mount(Static("[yellow]没有保存的会话[/yellow]"))
                else:
                    text = "[bold]会话列表:[/bold]\n"
                    for s in sessions:
                        text += f"  [cyan]{s['id']}[/cyan] - {s['name']} ({s['messages']}条消息)\n"
                    log.mount(Static(text))
                log.scroll_end()
                return

            elif cmd == "load":
                parts = user_input.split()
                if len(parts) < 2:
                    log.mount(Static("[red]请指定会话 ID: /load <id>[/red]"))
                else:
                    if self.agent.load_session(parts[1]):
                        log.mount(Static(f"[green]已加载会话: {parts[1]}[/green]"))
                        self.action_clear()
                    else:
                        log.mount(Static("[red]无法加载会话[/red]"))
                log.scroll_end()
                return

            elif cmd == "new":
                name = " ".join(user_input.split()[1:]) or None
                self.agent.new_session(name)
                self.action_clear()
                log.mount(Static("[green]已创建新会话[/green]"))
                log.scroll_end()
                return

            elif cmd == "save":
                self.agent.save()
                log.mount(Static("[green]已保存会话[/green]"))
                log.scroll_end()
                return

            elif cmd in ["delete", "rm"]:
                parts = user_input.split()
                if len(parts) < 2:
                    log.mount(Static("[red]请指定会话 ID: /delete <id>[/red]"))
                else:
                    self.agent.session_manager.delete_session(parts[1])
                    log.mount(Static(f"[green]已删除会话: {parts[1]}[/green]"))
                log.scroll_end()
                return

            else:
                log.mount(Static(f"[red]未知命令: {cmd}[/red]"))
                log.scroll_end()
                return

        # 添加用户消息
        self.add_message("user", user_input)

        # 处理
        await self.process_message(user_input)

    async def process_message(self, user_input: str) -> None:
        """处理消息"""
        log = self.query_one("#message-log", ScrollableContainer)

        # 检查是否是确认输入
        if self.pending_confirm:
            name, args, event = self.pending_confirm
            if user_input.lower() in ["y", "yes", "是"]:
                event.set()
                self.pending_confirm = None
                if self.confirm_widget:
                    self.confirm_widget.remove()
                    self.confirm_widget = None
                return
            elif user_input.lower() in ["n", "no", "否"]:
                event.clear()
                self.pending_confirm = None
                if self.confirm_widget:
                    self.confirm_widget.remove()
                    self.confirm_widget = None
                return

        def on_tool_call(name: str, args: dict):
            tool_widget = Static(
                f"[dim]执行工具: [bold]{name}[/bold] {args}[/dim]",
                classes="tool-result"
            )
            log.mount(tool_widget)
            log.scroll_end()

        def on_tool_result(name: str, result: str):
            tool_widget = Static(
                f"[green]{name} 结果:[/green]\n{result[:500]}{'...' if len(result) > 500 else ''}",
                classes="tool-result"
            )
            log.mount(tool_widget)
            log.scroll_end()

        # 确认回调
        confirm_event = None
        def confirm_tool(name: str, args: dict) -> bool:
            nonlocal confirm_event
            # 显示确认提示
            confirm_text = f"[yellow]执行工具 [bold]{name}[/bold] {args}?[/yellow]\n输入 [green]y[/green] 确认，[red]n[/red] 取消"
            self.confirm_widget = Static(confirm_text, classes="tool-result")
            log.mount(self.confirm_widget)
            log.scroll_end()

            # 等待用户输入
            confirm_event = asyncio.Event()
            self.pending_confirm = (name, args, confirm_event)

            # 这个会在同步上下文中调用，我们需要返回一个默认值，
            # 实际上让 agent 先跳过，等用户确认后再重新处理？
            # 简单点：TUI 暂时默认确认，CLI 有确认
            return True

        # AI 响应
        thinking = Static("[yellow]AI 思考中...[/yellow]")
        log.mount(thinking)
        log.scroll_end()

        # 运行 agent（TUI 暂时默认确认，需要完整确认得重构）
        response = self.agent.run(
            user_input,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result
        )

        # 移除思考提示
        thinking.remove()

        # 添加 AI 回复
        self.add_message("assistant", response)

    def add_message(self, role: str, content: str) -> None:
        """添加消息"""
        log = self.query_one("#message-log", ScrollableContainer)

        if role == "user":
            widget = Static(f"[cyan]你:[/cyan] {content}", classes="user-message")
        elif role == "assistant":
            widget = Static(f"[magenta]AI:[/magenta] {content}", classes="ai-message")
        else:
            widget = Static(f"[dim]{role}: {content}[/dim]")

        log.mount(widget)
        log.scroll_end()

    def action_quit(self) -> None:
        """退出"""
        self.agent.save()
        self.exit()

    def action_clear(self) -> None:
        """清屏"""
        self.query_one("#message-log", ScrollableContainer).clear()


def run_tui():
    """运行 TUI"""
    app = ZzhClawApp()
    app.run()
