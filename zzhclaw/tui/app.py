"""
zzhclaw.tui - Textual 终端界面
"""

import threading
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static, Markdown
from textual.containers import ScrollableContainer, Vertical
from textual.widget import Widget
from textual.message import Message
from textual import work
from rich.markup import escape
from ..ai import LLMClient
from ..agent import Agent
from ..coding.tools import (
    set_cwd, get_cwd, set_sandbox,
    list_skills, load_skill, create_skill, get_skills_dirs,
)

# 工具名中英映射（用于界面显示）
TOOL_NAMES_ZH = {
    "read_file": "读取文件",
    "write_file": "写入文件",
    "edit_file": "编辑文件",
    "run_bash": "执行命令",
    "web_search": "联网搜索",
    "fetch_webpage": "获取网页",
    "grep_files": "搜索内容",
    "glob_files": "查找文件",
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

# 权限模式中文描述
PERMISSION_MODE_DESC = {
    "confirm": "每个工具都确认",
    "smart": "只读自动，写/执行确认",
    "auto": "全自动，不再询问",
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


class TokenMsg(Message):
    """工作线程：流式 token 增量"""
    def __init__(self, delta: str) -> None:
        super().__init__()
        self.delta = delta


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
        # 流式输出状态
        self.streaming_widget = None  # 当前流式 AI 消息 widget
        self.streaming_text = ""      # 累积的流式文本

    def compose(self) -> ComposeResult:
        yield Header()
        yield MessageLog(id="message-log")
        with Vertical(id="input-area"):
            yield Input(placeholder="输入消息... (Ctrl+C 退出)", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        """应用启动"""
        self.title = "ZzhClaw"
        self.sub_title = f"权限: {self.agent.permission_mode}"
        self.query_one("#user-input", Input).focus()

    def _update_mode_indicator(self) -> None:
        """更新 Header 副标题的权限模式指示"""
        self.sub_title = f"权限: {self.agent.permission_mode}"

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
  /cd [path]        - 查看/切换工作目录
  /sandbox <on|off> - 开关写沙箱
  /permission [mode] - 查看/切换权限模式 (confirm|smart|auto)
  /auto             - 一键切换全自动模式
  /skills           - 列出可用 skill（项目级+全局级）
  /skill new <name> [--global] - 创建 skill 模板
  /skill <name>     - 预览指定 skill 内容
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

            elif cmd == "cd":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    await log.mount(Static(f"当前工作目录: [cyan]{get_cwd()}[/cyan]"))
                else:
                    result = set_cwd(parts[1].strip())
                    if result.startswith("错误"):
                        await log.mount(Static(f"[red]{result}[/red]"))
                    else:
                        await log.mount(Static(f"[green]工作目录已切换: {result}[/green]"))
                log.scroll_end()
                return

            elif cmd == "sandbox":
                parts = user_input.split()
                if len(parts) < 2:
                    from ..coding.tools.registry import _WORKSPACE
                    state = "开启" if _WORKSPACE["sandbox"] else "关闭"
                    await log.mount(Static(f"写沙箱当前: [cyan]{state}[/cyan]（用法: /sandbox on|off）"))
                elif parts[1].lower() in ("on", "true", "1"):
                    set_sandbox(True)
                    await log.mount(Static("[green]写沙箱已开启：write_file 只能写工作目录内[/green]"))
                elif parts[1].lower() in ("off", "false", "0"):
                    set_sandbox(False)
                    await log.mount(Static("[yellow]写沙箱已关闭：write_file 可写任意路径（谨慎）[/yellow]"))
                else:
                    await log.mount(Static("[red]用法: /sandbox on|off[/red]"))
                log.scroll_end()
                return

            elif cmd in ["permission", "perm"]:
                parts = user_input.split()
                if len(parts) < 2:
                    cur = self.agent.permission_mode
                    await log.mount(Static(
                        f"当前权限模式: [cyan]{cur}[/cyan]（{PERMISSION_MODE_DESC[cur]}）\n"
                        "[dim]用法: /permission confirm|smart|auto，或 /auto 一键全自动[/dim]"
                    ))
                else:
                    new_mode = parts[1].lower()
                    result = self.agent.set_permission_mode(new_mode)
                    if result == new_mode:
                        self._update_mode_indicator()
                        await log.mount(Static(f"[green]权限模式已切换: {result}（{PERMISSION_MODE_DESC[result]}）[/green]"))
                    else:
                        await log.mount(Static(f"[red]无效模式: {new_mode}（可选 confirm|smart|auto）[/red]"))
                log.scroll_end()
                return

            elif cmd == "auto":
                self.agent.set_permission_mode("auto")
                self._update_mode_indicator()
                await log.mount(Static(
                    "[green]✅ 已切换全自动模式：agent 将自主执行所有工具[/green]\n"
                    "[dim]仍受危险命令黑名单 + 写沙箱保护；恢复确认请输入 /permission confirm[/dim]"
                ))
                log.scroll_end()
                return

            elif cmd == "skills":
                skills = list_skills()
                if not skills:
                    dirs = "、".join(d["path"] for d in get_skills_dirs())
                    await log.mount(Static(
                        f"[yellow]没有可用 skill[/yellow]（已扫描: {dirs}）\n"
                        "[dim]用 /skill new <name> 在项目里创建一个[/dim]"
                    ))
                else:
                    text = "[bold]可用 skill:[/bold]\n"
                    for s in skills:
                        text += (
                            f"  [cyan][{s['scope']}][/cyan] [green]{s['name']}[/green]: "
                            f"{escape(s['description'] or '（无描述）')}\n"
                        )
                    await log.mount(Static(text))
                log.scroll_end()
                return

            elif cmd == "skill":
                parts = user_input.split()
                if len(parts) >= 2 and parts[1].lower() == "new":
                    if len(parts) < 3:
                        await log.mount(Static("[red]用法: /skill new <name> [--global][/red]"))
                    else:
                        scope = "global" if "--global" in parts[3:] else "project"
                        ok, msg = create_skill(parts[2], scope)
                        await log.mount(Static(escape(msg), style="green" if ok else "red"))
                elif len(parts) >= 2:
                    await log.mount(Static(
                        f"[cyan]skill: {escape(parts[1])}[/cyan]\n" + escape(load_skill(parts[1]))
                    ))
                else:
                    await log.mount(Static("[dim]用法: /skills 列出 | /skill new <name> [--global] 创建 | /skill <name> 预览[/dim]"))
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

        def on_token(delta: str):
            self.post_message(TokenMsg(delta))

        try:
            response = self.agent.run(
                user_input,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
                confirm_tool=confirm_tool,
                on_token=on_token,
            )
            self.post_message(AgentDoneMsg(response or ""))
        except Exception as e:
            self.post_message(AgentErrorMsg(str(e)))

    # ===== 消息 handler（主线程，async，可 await mount）=====
    async def on_tool_call_msg(self, event: ToolCallMsg) -> None:
        # 多轮对话边界：工具调用前定型当前流式气泡，下轮 token 新建气泡
        if self.streaming_widget is not None:
            self.streaming_widget.update(
                "[magenta]AI:[/magenta] " + escape(self.streaming_text)
            )
            self.streaming_widget = None
            self.streaming_text = ""
        await self._append_tool_call(event.name, event.args)

    async def on_tool_result_msg(self, event: ToolResultMsg) -> None:
        await self._append_tool_result(event.name, event.result)

    async def on_confirm_request_msg(self, event: ConfirmRequestMsg) -> None:
        await self._show_confirm_prompt(event.name, event.args)

    async def on_token_msg(self, event: TokenMsg) -> None:
        """主线程：流式 token 增量渲染（打字机效果）"""
        log = self.query_one("#message-log", ScrollableContainer)
        if self.streaming_widget is None:
            # 第一个 token：移除 thinking，创建流式 widget
            if self.thinking:
                self.thinking.remove()
                self.thinking = None
            self.streaming_text = ""
            self.streaming_widget = Static("", classes="ai-message")
            await log.mount(self.streaming_widget)
        self.streaming_text += event.delta
        # 转义 markup 特殊字符（避免 [ ] 被当 rich markup），末尾加闪烁光标
        self.streaming_widget.update(
            "[magenta]AI:[/magenta] " + escape(self.streaming_text) + " ▊"
        )
        log.scroll_end()

    async def on_agent_done_msg(self, event: AgentDoneMsg) -> None:
        if self.streaming_widget is not None:
            # 流式结束：用 Markdown widget 替换纯文本 Static，渲染代码块/列表/表格
            final_text = self.streaming_text
            log = self.query_one("#message-log", ScrollableContainer)
            self.streaming_widget.remove()
            self.streaming_widget = None
            self.streaming_text = ""
            await log.mount(Markdown(final_text or "", classes="ai-message"))
            log.scroll_end()
            self._cleanup_after_agent()
        else:
            # 无流式输出（纯工具调用无文本回复）
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
        # 清理未完成的流式 widget（异常时）
        if self.streaming_widget is not None:
            self.streaming_widget.remove()
            self.streaming_widget = None
            self.streaming_text = ""
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
            widget = Static(f"[cyan]你:[/cyan] {escape(content)}", classes="user-message")
            await log.mount(widget)
        elif role == "assistant":
            # AI 消息用 Markdown widget 渲染（代码块/列表/标题/表格）
            await log.mount(Markdown(content or "", classes="ai-message"))
        else:
            role_zh = ROLE_NAMES_ZH.get(role, role)
            widget = Static(f"[dim]{role_zh}: {escape(content)}[/dim]")
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
