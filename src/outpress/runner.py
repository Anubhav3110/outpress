"""Run a command and capture its output."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Sequence, Union


@dataclass
class Result:
    stdout: str
    stderr: str
    returncode: int
    command: str
    duration: float = 0.0
    timed_out: bool = False


def _decode(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def run(
    command: Union[str, Sequence[str]],
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env=None,
    shell: bool = False,
) -> Result:
    """Run *command* and capture stdout/stderr.

    ``command`` may be a string (parsed by the shell when ``shell=True``) or a
    list of arguments. A timed-out command yields ``returncode`` 124 and
    ``timed_out`` set to True.
    """
    if isinstance(command, str):
        cmd_str = command
        use_shell = True if shell else True  # strings always go through the shell
        args: object = command
    else:
        cmd_str = " ".join(command)
        args = list(command)
        use_shell = shell

    start = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.run(
            args,
            shell=use_shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr)
        returncode = 124
        timed_out = True
    duration = time.perf_counter() - start

    return Result(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        command=cmd_str,
        duration=duration,
        timed_out=timed_out,
    )
