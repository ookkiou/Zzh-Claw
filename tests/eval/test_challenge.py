from pathlib import Path

from zzhclaw.eval import load_benchmark
from zzhclaw.eval.verification import verify_benchmark


def test_challenge_baselines_fail_and_references_pass():
    manifest = (
        Path(__file__).resolve().parents[2]
        / "benchmarks/python_challenge/benchmark.json"
    )
    benchmark = load_benchmark(manifest)
    assert len(benchmark.tasks) == 6
    assert len([t for t in benchmark.tasks if t.split == "dev"]) == 2
    evidence = verify_benchmark(benchmark)
    assert evidence["all_verified"], evidence
