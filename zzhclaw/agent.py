"""
agent.py - Agent 核心逻辑 (对应 pi-agent-core)
"""

import json
from typing import List, Dict, Any, Callable, Optional
from .ai import LLMClient
from .tools import TOOLS, execute_tool
from .session import SessionManager


class Agent:
    """Agent 核心"""

    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        session_manager: Optional[SessionManager] = None
    ):
        self.llm = llm or LLMClient()
        self.session_manager = session_manager or SessionManager()

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
        confirm_tool: Optional[Callable[[str, Dict], bool]] = None
    ) -> str:
        """运行一次交互"""
        # 确保有会话
        if not self.session_manager.current_session:
            self.new_session()

        # 添加用户消息
        self.session_manager.add_message("user", user_input)

        while True:
            # 获取消息
            messages = self.session_manager.get_messages()

            # 调用 LLM
            response = self.llm.chat(messages, tools=TOOLS)
            message = response.choices[0].message

            # 添加到会话
            content = message.content or ""
            tool_calls_dicts = None
            if message.tool_calls:
                tool_calls_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            self.session_manager.add_message("assistant", content, tool_calls=tool_calls_dicts)

            # 如果有工具调用
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    # 确认是否执行
                    if confirm_tool:
                        if not confirm_tool(name, args):
                            self.session_manager.add_message(
                                "tool",
                                f"用户拒绝执行: {name}",
                                tool_call_id=tool_call.id
                            )
                            continue

                    if on_tool_call:
                        on_tool_call(name, args)

                    result = execute_tool(name, args)

                    if on_tool_result:
                        on_tool_result(name, result)

                    # 工具结果也添加到会话，带上 tool_call_id
                    self.session_manager.add_message("tool", result, tool_call_id=tool_call.id)
                continue

            # 没有工具调用，返回结果
            return content
