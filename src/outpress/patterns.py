"""Regex patterns and small text helpers used by the compressor."""

from __future__ import annotations

import re

# ANSI escape sequences: colors, cursor movement, erase-line, etc.
ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Common log timestamps (ISO8601, hh:mm:ss, syslog, and US-style dates).
TIMESTAMP_RE = re.compile(
    r"^\s*(?:"
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
    r"|\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"
    r"|\d{2}/\d{2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}"
    r")\s*"
)

# Stack traces (Python-flavoured, but the frame shape is common to many tools).
TRACEBACK_START = "Traceback (most recent call last):"
FRAME_RE = re.compile(r'^\s*File "[^"]+", line \d+, in ')
CAUSE_RE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Timeout)\b")

# Progress bars, spinners, and percentage counters.
PROGRESS_RE = re.compile(
    r"(\d{1,3}%"
    r"|\[\s*[=>#.\-+]{1,30}\s*\]"
    r"|\bETA\b"
    r"|\b\d+\s*/\s*\d+\b"
    r"|\b\d+(?:\.\d+)?\s*(?:[KMG]i?B|KB|MB|GB|B)\s*/s"
    r"|\b(?:downloading|installing|building|loading|processing|uploading)\b.{0,40}\d)"
)

# Spinner-only lines (ASCII and braille spinners).
SPINNER_RE = re.compile(
    r"^\s*[|/\\\-_+=⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷]+\s*$"
)

# Tokens that make otherwise-identical lines look different.
HASH_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")
ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")
NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
WS_RE = re.compile(r"\s+")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from *text*."""
    return ANSI_RE.sub("", text)


def normalize(line: str) -> str:
    """Reduce a line to a stable signature so repeated lines can be folded.

    Timestamps, hashes, addresses, and numbers are replaced with placeholders
    so that ``12:00:01 done 42`` and ``12:00:02 done 43`` collapse together.
    """
    s = strip_ansi(line)
    s = TIMESTAMP_RE.sub("", s)
    s = ADDR_RE.sub("<addr>", s)
    s = HASH_RE.sub("<hash>", s)
    s = NUM_RE.sub("<n>", s)
    s = WS_RE.sub(" ", s).strip()
    # Lines with almost no text (bare counters, numbered list items) must not
    # be folded together just because their numbers differ.
    if len(re.sub(r"[^a-z]", "", s)) < 2:
        return strip_ansi(line).strip()
    return s.lower()
