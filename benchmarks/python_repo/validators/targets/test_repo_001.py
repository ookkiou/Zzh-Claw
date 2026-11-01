import shlex
import sys

import pytest

from zzhclaw.coding.tools import run_bash


@pytest.mark.parametrize("channel", [1, 2])
def test_non_utf8_preserves_output_and_exit_code(channel):
    command = shlex.join(
        [
            sys.executable,
            "-c",
            f"import os;os.write({channel},b'\\xffusable');raise SystemExit(7)",
        ]
    )
    result = run_bash(command)
    assert "usable" in result and "\ufffd" in result
    assert "(退出码: 7)" in result
    assert "codec can" not in result


def test_mixed_channels_are_both_visible():
    command = shlex.join(
        [
            sys.executable,
            "-c",
            "import os;os.write(1,b'alpha\\xff');os.write(2,b'beta\\xfe')",
        ]
    )
    result = run_bash(command)
    assert "alpha" in result and "beta" in result
