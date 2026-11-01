"""FakeLLM：按脚本回放流式增量，替代真实 LLMClient。

Agent 只依赖两个接口：
  - chat_stream(messages, tools=...) -> 迭代 delta 对象
  - summarize(existing_summary, messages) -> str
因此可以零网络、零成本地把整条 agent 循环变成确定性测试。
"""

from types import SimpleNamespace


class ScriptExhausted(RuntimeError):
    """脚本用完但 Agent 又发起了一次 LLM 调用（通常意味着循环没按预期收敛）。"""


class Turn:
    """一次 chat_stream 调用要回放的全部 delta。"""

    def __init__(self, deltas):
        self.deltas = list(deltas)


def delta(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tc_delta(index, call_id=None, name=None, arguments=None):
    """一个 tool_call 增量；None 字段模拟 OpenAI 分片下发（只在首片给 id/name）。"""
    return SimpleNamespace(
        index=index,
        id=call_id,
        type="function" if name or call_id else None,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def text(content, chunk=8):
    """把整段回复切成多个 content 增量，验证 Agent 的拼接逻辑。"""
    if content == "":
        return Turn([delta("")])
    return Turn([
        delta(content[i:i + chunk])
        for i in range(0, len(content), chunk)
    ])


def default_call_id(name, index=0):
    return f"call_{index}_{name}"


def tool_call(name, arguments="", call_id=None, index=0, arg_chunk=6):
    """一次工具调用：先给 id+name，再把 arguments 按 arg_chunk 分片下发。"""
    call_id = call_id or default_call_id(name, index)
    deltas = [delta(tool_calls=[_tc_delta(index, call_id=call_id, name=name, arguments="")])]
    if arguments:
        for i in range(0, len(arguments), arg_chunk):
            deltas.append(
                delta(tool_calls=[_tc_delta(index, arguments=arguments[i:i + arg_chunk])])
            )
    return Turn(deltas)


def silent():
    """模型既没说话也没调工具。"""
    return Turn([])


class FakeLLM:
    """脚本化 LLM 替身。

    script 的每一项可以是：str（等价于 text(...)）、Turn、或原始 delta 列表。
    需要构造畸形/对抗性增量时，直接传 delta 列表。
    """

    def __init__(self, script=(), summarize_result=None):
        self.script = [self._normalize(item) for item in script]
        self.calls = []
        self.summarize_calls = []
        self._turn = 0
        self._summarize_result = summarize_result

    @staticmethod
    def _normalize(item):
        if isinstance(item, str):
            return text(item)
        if isinstance(item, Turn):
            return item
        if isinstance(item, list):
            return Turn(item)
        raise TypeError(f"无法识别的脚本项: {type(item).__name__}")

    @property
    def remaining(self):
        return len(self.script) - self._turn

    def chat_stream(self, messages, tools=None):
        if self._turn >= len(self.script):
            raise ScriptExhausted(
                f"FakeLLM 脚本已用尽（共 {len(self.script)} 轮），但 Agent 发起了第 "
                f"{self._turn + 1} 次调用。请给脚本补一轮，或检查被测逻辑是否陷入了循环。"
            )
        self.calls.append({"messages": messages, "tools": tools})
        turn = self.script[self._turn]
        self._turn += 1
        yield from turn.deltas

    def summarize(self, existing_summary, messages):
        self.summarize_calls.append(
            {"existing_summary": existing_summary, "messages": messages}
        )
        if callable(self._summarize_result):
            return self._summarize_result(existing_summary, messages)
        if self._summarize_result is not None:
            return self._summarize_result
        return f"摘要#{len(self.summarize_calls)}（压缩了 {len(messages)} 条消息）"


tc_delta = _tc_delta
