"""真实流式响应形状 ↔ FakeLLM 假设的一致性。

两层验证：
1. 静态：FakeLLM 造出的 delta 属性名必须是 openai SDK 类型里真实存在的字段；
2. 动态：有真实录制 fixture 时，用它的 chunk 序列端到端驱动 Agent。
fixture 缺失时动态部分跳过——录制需要出网（见 tests/record_real_stream.py）。
"""

import json
from pathlib import Path

import pytest
from fake_llm import delta, tc_delta
from stream_replay import RecordedLLM

from zzhclaw.agent import Agent
from zzhclaw.coding.session import SessionManager

FIXTURE = Path(__file__).parent / "fixtures" / "real_stream_shape.json"


def sdk_fields(class_name):
    from openai.types.chat import chat_completion_chunk as types

    return set(getattr(types, class_name).model_fields)


# ===== 静态：FakeLLM 的属性名必须真实存在 =====

def test_fake_delta_uses_real_sdk_field_names():
    sample = delta(
        content="hi",
        tool_calls=[tc_delta(0, call_id="call_1", name="read_file", arguments="{}")],
    )

    assert set(vars(sample)) <= sdk_fields("ChoiceDelta")
    tc = sample.tool_calls[0]
    assert set(vars(tc)) <= sdk_fields("ChoiceDeltaToolCall")
    assert set(vars(tc.function)) <= sdk_fields("ChoiceDeltaFunctionCall")


def test_fields_the_agent_reads_exist_in_the_sdk():
    """Agent 只读这几个名字；SDK 若改名，这里会红，而不是等到线上 getattr 拿到 None。"""
    assert {"content", "tool_calls"} <= sdk_fields("ChoiceDelta")
    assert {"id", "index", "function"} <= sdk_fields("ChoiceDeltaToolCall")
    assert {"name", "arguments"} <= sdk_fields("ChoiceDeltaFunctionCall")


# ===== 回放器的过滤语义与 LLMClient.chat_stream 一致 =====

def test_replay_skips_chunks_without_choices_and_with_null_delta():
    chunks = [
        {"choices": []},  # usage / 心跳尾包
        {"choices": [{"index": 0, "delta": None, "finish_reason": "stop"}]},
        {"choices": [{"index": 0, "delta": {"content": "第一段"}, "finish_reason": None}]},
    ]

    collected = list(RecordedLLM([{"chunks": chunks}]).chat_stream([], tools=None))

    assert [getattr(d, "content", None) for d in collected] == ["第一段"]


def test_fragmented_real_chunks_reassemble_into_one_tool_call(stub_tools, tmp_path):
    """按真实协议分片下发：首片段带 id+name，后续片段只带 arguments 碎片。"""
    fragments = [
        {"index": 0, "id": "call_9", "type": "function",
         "function": {"name": "write_file", "arguments": ""}},
        {"index": 0, "id": None, "type": None, "function": {"name": None, "arguments": '{"path"'}},
        {"index": 0, "id": None, "type": None, "function": {"name": None, "arguments": ': "x"}'}},
    ]
    tool_turn = [{"choices": [{"index": 0, "delta": {"tool_calls": [f]}, "finish_reason": None}]}
                 for f in fragments]
    final_turn = [{"choices": [{"index": 0, "delta": {"content": "写好了"}, "finish_reason": "stop"}]}]

    agent = Agent(
        llm=RecordedLLM([{"chunks": tool_turn}, {"chunks": final_turn}]),
        session_manager=SessionManager(storage_dir=str(tmp_path / "sessions")),
    )

    assert agent.run("写文件", confirm_tool=None) == "写好了"
    assert stub_tools.calls == [("write_file", {"path": "x"})]


# ===== 动态：真实录制回放 =====

@pytest.fixture(scope="module")
def payload():
    if not FIXTURE.exists():
        pytest.skip(
            f"缺少真实录制 fixture；能出网时运行 "
            f"PYTHONPATH=. .venv/bin/python tests/record_real_stream.py 生成 {FIXTURE.name}"
        )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_real_recorded_tool_arguments_are_valid_json(payload):
    """拼装后的 arguments 必须是合法 JSON，否则分片拼接逻辑与真实协议不匹配。"""
    for i, turn in enumerate(payload["turns"]):
        for tc in turn.get("tool_calls") or []:
            parsed = json.loads(tc["function"]["arguments"] or "{}")
            assert isinstance(parsed, dict), f"第 {i} 轮 {tc['function']['name']} 的参数不是 dict"


def test_real_chunks_drive_the_agent_loop(payload, stub_tools, tmp_path):
    """真实 chunk 喂给 Agent，解析出的工具名与参数应与录制时一致。"""
    agent = Agent(
        llm=RecordedLLM(payload["turns"]),
        session_manager=SessionManager(storage_dir=str(tmp_path / "sessions")),
    )

    agent.run(payload["user_prompt"], confirm_tool=None, max_iterations=len(payload["turns"]) + 2)

    expected = [tc for turn in payload["turns"] for tc in (turn.get("tool_calls") or [])]

    assert [name for name, _ in stub_tools.calls] == [tc["function"]["name"] for tc in expected]
    assert [args for _, args in stub_tools.calls] == [
        json.loads(tc["function"]["arguments"] or "{}") for tc in expected
    ]


def test_real_shape_stats_match_fake_llm_assumptions(payload):
    """录制时算出的形状统计必须支持 FakeLLM 的两条关键假设：
    片段总是带 index；name 出现在某个片段里（FakeLLM 只在首片段给）。"""
    for turn in payload["turns"]:
        shape = turn["shape"]
        if shape["tool_call_fragment_count"] == 0:
            continue
        assert shape["fragments_missing_index"] == 0, "真实片段缺 index，Agent 会把它们并到 0"
        assert shape["fragments_with_name"] >= len(shape["distinct_indexes"]), \
            "有工具调用却没有片段带 name"
