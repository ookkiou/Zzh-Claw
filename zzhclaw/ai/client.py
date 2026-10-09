"""
zzhclaw.ai - LLM API 封装
"""

import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


# 摘要生成的 system 指令：告诉模型如何压缩历史对话
SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要助手。请把给定的对话历史压缩成一段简洁的中文摘要，"
    "用于替换原始消息注入到 LLM 上下文中，帮助模型在有限窗口内保留关键信息。\n"
    "摘要要求：\n"
    "1. 保留关键事实：用户的目标/需求、已确认的决定、涉及的文件路径/命令/参数、"
    "未完成事项、错误信息与解决方案；\n"
    "2. 忽略寒暄、重复内容、已被后续对话覆盖的中间态；\n"
    "3. 用第三人称叙述（例如「用户询问了 X，助手执行了 Y，结果是 Z」）；\n"
    "4. 输出纯文本，不使用 markdown 标题，可用短横线列点；\n"
    "5. 严格控制在 1500 字符以内。"
)


class LLMClient:
    """LLM 客户端封装"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")
        self.model = model or os.getenv("OPENAI_MODEL_ID") or os.getenv("ANTHROPIC_MODEL_ID", "gpt-4o-mini")

        if not self.api_key or not self.base_url:
            raise ValueError("请配置 API_KEY 和 BASE_URL")

        # 重试与超时：避免网络抖动/429 直接抛给用户
        # 可通过 .env 调整：OPENAI_MAX_RETRIES / OPENAI_TIMEOUT
        try:
            max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
        except ValueError:
            max_retries = 3
        try:
            timeout = float(os.getenv("OPENAI_TIMEOUT", "60"))
        except ValueError:
            timeout = 60.0

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False
    ) -> Any:
        """聊天"""
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": stream
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return self.client.chat.completions.create(**kwargs)

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        """流式聊天：yield 每个 delta 对象（content / tool_calls 增量）

        调用方需自行累积 content 片段与 tool_calls 增量（按 index 拼接 arguments）。
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta is not None:
                    yield delta

    def summarize(
        self,
        existing_summary: Optional[str],
        messages: List[Dict[str, Any]],
    ) -> str:
        """把一段对话历史压缩成中文摘要，用于上下文压缩。

        existing_summary: 已有的旧摘要；None 表示首次生成，非 None 时做增量合并。
        messages: 需要压缩的新消息列表（OpenAI 格式，含 role/content/tool_calls/tool_call_id）。
        返回摘要文本；网络/接口异常向上抛，由调用方决定是否降级。
        """
        parts: List[str] = []
        if existing_summary:
            parts.append("【已有摘要（请与新增对话合并）】")
            parts.append(existing_summary)
            parts.append("")
            parts.append("【新增对话】")
        else:
            parts.append("【对话历史】")

        # 单条消息内容截断，避免摘要 prompt 自身过大（摘要输入无需完整原文）
        per_msg_limit = 2000
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content") or ""
            if len(content) > per_msg_limit:
                content = content[:per_msg_limit] + "...(截断)"
            suffix = ""
            tcs = m.get("tool_calls") or []
            if tcs:
                names = [tc.get("function", {}).get("name", "?") for tc in tcs]
                suffix += f" [调用工具: {', '.join(names)}]"
            if m.get("tool_call_id"):
                suffix += f" [tool_call_id={m['tool_call_id']}]"
            parts.append(f"- {role}: {content}{suffix}")

        if existing_summary:
            parts.append("")
            parts.append(
                "请把已有摘要与新增对话合并成一段完整摘要："
                "保留已有摘要中仍然有效的关键事实，补充新增对话的要点，"
                "对已被覆盖或过时的内容做精简。"
            )
        else:
            parts.append("")
            parts.append("请生成一段完整摘要。")

        user_prompt = "\n".join(parts)

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
        )
        if not resp.choices:
            return ""
        return (resp.choices[0].message.content or "").strip()
