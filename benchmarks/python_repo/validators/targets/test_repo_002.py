import json
import os
import shlex
import sys

import pytest

from zzhclaw.coding.tools import run_bash


@pytest.mark.parametrize(
    "key",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
        "custom_password",
        "CUSTOM_SECRET",
        "custom_api_key",
    ],
)
def test_credentials_are_not_inherited(key, monkeypatch):
    monkeypatch.setenv(key, "unit-test-fake-credential")
    command = shlex.join(
        [sys.executable, "-c", f"import os,json;print(json.dumps(os.getenv({key!r})))"]
    )
    assert json.loads(run_bash(command).strip()) is None
    assert os.environ[key] == "unit-test-fake-credential"


def test_regular_environment_is_retained(monkeypatch):
    monkeypatch.setenv("ZZHCLAW_CUSTOM_BUILD_FLAG", "development")
    monkeypatch.setenv("HTTPS_PROXY", "http://example.invalid:8080")
    keys = ["PATH", "HOME", "HTTPS_PROXY", "ZZHCLAW_CUSTOM_BUILD_FLAG"]
    command = shlex.join(
        [
            sys.executable,
            "-c",
            f"import os,json;print(json.dumps({{k:os.getenv(k) for k in {keys!r}}}))",
        ]
    )
    assert json.loads(run_bash(command)) == {k: os.getenv(k) for k in keys}
