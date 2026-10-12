import json
from pathlib import Path

import pytest
from fake_llm import FakeLLM, tool_call

from zzhclaw.eval.cli import main, parser
from zzhclaw.eval.experiment import run_experiment

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks/python_basic/benchmark.json"


@pytest.fixture(autouse=True)
def do_not_reload_local_secrets(monkeypatch):
    monkeypatch.setattr("zzhclaw.eval.experiment.load_dotenv", lambda: False)


def test_missing_model_config_does_not_start_experiment(tmp_path):
    root = tmp_path / "run"
    assert main(["experiment", str(MANIFEST), "--output", str(root)]) == 2
    assert not root.exists()


def test_two_prompts_smoke_uses_same_model_and_dev_tasks(tmp_path, monkeypatch):
    import zzhclaw.ai

    monkeypatch.setenv("OPENAI_API_KEY", "fake-only-for-unit-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://invalid.example/v1")
    monkeypatch.setenv("OPENAI_MODEL_ID", "fake")
    calls = []

    def client(**kwargs):
        task = "python-001" if len(calls) % 2 == 0 else "python-009"
        module = "calculator.py" if task == "python-001" else "money.py"
        calls.append(kwargs)
        source = (MANIFEST.parent / "references" / task / module).read_text()
        return FakeLLM(
            [
                tool_call(
                    "write_file", json.dumps({"path": module, "content": source})
                ),
                "完成",
            ]
        )

    monkeypatch.setattr(zzhclaw.ai, "LLMClient", client)
    root = tmp_path / "experiment"
    arguments = ["experiment", str(MANIFEST), "--output", str(root)]
    assert main(arguments) == 0
    assert len(calls) == 4 and all(call["model"] == "fake" for call in calls)
    manifests = [
        json.loads((root / name / "manifest.json").read_text())
        for name in ("baseline", "candidate")
    ]
    assert manifests[0]["model"] == manifests[1]["model"] == "fake"
    assert manifests[0]["task_specs"] == manifests[1]["task_specs"]
    assert all(task["split"] == "dev" for task in manifests[0]["task_specs"])
    assert (
        manifests[0]["configuration"]["system_prompt_sha256"]
        != manifests[1]["configuration"]["system_prompt_sha256"]
    )
    assert (root / "comparison.md").is_file()
    assert (root / "candidate/failures.md").is_file()
    assert main(arguments + ["--resume"]) == 0 and len(calls) == 4
    assert main(arguments + ["--stage", "test", "--resume"]) == 2


def test_test_stage_selects_test_and_fixed_repeat_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-only-for-unit-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://invalid.example/v1")
    monkeypatch.setenv("OPENAI_MODEL_ID", "fake")
    args = parser().parse_args(
        [
            "experiment",
            str(MANIFEST),
            "--stage",
            "test",
            "--output",
            str(tmp_path / "run"),
        ]
    )
    seen = []

    def execute(arguments):
        seen.append(parser().parse_args(arguments))
        return 130

    assert run_experiment(args, run_command=execute) == 130
    assert (
        seen[0].split == "test" and seen[0].repeat == 3 and seen[0].max_iterations == 12
    )
    assert not seen[0].task


def test_failures_expose_validator_output_and_trace(tmp_path):
    from zzhclaw.agent import Agent
    from zzhclaw.eval import BatchRunner, load_benchmark
    from zzhclaw.eval.analysis import analyze_run

    root = tmp_path / "run"
    benchmark = load_benchmark(MANIFEST)
    BatchRunner(
        benchmark,
        root,
        lambda sm: Agent(llm=FakeLLM(["未修改"]), session_manager=sm),
        model="fake",
        task_ids=["python-001"],
    ).run()
    evidence = analyze_run(root)
    case = evidence["cases"][0]
    assert case["diagnostic"] == "no_tool_action"
    assert "ZeroDivisionError" in case["validator_output_tail"]
    assert (root / case["trace"]).is_file()
    assert main(["analyze", str(root)]) == 0
