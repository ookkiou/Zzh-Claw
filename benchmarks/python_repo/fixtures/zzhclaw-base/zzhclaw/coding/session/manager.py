"""
zzhclaw.session - 会话管理
支持保存/加载历史、会话分支
"""

import os
import json
import uuid
import tempfile
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
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
    # 历史摘要（上下文压缩）：将前缀消息压缩后的文本，以及已覆盖的前缀长度
    summary: Optional[str] = None
    summary_up_to_index: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_message_id": self.parent_message_id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "summary": self.summary,
            "summary_up_to_index": self.summary_up_to_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionBranch":
        return cls(
            id=data["id"],
            name=data["name"],
            parent_message_id=data.get("parent_message_id"),
            messages=[Message.from_dict(m) for m in data["messages"]],
            created_at=data["created_at"],
            # 旧会话文件无这两个字段，默认值保证向后兼容
            summary=data.get("summary"),
            summary_up_to_index=int(data.get("summary_up_to_index", 0) or 0),
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
        """保存会话（原子写：先写临时文件再 os.replace，防止中途崩溃损坏会话）"""
        session = session or self.current_session
        if not session:
            return

        filepath = os.path.join(self.storage_dir, f"{session.id}.json")
        # 在同一目录下创建临时文件，保证 os.replace 是同文件系统内的原子操作
        fd, tmp_path = tempfile.mkstemp(
            dir=self.storage_dir,
            prefix=f".{session.id}.",
            suffix=".json.tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, filepath)
        except Exception:
            # 写失败时清理临时文件，不留垃圾
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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
                except Exception as e:
                    # 会话文件损坏不应静默吞掉，至少给 stderr 留一条痕迹
                    import sys
                    print(f"[warn] 无法读取会话 {filename}: {e}", file=sys.stderr)

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

    def fork_branch(self, message_index: int, new_branch_name: str, reset_summary: bool = False) -> SessionBranch:
        """从某个消息处分支

        reset_summary: 默认 False，新分支沿用父分支的摘要；True 则丢弃摘要重新积累。
        沿用时会把 summary_up_to_index 限制在 fork 点之内，避免覆盖不存在的消息。
        注：若 fork 点早于父分支摘要的实际覆盖范围，摘要文本里可能含有 fork 点之后的信息，
        作为简单折中接受（若介意可传 reset_summary=True）。
        """
        session = self.current_session
        if not session:
            raise ValueError("没有活动会话")

        current_branch = session.current_branch
        if message_index < 0 or message_index >= len(current_branch.messages):
            raise ValueError("无效的消息索引")

        parent_message = current_branch.messages[message_index]
        new_branch_id = str(uuid.uuid4())[:8]

        # 摘要继承
        if reset_summary:
            new_summary: Optional[str] = None
            new_summary_idx = 0
        else:
            new_summary = current_branch.summary
            new_summary_idx = min(current_branch.summary_up_to_index, message_index + 1)
            # 若限制后前缀长度为 0，摘要已不适用，直接丢弃
            if new_summary_idx <= 0:
                new_summary = None
                new_summary_idx = 0

        new_branch = SessionBranch(
            id=new_branch_id,
            name=new_branch_name,
            parent_message_id=parent_message.id,
            messages=current_branch.messages[:message_index + 1],
            created_at=datetime.now().isoformat(),
            summary=new_summary,
            summary_up_to_index=new_summary_idx,
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

        上下文结构：[system prompt] + [历史摘要（若有）] + [最近原文消息]

        其中“历史摘要”来自 branch.summary，覆盖 branch.messages[:summary_up_to_index]；
        “最近原文消息”从 summary_up_to_index 开始，再经下面五步兑底截断（保留滑动窗口/字符
        预算/配对修正/配对自愈），确保发给 API 的消息始终符合 function calling 协议。

        max_messages: 滑动窗口最多保留的近期消息条数
        max_chars:     近似 token 上限（按字符数估算，约 4 字符≈1 token），包含摘要本身
        """
        session = self.current_session
        if not session:
            return []
        branch = session.current_branch

        # 转换为 OpenAI 格式
        def to_dict(msg: Message) -> Dict[str, Any]:
            msg_dict = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            return msg_dict

        all_msgs = [to_dict(m) for m in branch.messages]
        if not all_msgs:
            return []

        # 1. 首条 system 单独保留（始终留在窗口里）
        system_msgs: List[Dict[str, Any]] = []
        if all_msgs[0]["role"] == "system":
            system_msgs = [all_msgs[0]]

        # 2. 若有摘要，拼接为合成 system 消息，紧跟首条 system prompt
        summary_msg: Optional[Dict[str, Any]] = None
        if branch.summary:
            summary_msg = {
                "role": "system",
                "content": f"[历史对话摘要]\n{branch.summary}",
            }

        # 3. 跳过已摘要的前缀，取近期原文作为滑动窗口基底
        start_idx = max(branch.summary_up_to_index, len(system_msgs))
        rest = all_msgs[start_idx:]

        # 4. 按条数取滑动窗口（保留最近 max_messages 条）
        window = rest[-max_messages:] if max_messages > 0 else rest[:]

        # 5. 按字符上限从前往后砍，直到总量在预算内（至少保留 1 条）
        def _char_count(msgs: List[Dict[str, Any]]) -> int:
            n = 0
            for m in msgs:
                n += len(m.get("content") or "")
                for tc in m.get("tool_calls") or []:
                    n += len(tc.get("function", {}).get("arguments", ""))
            return n

        fixed_chars = _char_count(system_msgs) + _char_count([summary_msg] if summary_msg else [])
        while window and fixed_chars + _char_count(window) > max_chars and len(window) > 1:
            window.pop(0)

        # 6. 配对完整性修正：开头不能是孤立的 tool 结果，
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

        # 7. 配对修复:确保每个 assistant(tool_calls) 的每个 tool_call_id
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

        prefix = system_msgs + ([summary_msg] if summary_msg else [])
        return prefix + window

    def summarize_old_messages(
        self,
        summarize_fn: Callable[[Optional[str], List[Dict[str, Any]]], str],
        keep_recent: int = 20,
        min_new_to_summarize: int = 10,
    ) -> bool:
        """把 keep_recent 之外的旧消息压缩成摘要（增量）。

        summarize_fn: 可调用对象，签名 (existing_summary, messages) -> str；
                      一般传 LLMClient.summarize，避免 SessionManager 直接依赖 LLM。
        keep_recent: 保留完整原文的最近消息条数（不参与压缩）。
        min_new_to_summarize: 待压缩区至少累积多少条才触发 LLM，避免频繁小摘要。

        返回 True 表示成功生成了新摘要，False 表示未触发（消息数不够、无变化或异常降级）。
        异常不会向上抛，失败时不修改任何状态，Agent 层可直接忽略返回值。
        """
        session = self.current_session
        if not session:
            return False
        branch = session.current_branch
        all_msgs = branch.messages
        if not all_msgs:
            return False

        # 保护：首条 system prompt 不参与压缩
        first_is_system = all_msgs[0].role == "system"
        start = branch.summary_up_to_index
        if start == 0 and first_is_system:
            start = 1

        # 初始边界：保留最近 keep_recent 条原文
        boundary = len(all_msgs) - keep_recent
        if boundary <= start:
            return False  # 尚未累积足够旧消息

        # 配对完整性对齐：避免将 assistant(tool_calls) 与其 tool 结果切开
        # 1) boundary 指向 tool 消息时，向后推到不是 tool 为止（tool 跟随其 assistant 一起进压缩区）
        while boundary < len(all_msgs) and all_msgs[boundary].role == "tool":
            boundary += 1
        # 2) 若压缩区末尾是带 tool_calls 的 assistant 但它的 tool 结果不全在压缩区内，
        #    把这个 assistant 前移出压缩区（留到下次一起压缩）
        while boundary > start:
            tail = all_msgs[boundary - 1]
            if tail.role == "assistant" and tail.tool_calls:
                tc_ids = {tc["id"] for tc in tail.tool_calls}
                result_ids = {
                    m.tool_call_id for m in all_msgs[:boundary]
                    if m.role == "tool" and m.tool_call_id
                }
                if not tc_ids.issubset(result_ids):
                    boundary -= 1
                    continue
            break

        if boundary - start < min_new_to_summarize:
            return False

        to_compress = all_msgs[start:boundary]
        if not to_compress:
            return False

        # 转换为 OpenAI dict 格式交给 summarize_fn
        def to_dict(msg: Message) -> Dict[str, Any]:
            d: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                d["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
            return d

        msgs_for_summary = [to_dict(m) for m in to_compress]

        try:
            new_summary = summarize_fn(branch.summary, msgs_for_summary)
        except Exception:
            # 摘要失败（网络/接口/模型异常）：不修改任何状态，返回 False，
            # get_messages 里的滑动窗口兑底仍能保证 API 调用不超预算
            return False

        if not new_summary or not isinstance(new_summary, str):
            return False

        # 更新状态并持久化
        branch.summary = new_summary.strip()
        branch.summary_up_to_index = boundary
        try:
            self.save_session()
        except Exception:
            # 写盘失败不回滚内存状态（下一次 add_message 还会重试）
            pass
        return True
