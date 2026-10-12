import sys
from dataclasses import replace

import pytest

from zzhclaw.eval import (
    EvalTask,
    ExternalValidator,
    ValidatorConfig,
    ValidatorExecutionError,
)


def task(command, *, timeout=10, env=None):
    return EvalTask(
        id="task-1",
        title="任务",
        prompt="执行验收",
        workspace="fixtures/task-1",
        validator=ValidatorConfig(
            command=tuple(command),
            timeout_seconds=timeout,
            env=env or {},
        ),
    )


def test_validator_captures_success_failure_and_workspace_placeholder(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    validator = ExternalValidator(tmp_path)
    success = task(
        [
            sys.executable,
            "-c",
            "import os,sys; print(os.environ['TARGET']); sys.exit(0)",
        ],
        env={"TARGET": "{workspace}"},
    )

    passed = validator.run(success, workspace)
    failed = validator.run(
        replace(
            success,
            validator=ValidatorConfig((sys.executable, "-c", "raise SystemExit(3)")),
        ),
        workspace,
    )

    assert passed.exit_code == 0 and not passed.timed_out
    assert str(workspace) in passed.stdout
    assert failed.exit_code == 3 and not failed.timed_out


def test_validator_timeout_becomes_structured_result(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    validator = ExternalValidator(tmp_path)
    slow = task([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)

    result = validator.run(slow, workspace)

    assert result.timed_out is True
    assert result.exit_code is None
    assert result.duration_ms is not None and result.duration_ms >= 900


def test_validator_missing_command_is_execution_error(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    validator = ExternalValidator(tmp_path)

    with pytest.raises(ValidatorExecutionError, match="无法启动"):
        validator.run(task(["definitely-not-a-real-command-zzhclaw"]), workspace)


def test_validator_truncates_large_output(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    validator = ExternalValidator(tmp_path, output_limit=20)

    result = validator.run(
        task([sys.executable, "-c", "print('x' * 100)"]),
        workspace,
    )

    assert len(result.stdout) == 20
