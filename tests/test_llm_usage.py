"""使用真实 SDK + 本地 HTTP transport 验证 usage，不调用远端模型。"""

import json
from dataclasses import replace

import httpx
import pytest
from openai import OpenAI

from zzhclaw.agent import Agent
from zzhclaw.ai import LLMClient
from zzhclaw.ai.usage import RequestPricing
from zzhclaw.eval import load_benchmark
from zzhclaw.eval.metrics import aggregate
from zzhclaw.eval.models import TaskRunResult, UsageMetrics
from zzhclaw.eval.recorder import TrajectoryRecorder


@pytest.fixture
def create_llm(monkeypatch):
    clients = []
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")

    def create(handler):
        monkeypatch.setattr(
            "zzhclaw.ai.client.OpenAI",
            lambda **kwargs: OpenAI(
                **kwargs,
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            ),
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="test-model",
        )
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.client.close()


def response(*, stream, content="完成", usage=True, input_tokens=100, output_tokens=20):
    data = {
        "id": "response-1",
        "object": "chat.completion",
        "created": 0,
        "model": "returned-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    if usage:
        data["usage"] = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    if not stream:
        return httpx.Response(200, json=data)
    chunks = [
        {
            "id": data["id"],
            "object": "chat.completion.chunk",
            "created": 0,
            "model": data["model"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
    ]
    if usage:
        chunks.append({**chunks[0], "choices": [], "usage": data["usage"]})
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        + "data: [DONE]\n\n",
    )


def test_stream_usage_only_chunk_and_price_snapshot(create_llm, monkeypatch):
    monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("OPENAI_OUTPUT_PRICE_PER_MILLION", "2")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream=True)

    llm = create_llm(handler)
    recorder = TrajectoryRecorder()
    assert [delta.content for delta in llm.chat_stream([], on_request=recorder)] == [
        "完成"
    ]
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert [event.event_type for event in recorder.events] == [
        "llm_request_start",
        "llm_request_end",
    ]
    end = recorder.events[-1]
    assert end.metadata["request_id"] == recorder.events[0].metadata["request_id"]
    assert end.metadata["response_model"] == "returned-model"
    assert end.metadata["pricing"] == {
        "input_per_million": 1,
        "output_per_million": 2,
        "currency": "USD",
    }
    assert end.duration_ms >= 0 and end.metadata["status"] == "succeeded"
    assert recorder.usage.input_tokens == 100
    assert recorder.usage.output_tokens == 20
    assert recorder.usage.estimated_cost == pytest.approx(0.00014)
    assert recorder.usage.request_count == recorder.usage.requests_with_usage == 1
    assert "test-key" not in json.dumps([event.to_dict() for event in recorder.events])


def test_agent_includes_summary_requests_and_resets_per_run(
    create_llm, session_manager
):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return response(
            stream=body["stream"], content="完成" if body["stream"] else "历史摘要"
        )

    session_manager.create_session()
    for index in range(35):
        session_manager.add_message("user", f"消息{index}")
    agent = Agent(
        llm=create_llm(handler), session_manager=session_manager, system_prompt=None
    )
    recorder = TrajectoryRecorder()
    assert agent.run("任务", on_event=recorder) == "完成"
    ends = [event for event in recorder.events if event.event_type == "llm_request_end"]
    assert [event.metadata["purpose"] for event in ends] == ["summary", "chat"]
    assert recorder.usage.request_count == 2
    assert recorder.usage.input_tokens == 200 and recorder.usage.output_tokens == 40
    assert recorder.usage.request_duration_ms == sum(
        event.duration_ms for event in ends
    )
    assert session_manager.current_session.current_branch.summary == "历史摘要"
    recorder = TrajectoryRecorder()
    agent.run("再运行", on_event=recorder)
    assert recorder.usage.request_count == 1
    assert len(bodies) == 3


def test_missing_usage_is_unknown_and_can_disable_stream_options(
    create_llm, monkeypatch
):
    monkeypatch.setenv("OPENAI_STREAM_USAGE", "false")

    def handler(request):
        assert "stream_options" not in json.loads(request.content)
        return response(stream=True, usage=False)

    recorder = TrajectoryRecorder()
    list(create_llm(handler).chat_stream([], on_request=recorder))
    assert recorder.usage.request_count == 1
    assert recorder.usage.requests_with_usage == 0
    assert recorder.usage.input_tokens is None
    assert recorder.usage.output_tokens is None
    assert recorder.usage.estimated_cost is None
    assert recorder.usage.request_duration_ms is not None


def test_failed_request_is_counted_and_has_no_fabricated_tokens(create_llm):
    def handler(request):
        return httpx.Response(
            503, json={"error": {"message": "offline", "type": "server_error"}}
        )

    recorder = TrajectoryRecorder()
    with pytest.raises(Exception, match="offline"):
        list(create_llm(handler).chat_stream([], on_request=recorder))
    assert recorder.events[-1].metadata["status"] == "failed"
    assert recorder.events[-1].error == "InternalServerError"
    assert recorder.usage.request_count == 1
    assert recorder.usage.request_duration_ms is not None
    assert recorder.usage.input_tokens is None


def test_closing_stream_records_cancellation(create_llm):
    llm = create_llm(lambda request: response(stream=True))
    recorder = TrajectoryRecorder()
    stream = llm.chat_stream([], on_request=recorder)
    next(stream)
    stream.close()
    assert recorder.events[-1].metadata["status"] == "cancelled"
    assert recorder.usage.request_count == 1
    assert recorder.usage.input_tokens is None
    assert recorder.usage.request_duration_ms is not None


def test_partial_request_prevents_incomplete_task_totals(create_llm):
    recorder = TrajectoryRecorder()
    llm = create_llm(lambda request: response(stream=True))
    list(llm.chat_stream([], on_request=recorder))
    recorder.record("llm_request_start", metadata={"request_id": "unfinished"})
    assert recorder.usage.request_count == 2
    assert recorder.usage.requests_with_usage == 1
    assert recorder.usage.request_duration_ms is None
    assert recorder.usage.input_tokens is None
    assert recorder.usage.estimated_cost is None


def test_non_stream_chat_and_raw_stream_both_count_once(create_llm):
    llm = create_llm(
        lambda request: response(stream=json.loads(request.content)["stream"])
    )
    recorder = TrajectoryRecorder()
    assert llm.chat([], on_request=recorder).choices[0].message.content == "完成"
    assert len(list(llm.chat([], stream=True, on_request=recorder))) == 2
    assert recorder.usage.request_count == 2
    assert recorder.usage.input_tokens == 200


@pytest.mark.parametrize(
    "input_price,output_price",
    [(None, "2"), ("1", None), ("nan", "1"), ("inf", "1"), ("-1", "1"), ("", "1")],
)
def test_invalid_prices_rejected_at_configuration_boundary(
    monkeypatch, input_price, output_price
):
    if input_price is not None:
        monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", input_price)
    if output_price is not None:
        monkeypatch.setenv("OPENAI_OUTPUT_PRICE_PER_MILLION", output_price)
    with pytest.raises(ValueError):
        RequestPricing.from_env()


def test_zero_prices_and_currency(monkeypatch):
    monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", "0")
    monkeypatch.setenv("OPENAI_OUTPUT_PRICE_PER_MILLION", "0")
    monkeypatch.setenv("OPENAI_PRICE_CURRENCY", "CNY")
    assert RequestPricing.from_env().estimate(100, 20) == 0
    assert RequestPricing.from_env().currency == "CNY"


def test_runner_saves_usage_and_report_keeps_unknown_or_mixed_currency(
    create_llm, tmp_path, monkeypatch
):
    from pathlib import Path

    from zzhclaw.eval.batch import BatchRunner
    from zzhclaw.eval.report import generate_report

    monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("OPENAI_OUTPUT_PRICE_PER_MILLION", "2")
    llm = create_llm(lambda request: response(stream=True))
    benchmark = load_benchmark(
        Path(__file__).resolve().parents[1] / "benchmarks/python_basic/benchmark.json"
    )
    task = benchmark.task_by_id("python-001")
    root = tmp_path / "run"
    outcome = BatchRunner(
        benchmark,
        root,
        lambda manager: Agent(llm=llm, session_manager=manager),
        model="test-model",
        task_ids=[task.id],
    ).run()
    summary = generate_report(root)
    assert summary == outcome["summary"]
    assert summary["input_tokens"] == 100
    assert summary["request_count"] == 1
    assert summary["estimated_cost"] == pytest.approx(0.00014)
    assert summary["currency"] == "USD"
    assert summary["token_usage_attempts"] == 1
    assert "request_count | 1" in (root / "report.md").read_text()
    result = TaskRunResult.from_dict(
        json.loads(next(root.glob("attempts/*/tasks/*/result.json")).read_text())
    )
    assert result.usage == UsageMetrics(
        input_tokens=100,
        output_tokens=20,
        estimated_cost=0.00014,
        currency="USD",
        request_count=1,
        request_duration_ms=result.usage.request_duration_ms,
        requests_with_usage=1,
    )
    manifest = json.loads((root / "manifest.json").read_text())
    rows = [{"result": replace(result, status="passed"), "events": []}]
    summary = aggregate(rows, manifest)
    assert summary["average_successful_input_tokens"] == 100
    assert summary["average_successful_estimated_cost"] == pytest.approx(0.00014)
    rows.append(
        {
            "result": replace(result, status="cancelled", usage=UsageMetrics()),
            "events": [],
        }
    )
    summary = aggregate(rows, manifest)
    assert summary["input_tokens"] is None and summary["estimated_cost"] is None
    assert summary["average_successful_input_tokens"] == 100
    assert (
        summary["token_usage_attempts"] == 1 and summary["observed_usage_attempts"] == 2
    )
    rows[1]["result"] = replace(result, usage=replace(result.usage, currency="CNY"))
    summary = aggregate(rows, manifest)
    assert summary["currency"] is None and summary["estimated_cost"] is None
    assert summary["input_tokens"] == 200


def test_summary_failure_is_observed_when_agent_continues(create_llm, session_manager):
    def handler(request):
        if not json.loads(request.content)["stream"]:
            return httpx.Response(
                503, json={"error": {"message": "summary unavailable"}}
            )
        return response(stream=True)

    session_manager.create_session()
    for index in range(35):
        session_manager.add_message("user", f"历史{index}")
    recorder = TrajectoryRecorder()
    agent = Agent(llm=create_llm(handler), session_manager=session_manager)
    assert agent.run("继续", on_event=recorder) == "完成"
    assert recorder.usage.request_count == 2
    assert recorder.usage.requests_with_usage == 1
    assert recorder.usage.input_tokens is None
    assert recorder.usage.request_duration_ms is not None
    ends = [event for event in recorder.events if event.event_type == "llm_request_end"]
    assert ends[0].metadata["purpose"] == "summary"
    assert ends[0].metadata["status"] == "failed"


@pytest.mark.network
def test_worker_subprocess_inherits_prices_and_returns_usage(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    from threading import Thread

    from zzhclaw.eval.cli import main

    bodies = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            data = response(stream=True).content
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("OPENAI_OUTPUT_PRICE_PER_MILLION", "2")
    monkeypatch.setenv("OPENAI_PRICE_CURRENCY", "CNY")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "0")
    root = tmp_path / "run"
    manifest = (
        Path(__file__).resolve().parents[1] / "benchmarks/python_basic/benchmark.json"
    )
    args = [
        "run",
        str(manifest),
        "--task",
        "python-001",
        "--task-timeout",
        "10",
        "--model",
        "test-model",
        "--output",
        str(root),
    ]
    try:
        assert main(args) == 1
        configuration = json.loads((root / "manifest.json").read_text())[
            "configuration"
        ]
        assert configuration["pricing"] == {
            "input_per_million": 1,
            "output_per_million": 2,
            "currency": "CNY",
        }
        assert configuration["stream_usage"] == "true"
        monkeypatch.setenv("OPENAI_INPUT_PRICE_PER_MILLION", "3")
        assert main([*args, "--resume"]) == 2  # 单价变化必须使用新运行目录。
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    directory = root / "attempts/repeat-001/tasks/python-001"
    result = TaskRunResult.from_dict(
        json.loads((directory / "result.json").read_text())
    )
    assert result.status == "failed"  # 模型正常回答，但未修复任务，Validator 拒绝。
    assert result.final_answer == "完成"
    assert result.usage.input_tokens == 100 and result.usage.output_tokens == 20
    assert result.usage.request_count == result.usage.requests_with_usage == 1
    assert result.usage.currency == "CNY"
    assert result.usage.estimated_cost == pytest.approx(0.00014)
    assert bodies[0]["stream_options"] == {"include_usage": True}
    assert len(bodies) == 1
    events = (directory / "trace.jsonl").read_text()
    assert "local-test-key" not in events
    assert "worker_timestamp" in events
