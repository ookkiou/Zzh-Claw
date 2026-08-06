"""
zzhclaw.session - 会话管理
支持保存/加载历史、会话分支
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict


@dataclass
class Message:
    """一条消息"""
    role: str
    content: str
    timestamp: str
    id: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(**data)


@dataclass
class SessionBranch:
    """会话分支"""
    id: str
    name: str
    parent_message_id: Optional[str]
    messages: List[Message]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_message_id": self.parent_message_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionBranch":
        return cls(
            id=data["id"],
            name=data["name"],
            parent_message_id=data.get("parent_message_id"),
            messages=[Message.from_dict(m) for m in data["messages"]],
            created_at=data["created_at"]
        )


@dataclass
class Session:
    """会话"""
    id: str
    name: str
    created_at: str
    branches: Dict[str, SessionBranch]
    current_branch_id: str

    @property
    def current_branch(self) -> SessionBranch:
        return self.branches[self.current_branch_id]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "branches": {k: v.to_dict() for k, v in self.branches.items()},
            "current_branch_id": self.current_branch_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
            branches={k: SessionBranch.from_dict(v) for k, v in data["branches"].items()},
            current_branch_id=data["current_branch_id"]
        )


class SessionManager:
    """会话管理器"""

    def __init__(self, storage_dir: str = "~/.zzhclaw/sessions"):
        self.storage_dir = os.path.expanduser(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self.current_session: Optional[Session] = None

    def create_session(self, name: Optional[str] = None) -> Session:
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        session_name = name or f"会话 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        branch_id = "main"

        branch = SessionBranch(
            id=branch_id,
            name="主线",
            parent_message_id=None,
            messages=[],
            created_at=datetime.now().isoformat()
        )

        session = Session(
            id=session_id,
            name=session_name,
            created_at=datetime.now().isoformat(),
            branches={branch_id: branch},
            current_branch_id=branch_id
        )

        self.current_session = session
        return session

    def save_session(self, session: Optional[Session] = None):
        """保存会话"""
        session = session or self.current_session
        if not session:
            return

        filepath = os.path.join(self.storage_dir, f"{session.id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)

    def load_session(self, session_id: str) -> Optional[Session]:
        """加载会话"""
        filepath = os.path.join(self.storage_dir, f"{session_id}.json")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        session = Session.from_dict(data)
        self.current_session = session
        return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话"""
        sessions = []
        for filename in os.listdir(self.storage_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.storage_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        sessions.append({
                            "id": data["id"],
                            "name": data["name"],
                            "created_at": data["created_at"],
                            "branches": len(data["branches"]),
                            "messages": sum(len(b["messages"]) for b in data["branches"].values())
                        })
                except Exception:
                    pass

        return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        filepath = os.path.join(self.storage_dir, f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            if self.current_session and self.current_session.id == session_id:
                self.current_session = None
            return True
        return False

    def fork_branch(self, message_index: int, new_branch_name: str) -> SessionBranch:
        """从某个消息处分支"""
        session = self.current_session
        if not session:
            raise ValueError("没有活动会话")

        current_branch = session.current_branch
        if message_index < 0 or message_index >= len(current_branch.messages):
            raise ValueError("无效的消息索引")

        parent_message = current_branch.messages[message_index]
        new_branch_id = str(uuid.uuid4())[:8]

        new_branch = SessionBranch(
            id=new_branch_id,
            name=new_branch_name,
            parent_message_id=parent_message.id,
            messages=current_branch.messages[:message_index + 1],
            created_at=datetime.now().isoformat()
        )

        session.branches[new_branch_id] = new_branch
        session.current_branch_id = new_branch_id
        return new_branch

    def switch_branch(self, branch_id: str):
        """切换分支"""
        session = self.current_session
        if not session:
            raise ValueError("没有活动会话")

        if branch_id not in session.branches:
            raise ValueError("无效的分支 ID")

        session.current_branch_id = branch_id

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None
    ):
        """添加消息到当前会话"""
        session = self.current_session
        if not session:
            return

        message = Message(
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            id=str(uuid.uuid4())[:8],
            tool_calls=tool_calls,
            tool_call_id=tool_call_id
        )

        session.current_branch.messages.append(message)
        self.save_session()

    def get_messages(
        self,
        max_messages: int = 50,
        max_chars: int = 80000,
    ) -> List[Dict[str, Any]]:
        """获取当前消息列表（给 LLM 用）

        带 token 截断：保留首条 system 消息，保留最近的消息，并保证不会在
        工具调用配对（assistant 的 tool_calls 与对应 tool 结果）中间截断，
        避免长会话超出 context window。

        max_messages: 滑动窗口最多保留的消息条数
        max_chars:     近似 token 上限（按字符数估算，约 4 字符≈1 token）
        """
        session = self.current_session
        if not session:
            return []

        # 转换为 OpenAI 格式
        def to_dict(msg: Message) -> Dict[str, Any]:
            msg_dict = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            return msg_dict

        all_msgs = [to_dict(m) for m in session.current_branch.messages]
        if not all_msgs:
            return []

        # 1. 首条 system 单独保留（始终留在窗口里）
        system_msgs: List[Dict[str, Any]] = []
        rest = all_msgs
        if all_msgs[0]["role"] == "system":
            system_msgs = [all_msgs[0]]
            rest = all_msgs[1:]

        # 2. 按条数取滑动窗口（保留最近 max_messages 条）
        window = rest[-max_messages:]

        # 3. 按字符上限从前往后砍，直到总量在预算内（至少保留 1 条）
        def _char_count(msgs: List[Dict[str, Any]]) -> int:
            n = 0
            for m in msgs:
                n += len(m.get("content") or "")
                for tc in m.get("tool_calls") or []:
                    n += len(tc.get("function", {}).get("arguments", ""))
            return n

        system_chars = _char_count(system_msgs)
        while window and system_chars + _char_count(window) > max_chars and len(window) > 1:
            window.pop(0)

        # 4. 配对完整性修正：开头不能是孤立的 tool 结果，
        #    也不能是 tool_calls 结果不全的 assistant（否则 API 会报错）
        def _trim_orphans(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            # 去掉开头孤立的 tool 结果（它的 assistant 已被砍掉）
            while msgs and msgs[0]["role"] == "tool":
                msgs.pop(0)
            # 去掉开头 tool_calls 结果不全的 assistant
            if msgs and msgs[0]["role"] == "assistant" and msgs[0].get("tool_calls"):
                tool_ids = {m["tool_call_id"] for m in msgs if m["role"] == "tool"}
                asst_ids = {tc["id"] for tc in msgs[0]["tool_calls"]}
                if not asst_ids.issubset(tool_ids):
                    msgs.pop(0)
                    return _trim_orphans(msgs)  # 砍完可能又露出孤立 tool，递归清理
            return msgs

        window = _trim_orphans(window)

        # 5. 配对修复:确保每个 assistant(tool_calls) 的每个 tool_call_id
        #    都有对应的 tool 结果,缺失的补占位(防止 API 报错;
        #    也让因异常损坏的旧会话自愈)
        def _fix_tool_call_pairs(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            existing = {m["tool_call_id"] for m in msgs
                        if m["role"] == "tool" and m.get("tool_call_id")}
            result: List[Dict[str, Any]] = []
            for m in msgs:
                result.append(m)
                if m["role"] == "assistant" and m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        if tc["id"] not in existing:
                            result.append({
                                "role": "tool",
                                "content": "[工具未执行]",
                                "tool_call_id": tc["id"],
                            })
            return result

        window = _fix_tool_call_pairs(window)

        return system_msgs + window
