"""Command line interface for outpress."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import List, Optional, Tuple

from . import __version__
from .compressor import Stats, compress
from .runner import run


class Colors:
    """Tiny ANSI color helper that respects ``--no-color`` and non-tty output."""

    DIM = "\x1b[2m"
    BOLD = "\x1b[1m"
    RED = "\x1b[31m"
    YELLOW = "\x1b[33m"
    CYAN = "\x1b[36m"
    RESET = "\x1b[0m"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"{code}{text}{self.RESET}"

    def dim(self, text: str) -> str:
        return self._wrap(self.DIM, text)

    def bold(self, text: str) -> str:
        return self._wrap(self.BOLD, text)

    def red(self, text: str) -> str:
        return self._wrap(self.RED, text)

    def yellow(self, text: str) -> str:
        return self._wrap(self.YELLOW, text)

    def cyan(self, text: str) -> str:
        return self._wrap(self.CYAN, text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outpress",
        description="Compress noisy terminal output into a clean summary for AI agents.",
        epilog=(
            "examples:\n"
            "  outpress npm install\n"
            "  outpress --level minimal pytest -q\n"
            "  outpress --file build.log --stats\n"
            "  npm install 2>&1 | outpress\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run and compress. Everything after the command is passed through, "
             "so put outpress options before the command.",
    )
    parser.add_argument(
        "-f", "--file",
        help="Compress a log file instead of running a command.",
    )
    parser.add_argument(
        "-l", "--level",
        choices=["minimal", "normal", "verbose"],
        default="normal",
        help="Compression level (default: normal).",
    )
    parser.add_argument("--head", type=int, default=None, help="Keep only the first N lines.")
    parser.add_argument("--tail", type=int, default=None, help="Keep only the last N lines.")
    parser.add_argument("--max-lines", type=int, default=None, help="Cap total output lines.")
    parser.add_argument("--filter", metavar="REGEX", help="Drop lines matching this regex.")
    parser.add_argument("--keep", metavar="REGEX", help="Keep only lines matching this regex.")
    parser.add_argument("--stats", action="store_true", help="Show compression statistics.")
    parser.add_argument("--raw", action="store_true", help="Also print the raw output.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output.")
    parser.add_argument(
        "--shell",
        action="store_true",
        help="Run the command through the system shell (enables pipes and redirection).",
    )
    parser.add_argument("--timeout", type=float, default=None, help="Kill the command after N seconds.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _load_text(args: argparse.Namespace) -> Tuple[Optional[str], int, float, str]:
    """Return ``(text, exit_code, duration, command)`` or ``(None, ...)`` for help."""
    if args.file:
        with open(args.file, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(), 0, 0.0, args.file
    if args.command:
        result = run(args.command, timeout=args.timeout, shell=args.shell)
        return result.stdout + result.stderr, result.returncode, result.duration, result.command
    if not sys.stdin.isatty():
        return sys.stdin.read(), 0, 0.0, "<stdin>"
    return None, 0, 0.0, ""


def _render_header(command: str, stats: Stats, colors: Colors) -> str:
    pct = stats.reduction * 100
    return (
        f"{colors.cyan('outpress')} {colors.dim(command)}\n"
        f"{colors.dim('─' * 44)}\n"
        f"  {stats.raw_lines} lines → {stats.out_lines} lines"
        f"  ({pct:.0f}% smaller)\n\n"
    )


def _render_footer(stats: Stats, exit_code: int, duration: float, colors: Colors) -> str:
    status = colors.dim("exit 0") if exit_code == 0 else colors.red(f"exit {exit_code}")
    parts = [status]
    if duration:
        parts.append(colors.dim(f"{duration:.2f}s"))
    parts.append(colors.dim(f"{stats.folded_lines} folded"))
    if stats.progress_groups:
        parts.append(colors.dim(f"{stats.progress_groups} progress groups"))
    return f"\n{colors.dim('─' * 44)}\n  " + "  ·  ".join(parts) + "\n"


def _configure_stdout() -> None:
    """Use UTF-8 so box-drawing/arrow characters survive on Windows consoles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    colors = Colors(
        enabled=not args.no_color and not args.json and sys.stdout.isatty()
    )

    text, exit_code, duration, command = _load_text(args)
    if text is None:
        parser.print_help()
        return 0

    try:
        drop = re.compile(args.filter) if args.filter else None
        keep = re.compile(args.keep) if args.keep else None
    except re.error as exc:
        print(f"outpress: invalid regex: {exc}", file=sys.stderr)
        return 2

    lines, stats = compress(
        text,
        level=args.level,
        head=args.head,
        tail=args.tail,
        drop=drop,
        keep=keep,
        max_lines=args.max_lines,
    )

    if args.raw:
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.write("\n")

    output = "\n".join(lines)

    if args.json:
        payload = {
            "command": command,
            "exit_code": exit_code,
            "duration": round(duration, 3),
            "summary": output,
            "lines": lines,
            "stats": {
                "raw_lines": stats.raw_lines,
                "output_lines": stats.out_lines,
                "raw_bytes": stats.raw_bytes,
                "output_bytes": stats.out_bytes,
                "reduction": round(stats.reduction, 3),
                "progress_groups": stats.progress_groups,
                "folded_lines": stats.folded_lines,
                "dropped_lines": stats.dropped_lines,
            },
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return exit_code

    if args.stats:
        sys.stdout.write(_render_header(command, stats, colors))
    if output:
        sys.stdout.write(output + "\n")
    if args.stats:
        sys.stdout.write(_render_footer(stats, exit_code, duration, colors))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
