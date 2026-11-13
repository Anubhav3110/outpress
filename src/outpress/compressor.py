"""Compression pipeline: turns noisy terminal output into an LLM-friendly summary.

The pipeline is a sequence of small, independent stages:

1. split raw text into logical lines (carriage-return redraws are kept apart)
2. collapse progress-bar / spinner update runs into a single line
3. trim long stack traces (dedupe frames, keep head and tail)
4. fold consecutive duplicate lines (after normalizing timestamps/numbers)
5. apply user ``--filter`` / ``--keep`` regexes
6. truncate to the level's line budget or the user's ``--head`` / ``--tail``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Pattern, Tuple

from .patterns import (
    CAUSE_RE,
    FRAME_RE,
    PROGRESS_RE,
    SPINNER_RE,
    TRACEBACK_START,
    normalize,
    strip_ansi,
)


@dataclass
class Line:
    """A single logical line of output."""

    text: str
    has_cr: bool = False
    redraws: Tuple[str, ...] = ()
    count: int = 1


@dataclass
class Stats:
    raw_lines: int = 0
    out_lines: int = 0
    raw_bytes: int = 0
    out_bytes: int = 0
    progress_groups: int = 0
    folded_lines: int = 0
    dropped_lines: int = 0

    @property
    def reduction(self) -> float:
        """Fraction of bytes removed, between 0.0 and 1.0."""
        if self.raw_bytes == 0:
            return 0.0
        return 1.0 - (self.out_bytes / self.raw_bytes)


DEFAULT_MAX_LINES = {"minimal": 20, "normal": 200, "verbose": 5000}


def _split(text: str) -> List[Line]:
    """Split on newlines, keeping carriage-return redraws as separate history."""
    lines: List[Line] = []
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()  # a trailing newline terminates the last line, not a new one
    for raw in raw_lines:
        parts = raw.split("\r")
        if len(parts) > 1:
            final = strip_ansi(parts[-1]).rstrip()
            redraws = tuple(strip_ansi(part) for part in parts[:-1])
            if not final.strip():
                # A trailing CR means the cursor rewound; recover the last content.
                for candidate in reversed(redraws):
                    if candidate.strip():
                        final = candidate.rstrip()
                        break
            lines.append(Line(text=final, has_cr=True, redraws=redraws))
        else:
            lines.append(Line(text=strip_ansi(parts[0]).rstrip()))
    return lines


def _is_progress(line: Line) -> bool:
    """Heuristic: does this line look like a progress-bar/spinner update?"""
    if line.has_cr:
        return True
    text = line.text
    if not text.strip():
        return False
    return bool(SPINNER_RE.match(text) or PROGRESS_RE.search(text))


def _collapse_progress(lines: List[Line]) -> Tuple[List[Line], int]:
    """Fold runs of progress updates into their final state plus a count."""
    out: List[Line] = []
    groups = 0
    i = 0
    n = len(lines)
    while i < n:
        if not _is_progress(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i
        last = lines[i]
        count = 1
        redraws = len(lines[i].redraws)
        while j + 1 < n and _is_progress(lines[j + 1]):
            j += 1
            last = lines[j]
            count += 1
            redraws += len(lines[j].redraws)
        text = last.text.strip()
        if not text:
            for candidate in reversed(last.redraws):
                if candidate.strip():
                    text = candidate.strip()
                    break
        updates = count + redraws
        if updates > 1:
            text = f"{text}  [collapsed {updates} progress updates]"
        out.append(Line(text=text))
        groups += 1
        i = j + 1
    return out, groups


def _is_traceback_body(text: str) -> bool:
    """Does *text* belong to the current traceback block?"""
    if not text.strip():
        return True
    if FRAME_RE.match(text):
        return True
    if text != text.lstrip():
        return True  # indented source line quoted under a frame
    if TRACEBACK_START in text:
        return True
    if CAUSE_RE.match(text):
        return False  # the exception message ends the block
    lowered = text.lower()
    return "handling" in lowered and "exception" in lowered


def _is_code_line(body: List[str], i: int) -> bool:
    if i >= len(body):
        return False
    text = body[i]
    return bool(text.strip()) and text != text.lstrip() and not FRAME_RE.match(text)


def _compress_traceback_body(body: List[str]) -> List[str]:
    """Dedupe repeated frames (recursion) and trim very long traces."""
    seen_frames = set()
    deduped: List[str] = []
    i = 0
    while i < len(body):
        text = body[i]
        if FRAME_RE.match(text):
            i += 1
            code: List[str] = []
            while _is_code_line(body, i):
                code.append(body[i])
                i += 1
            if text in seen_frames:
                continue
            seen_frames.add(text)
            deduped.append(text)
            deduped.extend(code)
            continue
        deduped.append(text)
        i += 1

    frame_positions = [idx for idx, t in enumerate(deduped) if FRAME_RE.match(t)]
    if len(frame_positions) <= 12:
        return deduped
    keep = 6
    omitted = len(frame_positions) - keep * 2
    drop_start = frame_positions[keep]
    drop_end = frame_positions[-keep]
    return (
        deduped[:drop_start]
        + [f"    ... {omitted} frames omitted ..."]
        + deduped[drop_end:]
    )


def _collapse_tracebacks(lines: List[Line]) -> List[Line]:
    out: List[Line] = []
    i = 0
    n = len(lines)
    while i < n:
        if TRACEBACK_START in lines[i].text:
            out.append(lines[i])
            i += 1
            body: List[str] = []
            while i < n and _is_traceback_body(lines[i].text):
                body.append(lines[i].text)
                i += 1
            out.extend(Line(text=t) for t in _compress_traceback_body(body))
            continue
        out.append(lines[i])
        i += 1
    return out


def _dedupe_lines(lines: List[Line]) -> Tuple[List[Line], int]:
    """Fold consecutive lines that share a normalized signature."""
    out: List[Line] = []
    folded = 0
    for line in lines:
        signature = normalize(line.text)
        if out and signature and signature == normalize(out[-1].text):
            out[-1].count += 1
            folded += 1
            continue
        out.append(Line(text=line.text, has_cr=line.has_cr, redraws=line.redraws))
    return out, folded


def _filter_lines(
    lines: List[Line],
    drop: Optional[Pattern[str]],
    keep: Optional[Pattern[str]],
) -> Tuple[List[Line], int]:
    out: List[Line] = []
    dropped = 0
    for line in lines:
        if keep is not None and not keep.search(line.text):
            dropped += 1
            continue
        if drop is not None and drop.search(line.text):
            dropped += 1
            continue
        out.append(line)
    return out, dropped


def _truncate(
    lines: List[Line],
    head: Optional[int] = None,
    tail: Optional[int] = None,
    max_lines: Optional[int] = None,
) -> List[Line]:
    total = len(lines)
    if head is not None:
        if total > head:
            return lines[:head] + [Line(text=f"... {total - head} lines omitted ...")]
        return lines
    if tail is not None:
        if total > tail:
            return [Line(text=f"... {total - tail} lines omitted ...")] + lines[-tail:]
        return lines
    if max_lines is not None and total > max_lines:
        keep = (max_lines - 1) // 2  # leave room for the omission marker
        omitted = total - keep * 2
        return lines[:keep] + [Line(text=f"... {omitted} lines omitted ...")] + lines[-keep:]
    return lines


def _render(line: Line) -> str:
    text = line.text
    if line.count > 1:
        text = f"{text}  (x{line.count})"
    return text


def compress(
    text: str,
    level: str = "normal",
    head: Optional[int] = None,
    tail: Optional[int] = None,
    drop: Optional[Pattern[str]] = None,
    keep: Optional[Pattern[str]] = None,
    max_lines: Optional[int] = None,
) -> Tuple[List[str], Stats]:
    """Compress *text* and return ``(lines, stats)``.

    ``level`` is one of ``minimal``, ``normal``, or ``verbose``. ``drop`` and
    ``keep`` are compiled regular expressions applied to each line.
    """
    stats = Stats(
        raw_lines=text.count("\n") + 1,
        raw_bytes=len(text.encode("utf-8")),
    )
    lines = _split(text)

    if level == "minimal":
        lines = [line for line in lines if line.text.strip()]

    lines, groups = _collapse_progress(lines)
    stats.progress_groups = groups

    lines = _collapse_tracebacks(lines)

    lines, folded = _dedupe_lines(lines)
    stats.folded_lines = folded

    if drop is not None or keep is not None:
        lines, dropped = _filter_lines(lines, drop, keep)
        stats.dropped_lines = dropped

    limit = max_lines if max_lines is not None else DEFAULT_MAX_LINES[level]
    lines = _truncate(lines, head=head, tail=tail, max_lines=limit)

    rendered = [_render(line) for line in lines]
    stats.out_lines = len(rendered)
    stats.out_bytes = len("\n".join(rendered).encode("utf-8"))
    return rendered, stats
