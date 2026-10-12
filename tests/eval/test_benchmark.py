from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from zzhclaw.eval import load_benchmark
from zzhclaw.eval.cli import main
from zzhclaw.eval.verification import verify_benchmark

MANIFEST = (
    Path(__file__).resolve().parents[2] / "benchmarks/python_basic/benchmark.json"
)


def test_benchmark_coverage_and_split():
    benchmark = load_benchmark(MANIFEST)
    assert len(benchmark.tasks) == 30
    assert Counter(task.split for task in benchmark.tasks) == {
        "train": 6,
        "dev": 9,
        "test": 15,
    }
    assert {"bugfix", "implementation", "refactor", "multi-file"} <= {
        tag for task in benchmark.tasks for tag in task.tags
    }
    assert sum("multi-file" in task.tags for task in benchmark.tasks) == 5
    for task in benchmark.tasks:
        fixture = benchmark.fixture_path(task)
        assert not list(fixture.rglob("test_*.py"))
        assert not (fixture / "references").exists()


@pytest.mark.parametrize("task_id", [f"python-{index:03d}" for index in range(1, 31)])
def test_original_fails_and_reference_passes(task_id):
    benchmark = load_benchmark(MANIFEST)
    task = benchmark.task_by_id(task_id)
    evidence = verify_benchmark(replace(benchmark, tasks=(task,)))
    assert evidence["all_verified"], evidence["results"]


def test_verify_rejects_collection_error_as_baseline_failure(tmp_path):
    import json

    fixture = tmp_path / "fixtures/task-1"
    reference = tmp_path / "references/task-1"
    fixture.mkdir(parents=True)
    reference.mkdir(parents=True)
    (fixture / "module.py").write_text("x=0")
    (reference / "module.py").write_text("x=1")
    (tmp_path / "benchmark.json").write_text(
        json.dumps(
            {
                "name": "bad",
                "version": "1",
                "created_at": "2026-10-11",
                "task_file": "tasks.jsonl",
            }
        )
    )
    (tmp_path / "tasks.jsonl").write_text(
        json.dumps(
            {
                "id": "task-1",
                "title": "bad",
                "prompt": "test",
                "workspace": "fixtures/task-1",
                "validator": {"command": ["{python}", "-c", "raise SystemExit(2)"]},
            }
        )
    )
    evidence = verify_benchmark(load_benchmark(tmp_path / "benchmark.json"))
    assert not evidence["all_verified"]
    assert evidence["verified_count"] == 0


def test_verify_cli_writes_evidence_without_model(tmp_path):
    import json

    output = tmp_path / "audit.json"
    assert (
        main(["verify", str(MANIFEST), "--task", "python-001", "--output", str(output)])
        == 0
    )
    assert json.loads(output.read_text())["verified_count"] == 1


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import slug\ndef make_slug(text): return slug.slugify(text)\n", 0),
        (
            "from slug import slugify as _slugify\n"
            "def make_slug(text): return _slugify(text)\n",
            0,
        ),
        (
            "import re\ndef make_slug(text): "
            "return '-'.join(re.findall('[a-z0-9]+',text.lower()))\n",
            1,
        ),
    ],
)
def test_api_delegate_validator_accepts_import_styles_and_rejects_copy(
    tmp_path, source, expected
):
    from zzhclaw.eval.evaluator import ExternalValidator

    benchmark = load_benchmark(MANIFEST)
    task = benchmark.task_by_id("python-022")
    (tmp_path / "slug.py").write_bytes(
        (benchmark.root / "references/python-022/slug.py").read_bytes()
    )
    (tmp_path / "legacy.py").write_text(source)
    assert ExternalValidator(benchmark.root).run(task, tmp_path).exit_code == expected
