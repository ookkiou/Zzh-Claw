"""
zzhclaw.ai - LLM API 封装
"""

import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


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

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
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
