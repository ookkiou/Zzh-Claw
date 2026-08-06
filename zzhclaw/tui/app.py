"""
zzhclaw.tui - Textual 终端界面
"""

import threading
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static
from textual.containers import ScrollableContainer, Vertical
from textual.widget import Widget
from textual.message import Message
from textual import work
from ..ai import LLMClient
from ..agent import Agent

# 工具名中英映射（用于界面显示）
TOOL_NAMES_ZH = {
    "read_file": "读取文件",
    "write_file": "写入文件",
    "run_bash": "执行命令",
    "web_search": "联网搜索",
    "fetch_webpage": "获取网页",
}


def _tool_name_zh(name: str) -> str:
    """把工具英文名转为中文显示名"""
    return TOOL_NAMES_ZH.get(name, name)


# 消息角色中英映射
ROLE_NAMES_ZH = {
    "user": "你",
    "assistant": "AI",
    "tool": "工具",
}


# ===== 跨线程消息（工作线程 → 主线程）=====
class ToolCallMsg(Message):
    """工作线程：通知主线程显示工具调用"""
    def __init__(self, name: str, args: dict) -> None:
        super().__init__()
        self.name = name
        self.args = args


class ToolResultMsg(Message):
    """工作线程：通知主线程显示工具结果"""
    def __init__(self, name: str, result: str) -> None:
        super().__init__()
        self.name = name
        self.result = result


class ConfirmRequestMsg(Message):
    """工作线程：请求用户确认工具执行"""
    def __init__(self, name: str, args: dict) -> None:
        super().__init__()
        self.name = name
        self.args = args


class AgentDoneMsg(Message):
    """工作线程：agent.run 完成"""
    def __init__(self, response: str) -> None:
        super().__init__()
        self.response = response


class AgentErrorMsg(Message):
    """工作线程：agent.run 出错"""
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


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
            role_zh = ROLE_NAMES_ZH.get(self.role, self.role)
            return f"[dim]{role_zh}: {self.content}[/dim]"


class MessageLog(ScrollableContainer):
    """消息日志"""

    pass


class ZzhClawApp(App):
    """ZzhClaw TUI 应用

    异步模型（Textual 原生 @work + post_message）：
      - agent.run 在 @work(thread=True) worker 线程里跑，不阻塞事件循环
      - 工作线程通过 post_message 把工具调用/结果/确认请求发回主线程
      - 主线程消息 handler（async）更新 UI（await mount）
      - 确认时工作线程阻塞在 threading.Event，用户按 y/n 后主线程 set 唤醒
    """

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
        ("y", "confirm_yes", "确认"),
        ("n", "confirm_no", "取消"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.llm = LLMClient()
        self.agent = Agent(self.llm)
        self.agent.new_session("TUI 会话")
        self.processing = False
        # 工具确认的跨线程同步：工作线程阻塞等待，主线程按键后唤醒
        self._confirm_event = threading.Event()
        self._confirm_result = False
        self._confirm_pending = None  # (name, args) 当前等待确认的工具
        self.confirm_widget = None
        self.thinking = None  # "AI 思考中..." 提示

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

        # 处理中时不接受新输入（避免并发跑多个 agent）
        if self.processing:
            await self._notify("[yellow]正在处理中,请稍候...[/yellow]")
            return

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
                await log.mount(Static(help_text))
                log.scroll_end()
                return

            elif cmd == "list":
                sessions = self.agent.list_sessions()
                if not sessions:
                    await log.mount(Static("[yellow]没有保存的会话[/yellow]"))
                else:
                    text = "[bold]会话列表:[/bold]\n"
                    for s in sessions:
                        text += f"  [cyan]{s['id']}[/cyan] - {s['name']} ({s['messages']}条消息)\n"
                    await log.mount(Static(text))
                log.scroll_end()
                return

            elif cmd == "load":
                parts = user_input.split()
                if len(parts) < 2:
                    await log.mount(Static("[red]请指定会话 ID: /load <id>[/red]"))
                else:
                    if self.agent.load_session(parts[1]):
                        await log.mount(Static(f"[green]已加载会话: {parts[1]}[/green]"))
                        self.action_clear()
                    else:
                        await log.mount(Static("[red]无法加载会话[/red]"))
                log.scroll_end()
                return

            elif cmd == "new":
                name = " ".join(user_input.split()[1:]) or None
                self.agent.new_session(name)
                self.action_clear()
                await log.mount(Static("[green]已创建新会话[/green]"))
                log.scroll_end()
                return

            elif cmd == "save":
                self.agent.save()
                await log.mount(Static("[green]已保存会话[/green]"))
                log.scroll_end()
                return

            elif cmd in ["delete", "rm"]:
                parts = user_input.split()
                if len(parts) < 2:
                    await log.mount(Static("[red]请指定会话 ID: /delete <id>[/red]"))
                else:
                    self.agent.session_manager.delete_session(parts[1])
                    await log.mount(Static(f"[green]已删除会话: {parts[1]}[/green]"))
                log.scroll_end()
                return

            else:
                await log.mount(Static(f"[red]未知命令: {cmd}[/red]"))
                log.scroll_end()
                return

        # 添加用户消息
        await self.add_message("user", user_input)
        # 启动 agent worker
        await self.process_message(user_input)

    async def process_message(self, user_input: str) -> None:
        """启动 agent worker（@work 在后台线程跑，不阻塞事件循环）"""
        log = self.query_one("#message-log", ScrollableContainer)
        self.thinking = Static("[yellow]AI 思考中...[/yellow]")
        await log.mount(self.thinking)
        log.scroll_end()
        self.processing = True
        self._set_input_placeholder("AI 处理中...")
        # 启动 worker（非阻塞，立即返回；结果通过消息回传）
        self.run_agent(user_input)

    @work(exclusive=True, thread=True)
    def run_agent(self, user_input: str) -> None:
        """工作线程：运行 agent.run（同步阻塞，但在 worker 线程不卡 UI）

        工具调用/结果/确认通过 post_message 发回主线程，主线程在消息 handler 里更新 UI。
        确认时工作线程阻塞在 _confirm_event，等主线程用户按 y/n 后唤醒。
        """
        def on_tool_call(name: str, args: dict):
            self.post_message(ToolCallMsg(name, args))

        def on_tool_result(name: str, result: str):
            self.post_message(ToolResultMsg(name, result))

        def confirm_tool(name: str, args: dict) -> bool:
            self.post_message(ConfirmRequestMsg(name, args))
            self._confirm_event.wait()
            self._confirm_event.clear()
            return self._confirm_result

        try:
            response = self.agent.run(
                user_input,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                confirm_tool=confirm_tool,
            )
            self.post_message(AgentDoneMsg(response or ""))
        except Exception as e:
            self.post_message(AgentErrorMsg(str(e)))

    # ===== 消息 handler（主线程，async，可 await mount）=====
    async def on_tool_call_msg(self, event: ToolCallMsg) -> None:
        await self._append_tool_call(event.name, event.args)

    async def on_tool_result_msg(self, event: ToolResultMsg) -> None:
        await self._append_tool_result(event.name, event.result)

    async def on_confirm_request_msg(self, event: ConfirmRequestMsg) -> None:
        await self._show_confirm_prompt(event.name, event.args)

    async def on_agent_done_msg(self, event: AgentDoneMsg) -> None:
        self._cleanup_after_agent()
        if event.response:
            await self.add_message("assistant", event.response)

    async def on_agent_error_msg(self, event: AgentErrorMsg) -> None:
        self._cleanup_after_agent()
        await self._notify(f"[red]处理出错: {event.error}[/red]")

    def _cleanup_after_agent(self) -> None:
        """主线程：agent 结束后清理"""
        if self.thinking:
            self.thinking.remove()
            self.thinking = None
        self.processing = False
        self._set_input_placeholder("输入消息... (Ctrl+C 退出)")

    async def _append_tool_call(self, name: str, args: dict) -> None:
        """主线程：追加工具调用提示"""
        log = self.query_one("#message-log", ScrollableContainer)
        await log.mount(Static(
            f"[dim]执行工具: [bold]{_tool_name_zh(name)}[/bold] {args}[/dim]",
            classes="tool-result"
        ))
        log.scroll_end()

    async def _append_tool_result(self, name: str, result: str) -> None:
        """主线程：追加工具结果"""
        log = self.query_one("#message-log", ScrollableContainer)
        await log.mount(Static(
            f"[green]{_tool_name_zh(name)} 结果:[/green]\n{result[:500]}{'...' if len(result) > 500 else ''}",
            classes="tool-result"
        ))
        log.scroll_end()

    async def _show_confirm_prompt(self, name: str, args: dict) -> None:
        """主线程：显示工具确认提示，等待用户按 y/n"""
        log = self.query_one("#message-log", ScrollableContainer)
        self._confirm_pending = (name, args)
        self._confirm_result = False
        self.confirm_widget = Static(
            f"[yellow]执行工具 [bold]{_tool_name_zh(name)}[/bold] {args}?[/yellow]\n"
            f"[bold green](按 y 确认 / n 取消)[/bold green]",
            classes="tool-result"
        )
        await log.mount(self.confirm_widget)
        log.scroll_end()
        # 禁用输入框（按 y/n 触发 BINDINGS，不进输入框）
        self.query_one("#user-input", Input).disabled = True

    def action_confirm_yes(self) -> None:
        """按键 y 确认工具执行"""
        if self._confirm_pending is None:
            return
        self._confirm_result = True
        self._finish_confirm()

    def action_confirm_no(self) -> None:
        """按键 n 取消工具执行"""
        if self._confirm_pending is None:
            return
        self._confirm_result = False
        self._finish_confirm()

    def _finish_confirm(self) -> None:
        """主线程：清理确认提示，恢复输入框，唤醒工作线程"""
        if self.confirm_widget:
            self.confirm_widget.remove()
            self.confirm_widget = None
        self._confirm_pending = None
        self._set_input_placeholder("AI 处理中...")
        inp = self.query_one("#user-input", Input)
        inp.disabled = False
        inp.focus()
        # 唤醒工作线程
        self._confirm_event.set()

    async def _notify(self, text: str) -> None:
        """主线程：显示一条临时提示"""
        log = self.query_one("#message-log", ScrollableContainer)
        await log.mount(Static(text))
        log.scroll_end()

    def _set_input_placeholder(self, text: str) -> None:
        """主线程：更新输入框占位符"""
        try:
            self.query_one("#user-input", Input).placeholder = text
        except Exception:
            pass

    async def add_message(self, role: str, content: str) -> None:
        """添加消息"""
        log = self.query_one("#message-log", ScrollableContainer)

        if role == "user":
            widget = Static(f"[cyan]你:[/cyan] {content}", classes="user-message")
        elif role == "assistant":
            widget = Static(f"[magenta]AI:[/magenta] {content}", classes="ai-message")
        else:
            role_zh = ROLE_NAMES_ZH.get(role, role)
            widget = Static(f"[dim]{role_zh}: {content}[/dim]")

        await log.mount(widget)
        log.scroll_end()

    def action_quit(self) -> None:
        """退出"""
        # 若工作线程正阻塞等待确认，唤醒它以解阻塞
        if self._confirm_pending is not None:
            self._confirm_result = False
            self._confirm_pending = None
            self._confirm_event.set()
        self.agent.save()
        self.exit()

    def action_clear(self) -> None:
        """清屏"""
        self.query_one("#message-log", ScrollableContainer).clear()


def run_tui():
    """运行 TUI"""
    app = ZzhClawApp()
    app.run()
