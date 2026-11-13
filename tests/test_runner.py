"""Tests for the command runner."""

import sys

from outpress.runner import run


def test_captures_stdout():
    result = run([sys.executable, "-c", "print('hello')"])
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_captures_stderr_and_exit_code():
    result = run(
        [sys.executable, "-c", "import sys; sys.stderr.write('bad'); sys.exit(3)"]
    )
    assert result.returncode == 3
    assert "bad" in result.stderr


def test_timeout_is_reported():
    result = run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=0.5,
    )
    assert result.timed_out is True
    assert result.returncode == 124


def test_shell_string_command():
    result = run("echo shell-ok", shell=True)
    assert result.returncode == 0
    assert "shell-ok" in result.stdout
