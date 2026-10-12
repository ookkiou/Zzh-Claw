"""检查每个任务的原始代码失败、参考实现通过，不调用模型。"""

from tempfile import TemporaryDirectory

from .batch import benchmark_digest
from .evaluator import ExternalValidator
from .models import utc_now_iso
from .workspace import WorkspaceManager


def reference_files(benchmark, task):
    root = (benchmark.root / "references" / task.id).resolve()
    if not root.is_relative_to(benchmark.root) or not root.is_dir():
        raise ValueError(f"参考实现缺失或路径越界: {task.id}")
    files = []
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError(f"参考实现不支持软链接: {path}")
        if path.is_file():
            files.append((path.relative_to(root), path))
    if not files:
        raise ValueError(f"参考实现为空: {task.id}")
    return files


def verify_benchmark(benchmark, *, on_progress=None):
    """每个 baseline 和 reference 各使用一个全新副本。"""
    fingerprint = benchmark_digest(benchmark)
    results = []
    with TemporaryDirectory(prefix="zzhclaw-verify-") as directory:
        manager = WorkspaceManager(benchmark, directory)
        validator = ExternalValidator(benchmark.root)
        for task in benchmark.tasks:
            files = reference_files(benchmark, task)
            with manager.prepare(task) as original:
                baseline = validator.run(task, original.path)
            with manager.prepare(task) as patched:
                for relative, source in files:
                    target = patched.path / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                reference = validator.run(task, patched.path)
            # pytest 的 2/3/4/5 分别是收集/内部/用法/未收集错误，不能当成有效失败。
            verified = (
                baseline.exit_code == 1
                and not baseline.timed_out
                and reference.exit_code == 0
                and not reference.timed_out
            )
            row = {
                "task_id": task.id,
                "split": task.split,
                "verified": verified,
                "baseline": baseline.to_dict(),
                "reference": reference.to_dict(),
            }
            results.append(row)
            if on_progress:
                on_progress(row)
    if benchmark_digest(benchmark) != fingerprint:
        raise ValueError("验收期间 benchmark 资源发生变化，请重新验证")
    return {
        "schema_version": 1,
        "benchmark": benchmark.identity,
        "benchmark_digest": fingerprint,
        "verified_at": utc_now_iso(),
        "task_count": len(results),
        "verified_count": sum(row["verified"] for row in results),
        "all_verified": bool(results) and all(row["verified"] for row in results),
        "results": results,
    }
