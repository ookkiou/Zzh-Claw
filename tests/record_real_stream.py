"""一次性录制真实流式 chunk 的形状，落成离线 fixture。

用途：验证 FakeLLM 对 OpenAI 流式协议的假设是否成立，并把真实形状固化为回归基线。
手动运行（会产生真实请求）：
    .venv/bin/python tests/record_real_stream.py

产物：tests/fixtures/real_stream_shape.json —— 之后的回放测试完全离线。
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from zzhclaw.ai import LLMClient
from zzhclaw.coding.tools import get_tools_with_cwd, execute_tool, set_cwd

OUT = Path(__file__).parent / "fixtures" / "real_stream_shape.json"

USER_PROMPT = (
    "请调用 read_file 工具读取 note.txt，然后用一句话告诉我文件里写了什么。"
    "必须通过工具调用获取内容，不要凭空猜测。"
)


def record_turn(llm, messages, tools):
    """原样录下每一个 chunk 的 model_dump，并顺带做形状统计。"""
    stream = llm.client.chat.completions.create(
        model=llm.model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        stream=True,
    )
    chunks = []
    for chunk in stream:
        chunks.append(chunk.model_dump(exclude_none=False))

    shape = analyse(chunks)
    content, tool_calls = assemble(chunks)
    return {"chunks": chunks, "shape": shape, "content": content, "tool_calls": tool_calls}


def analyse(chunks):
    """把 FakeLLM 的假设逐条拿去对照真实数据。"""
    deltas = [c["choices"][0]["delta"] for c in chunks if c.get("choices")]
    stats = {
        "chunk_count": len(chunks),
        "chunks_without_choices": sum(1 for c in chunks if not c.get("choices")),
        "delta_count": len(deltas),
        "deltas_missing_content_attr": sum(1 for d in deltas if "content" not in d),
        "deltas_with_nonempty_content": sum(1 for d in deltas if d.get("content")),
        "deltas_with_tool_calls": sum(1 for d in deltas if d.get("tool_calls")),
        "deltas_with_both_content_and_tool_calls": sum(
            1 for d in deltas if d.get("content") and d.get("tool_calls")
        ),
        "reasoning_content_seen": any("reasoning_content" in d for d in deltas),
    }
    tc_fragments = [tc for d in deltas for tc in (d.get("tool_calls") or [])]
    stats["tool_call_fragment_count"] = len(tc_fragments)
    stats["fragments_missing_index"] = sum(1 for tc in tc_fragments if tc.get("index") is None)
    stats["fragments_with_id"] = sum(1 for tc in tc_fragments if tc.get("id"))
    stats["fragments_with_name"] = sum(
        1 for tc in tc_fragments if (tc.get("function") or {}).get("name")
    )
    stats["fragments_with_empty_arguments"] = sum(
        1 for tc in tc_fragments if (tc.get("function") or {}).get("arguments") in ("", None)
    )
    stats["arguments_fragment_lengths"] = [
        len((tc.get("function") or {}).get("arguments") or "") for tc in tc_fragments
    ]
    stats["distinct_indexes"] = sorted({tc.get("index") for tc in tc_fragments}, key=str)
    stats["finish_reasons"] = [
        c["choices"][0].get("finish_reason") for c in chunks if c.get("choices")
    ][-3:]
    return stats


def assemble(chunks):
    """复刻 Agent 的累积逻辑，得到本轮真实产生的 content / tool_calls。"""
    content_parts = []
    acc = {}
    for c in chunks:
        if not c.get("choices"):
            continue
        delta = c["choices"][0]["delta"] or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index") if tc.get("index") is not None else 0
            slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]
    tool_calls = [
        {"id": acc[i]["id"], "type": "function",
         "function": {"name": acc[i]["name"], "arguments": acc[i]["arguments"]}}
        for i in sorted(acc) if acc[i]["name"]
    ]
    return "".join(content_parts), (tool_calls or None)


def main():
    workdir = tempfile.mkdtemp(prefix="zzhclaw-record-")
    Path(workdir, "note.txt").write_text("锚点文本：七号浮标处于待命状态。", encoding="utf-8")
    resolved = set_cwd(workdir)
    if not os.path.isdir(resolved):
        sys.exit(f"工作目录设置失败: {resolved}")

    llm = LLMClient()
    tools = get_tools_with_cwd()
    print(f"model={llm.model}  工具数={len(tools)}  cwd={resolved}")

    messages = [{"role": "user", "content": USER_PROMPT}]
    turn1 = record_turn(llm, messages, tools)
    print("turn1 shape:", json.dumps(turn1["shape"], ensure_ascii=False, indent=2))

    payload = {"model": llm.model, "user_prompt": USER_PROMPT, "turns": [turn1]}

    if turn1["tool_calls"]:
        for tc in turn1["tool_calls"]:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                result = execute_tool(name, args)
            except Exception as exc:  # noqa: BLE001 - 录制脚本，异常也原样记录
                result = f"录制脚本内工具异常: {type(exc).__name__}: {exc}"
            messages.append({
                "role": "assistant", "content": turn1["content"],
                "tool_calls": [tc],
            })
            messages.append({"role": "tool", "content": result, "tool_call_id": tc["id"]})
        payload["turns"].append(record_turn(llm, messages, tools))
        print("turn2 recorded")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT}（{OUT.stat().st_size} 字节）")


if __name__ == "__main__":
    main()
