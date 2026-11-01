"""把录制下来的真实 chunk 回放成 LLMClient 的替身。

真实网络不可用时（CI、离线、避免计费），用 tests/fixtures/real_stream_shape.json
驱动 Agent，验证它对 OpenAI 流式协议的累积逻辑对得上真实响应。
"""

from types import SimpleNamespace


def _to_object(value):
    """录制时是 dict；还原成属性访问对象，保持和 SDK chunk 一样的用法。"""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_object(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_object(v) for v in value]
    return value


class RecordedLLM:
    """按 LLMClient.chat_stream 的语义回放真实 chunk 序列。

    与生产代码逐条对齐（ai/client.py:97-102）：
      - 跳过没有 choices 的 chunk（心跳/usage 尾包）
      - choices[0].delta 为 None 时也跳过
    """

    def __init__(self, turns, summarize_result="回放摘要"):
        self.turns = [_to_object(turn["chunks"]) for turn in turns]
        self.summarize_result = summarize_result
        self.calls = []
        self._turn = 0

    @classmethod
    def from_payload(cls, payload):
        return cls(payload["turns"])

    def chat_stream(self, messages, tools=None):
        if self._turn >= len(self.turns):
            raise RuntimeError(
                f"录制数据只有 {len(self.turns)} 轮，Agent 发起了第 {self._turn + 1} 次调用"
            )
        self.calls.append({"messages": messages, "tools": tools})
        chunk = self.turns[self._turn]
        self._turn += 1
        for c in chunk:
            if c.choices:
                delta = c.choices[0].delta
                if delta is not None:
                    yield delta

    def summarize(self, existing_summary, messages):
        return self.summarize_result
