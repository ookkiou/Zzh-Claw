import json
from pathlib import Path

import pytest

from zzhclaw.eval.cli import parser
from zzhclaw.eval.cross_experiment import run_cross_experiment

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    monkeypatch.setattr("zzhclaw.eval.cross_experiment.load_dotenv", lambda: False)
    monkeypatch.setattr(
        "zzhclaw.eval.cross_experiment.executable_identity",
        lambda _: {"version": "aider test"},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fake-unit-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL_ID", "fake-model")


def test_cross_builds_matching_conditions_and_resume(tmp_path, monkeypatch):
    args = parser().parse_args(
        [
            "cross-experiment",
            str(ROOT / "benchmarks/python_challenge/benchmark.json"),
            "--output",
            str(tmp_path / "run"),
            "--aider-executable",
            "fake",
            "--split",
            "test",
            "--repeat",
            "3",
            "--task-timeout",
            "7",
        ]
    )
    calls = []

    def execute(argv):
        calls.append(argv)
        output = Path(argv[argv.index("--output") + 1])
        output.mkdir()
        (output / "summary.json").write_text(
            json.dumps({"status_counts": {"passed": 12}, "planned_attempts": 12})
        )
        (output / "manifest.json").write_text("{}")
        return 0

    monkeypatch.setattr("zzhclaw.eval.cross_experiment.analyze_run", lambda _: None)
    monkeypatch.setattr(
        "zzhclaw.eval.cross_experiment.comparison_markdown", lambda _: "comparison"
    )
    assert run_cross_experiment(args, run_command=execute) == 0
    assert len(calls) == 2
    for argv in calls:
        assert argv[argv.index("--split") + 1] == "test"
        assert argv[argv.index("--repeat") + 1] == "3"
        assert argv[argv.index("--task-timeout") + 1] == "7"
    args.resume = True
    args.repeat = 2
    with pytest.raises(ValueError, match="不一致"):
        run_cross_experiment(args, run_command=execute)


def test_cross_missing_configuration_fails_before_output(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    args = parser().parse_args(
        [
            "cross-experiment",
            str(ROOT / "benchmarks/python_challenge/benchmark.json"),
            "--output",
            str(tmp_path / "run"),
            "--aider-executable",
            "fake",
        ]
    )
    with pytest.raises(ValueError, match="OPENAI"):
        run_cross_experiment(args)
    assert not (tmp_path / "run").exists()
