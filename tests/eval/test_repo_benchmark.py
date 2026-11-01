"""真实历史快照、冻结回归和仓库任务判分的集成契约。"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from zzhclaw.eval import ExternalValidator, load_benchmark
from zzhclaw.eval.verification import verify_benchmark
from zzhclaw.eval.workspace import WorkspaceManager

ROOT = Path(__file__).resolve().parents[2] / "benchmarks/python_repo"


def phase_summary(stdout):
    line = next(
        line
        for line in stdout.splitlines()
        if line.startswith("ZZHCLAW_REPO_VALIDATION ")
    )
    return json.loads(line.split(" ", 1)[1])


def test_source_snapshot_and_frozen_regression_are_original_bytes():
    source = json.loads((ROOT / "source.json").read_text())
    assert source["commit"] == "2ab74cee27b48a1241c0e7cdc0e2c5430087de5a"
    assert source["license"] == "MIT"
    assert len(source["files"]) == 42
    for name, digest in source["files"].items():
        path = ROOT / source["snapshot"] / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        if name.startswith("tests/"):
            frozen = ROOT / "validators/regression" / name.removeprefix("tests/")
            assert frozen.read_bytes() == path.read_bytes(), name
    assert "MIT License" in (ROOT / source["snapshot"] / "LICENSE").read_text()


def test_all_repo_tasks_fail_target_only_and_references_pass():
    benchmark = load_benchmark(ROOT / "benchmark.json")
    assert Counter(task.split for task in benchmark.tasks) == {"dev": 3, "test": 3}
    evidence = verify_benchmark(benchmark)
    assert evidence["all_verified"], evidence
    for row in evidence["results"]:
        assert phase_summary(row["baseline"]["stdout"]) == {
            "task": row["task_id"],
            "target": 1,
            "regression": 0,
        }
        assert phase_summary(row["reference"]["stdout"]) == {
            "task": row["task_id"],
            "target": 0,
            "regression": 0,
        }


def test_modifying_workspace_tests_does_not_change_external_oracle(tmp_path):
    benchmark = load_benchmark(ROOT / "benchmark.json")
    task = benchmark.task_by_id("repo-005")
    with WorkspaceManager(benchmark, tmp_path).prepare(task) as prepared:
        for path in (prepared.path / "tests").glob("*.py"):
            path.write_text("# test removal must not change external acceptance\n")
        (prepared.path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts='--collect-only'\n"
        )
        result = ExternalValidator(benchmark.root).run(task, prepared.path)
    assert result.exit_code == 1
    assert phase_summary(result.stdout) == {
        "task": task.id,
        "target": 1,
        "regression": 0,
    }
