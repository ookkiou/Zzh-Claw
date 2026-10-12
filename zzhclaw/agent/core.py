"""
zzhclaw.agent - Agent 核心逻辑
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional

from ..ai import LLMClient
from ..coding.session import SessionManager
from ..coding.tools import execute_tool, get_tools_with_cwd, is_readonly_tool

# 默认系统指令：引导模型在请求模糊时先澄清再行动
DEFAULT_SYSTEM_PROMPT = (
    "你是 ZzhClaw，一个中文编程助手，可以调用工具帮助用户完成任务。\n"
    "行为准则：\n"
    "1. 当用户的请求存在多种合理解释、缺少必要信息（如目标路径、范围、参数）、\n"
    "   或可能产生破坏性/不可逆后果时，先向用户提出简明的澄清问题，得到确认后再调用工具；\n"
    "2. 澄清问题应聚焦关键分歧点，一次不要问太多（建议 1-3 个），并给出你倾向的默认方案供用户选择；\n"
    "3. 若请求已经明确、或存在合理默认值且不涉及风险，直接执行，不要为问而问；\n"
    "4. 若任务匹配某个可用 skill，先用 Skill 工具（不传 name 可列出全部）加载其指令，再按指令执行；\n"
    "5. 使用与用户相同的语言回复（默认为中文）。"
)


class Agent:
    """Agent 核心"""

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        session_manager: Optional[SessionManager] = None,
        system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT,
        permission_mode: str = "confirm",
    ):
        self.llm = llm or LLMClient()
        self.session_manager = session_manager or SessionManager()
        self.system_prompt = system_prompt
        # 权限模式：confirm(每个都问) / smart(只读自动,写确认) / auto(全自动)
        self.permission_mode = permission_mode if permission_mode in ("confirm", "smart", "auto") else "confirm"

    def set_permission_mode(self, mode: str) -> str:
        """设置权限模式，返回生效后的模式（无效值不改变原模式）"""
        if mode in ("confirm", "smart", "auto"):
            self.permission_mode = mode
        return self.permission_mode

    def _should_confirm(self, tool_name: str, confirm_tool: Optional[Callable]) -> bool:
        """根据权限模式决定某个工具是否需要用户确认

        - confirm: 所有工具都确认
        - smart:   只读工具自动放行，写/执行工具确认
        - auto:    所有工具自动放行（仍受黑名单+沙箱底层防护）
        注：confirm_tool 为 None 时无法确认，直接放行。
        """
        if confirm_tool is None:
            return False
        if self.permission_mode == "auto":
            return False
        if self.permission_mode == "smart":
            return not is_readonly_tool(tool_name)
        return True

    def _ensure_system_prompt(self) -> None:
        """确保当前会话首条消息是 system prompt。

        - 新会话（无消息）：注入系统指令作为首条消息；
        - 已有会话：若首条已是 system 消息则保持不变（兼容旧会话中用户自定义的 system）；
          若首条不是 system 消息，为避免破坏已有会话的历史与截断逻辑，不做修改。
        """
        if not self.system_prompt:
            return
        session = self.session_manager.current_session
        if not session:
            return
        messages = session.current_branch.messages
        if not messages:
            self.session_manager.add_message("system", self.system_prompt)

    def new_session(self, name: Optional[str] = None):
        """创建新会话"""
        self.session_manager.create_session(name)

    def load_session(self, session_id: str) -> bool:
        """加载会话"""
        return self.session_manager.load_session(session_id) is not None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话"""
        return self.session_manager.list_sessions()

    def fork_branch(self, message_index: int, new_branch_name: str):
        """分支会话"""
        self.session_manager.fork_branch(message_index, new_branch_name)

    def save(self):
        """保存当前会话"""
        self.session_manager.save_session()

    def run(
        self,
        user_input: str,
        on_tool_call: Optional[Callable[[str, Dict], None]] = None,
        on_tool_result: Optional[Callable[[str, str], None]] = None,
        confirm_tool: Optional[Callable[[str, Dict], bool]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        max_iterations: int = 20,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> str:
        """运行一次交互（流式）

        on_token: 流式 token 回调，签名 (delta_text: str) -> None，实时推送 AI 回复增量。
        max_iterations: 单次交互内工具调用轮次上限，防止模型陷入死循环持续烧钱。
        on_event: 结构化生命周期事件回调，供评测与可观测性使用；不替代已有回调。
        """
        def emit(event_type: str, **payload: Any) -> None:
            if on_event:
                on_event({"event_type": event_type, **payload})

        # 确保有会话
        if not self.session_manager.current_session:
            self.new_session()

        # 首次对话时注入 system prompt（若会话已有消息则跳过，兼容旧会话）
        self._ensure_system_prompt()

        # 添加用户消息
        self.session_manager.add_message("user", user_input)
        emit("agent_start", metadata={"max_iterations": max_iterations})

        # 主动触发历史摘要（上下文压缩）：把 keep_recent 之外的旧消息压缩成一段摘要。
        # 失败不阻塞主流程：get_messages 里的滑动窗口兑底仍能保证 API 调用不超预算。
        # 放在循环外而不是循环内：单次 run 内消息增长有限，每轮都触发意义不大且增加成本。
        try:
            self.session_manager.summarize_old_messages(
                summarize_fn=self.llm.summarize,
                keep_recent=20,
                min_new_to_summarize=10,
            )
        except Exception:
            pass

        for iteration in range(1, max_iterations + 1):
            # 获取消息
            messages = self.session_manager.get_messages()

            # 流式调用 LLM：边收边推送 content token，按 index 累积 tool_calls 增量
            content_parts: List[str] = []
            tool_calls_acc: Dict[int, Dict[str, str]] = {}
            try:
                for delta in self.llm.chat_stream(messages, tools=get_tools_with_cwd()):
                    # content 增量
                    delta_content = getattr(delta, "content", None)
                    if delta_content:
                        content_parts.append(delta_content)
                        if on_token:
                            on_token(delta_content)
                    # tool_calls 增量（按 index 拼接 arguments 片段）
                    delta_tcs = getattr(delta, "tool_calls", None)
                    if delta_tcs:
                        for tc in delta_tcs:
                            idx = getattr(tc, "index", None)
                            idx = idx if idx is not None else 0
                            acc = tool_calls_acc.setdefault(
                                idx, {"id": "", "name": "", "arguments": ""}
                            )
                            if getattr(tc, "id", None):
                                acc["id"] = tc.id
                            fn = getattr(tc, "function", None)
                            if fn:
                                if getattr(fn, "name", None):
                                    acc["name"] = fn.name
                                if getattr(fn, "arguments", None):
                                    acc["arguments"] += fn.arguments
            except Exception as exc:
                emit(
                    "agent_error",
                    error=f"{type(exc).__name__}: {exc}",
                    metadata={"iteration": iteration, "stage": "llm"},
                )
                raise

            content = "".join(content_parts)
            # 组装 tool_calls 为标准 dict 格式（按 index 排序，过滤无效项）
            tool_calls_list: List[Dict[str, Any]] = []
            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                if acc["name"]:  # 只保留有函数名的有效 tool_call
                    tool_calls_list.append({
                        "id": acc["id"],
                        "type": "function",
                        "function": {"name": acc["name"], "arguments": acc["arguments"]},
                    })
            tool_calls_dicts = tool_calls_list if tool_calls_list else None

            self.session_manager.add_message("assistant", content, tool_calls=tool_calls_dicts)

            # 如果有工具调用
            if tool_calls_list:
                for tc in tool_calls_list:
                    name = tc["function"]["name"]
                    tc_id = tc["id"]

                    # 参数解析：模型偶尔会返回坏 JSON，把错误作为工具结果回传给模型自愈
                    raw_args = tc["function"]["arguments"] or "{}"
                    try:
                        args = json.loads(raw_args)
                        if not isinstance(args, dict):
                            raise ValueError(f"预期 dict，实际得到 {type(args).__name__}")
                    except (json.JSONDecodeError, ValueError) as e:
                        err = f"工具参数解析失败: {e}; 原始参数: {raw_args!r}"
                        emit(
                            "tool_call",
                            tool_call_id=tc_id,
                            tool_name=name,
                            arguments=None,
                            error=str(e),
                            metadata={"iteration": iteration, "raw_arguments": raw_args},
                        )
                        if on_tool_result:
                            on_tool_result(name, err)
                        self.session_manager.add_message("tool", err, tool_call_id=tc_id)
                        emit(
                            "tool_result",
                            tool_call_id=tc_id,
                            tool_name=name,
                            result=err,
                            duration_ms=0,
                            error=str(e),
                            metadata={"iteration": iteration},
                        )
                        continue

                    emit(
                        "tool_call",
                        tool_call_id=tc_id,
                        tool_name=name,
                        arguments=args,
                        metadata={"iteration": iteration, "raw_arguments": raw_args},
                    )

                    # 确认是否执行（根据权限模式决定是否需要问用户）
                    if self._should_confirm(name, confirm_tool):
                        if not confirm_tool(name, args):
                            rejected = f"用户拒绝执行: {name}"
                            self.session_manager.add_message(
                                "tool",
                                rejected,
                                tool_call_id=tc_id
                            )
                            emit(
                                "tool_result",
                                tool_call_id=tc_id,
                                tool_name=name,
                                result=rejected,
                                duration_ms=0,
                                metadata={"iteration": iteration, "rejected": True},
                            )
                            continue

                    if on_tool_call:
                        on_tool_call(name, args)

                    # 工具执行兜底：任何未捕获异常都转为结果字符串，保证会话配对不损坏
                    tool_started = time.perf_counter()
                    tool_error = None
                    try:
                        result = execute_tool(name, args)
                    except Exception as e:
                        result = f"工具执行异常: {type(e).__name__}: {e}"
                        tool_error = f"{type(e).__name__}: {e}"
                    tool_duration_ms = int((time.perf_counter() - tool_started) * 1000)

                    if on_tool_result:
                        on_tool_result(name, result)

                    # 工具结果也添加到会话，带上 tool_call_id
                    self.session_manager.add_message("tool", result, tool_call_id=tc_id)
                    emit(
                        "tool_result",
                        tool_call_id=tc_id,
                        tool_name=name,
                        result=result,
                        duration_ms=tool_duration_ms,
                        error=tool_error,
                        metadata={"iteration": iteration},
                    )
                continue

            # 没有工具调用，返回结果
            emit(
                "agent_final",
                result=content,
                metadata={"iteration": iteration, "termination": "completed"},
            )
            return content

        # 达到最大迭代次数：写入一条提示作为 assistant 回复，保证会话历史完整
        warning = (
            f"⚠️ 已达到单次交互工具调用轮次上限 ({max_iterations})，自动停止。\n"
            "建议：拆分任务、缩小范围，或提高 max_iterations 后重试。"
        )
        self.session_manager.add_message("assistant", warning)
        emit(
            "agent_final",
            result=warning,
            metadata={"iteration": max_iterations, "termination": "max_iterations"},
        )
        return warning
