"""Tests for the outpress compressor pipeline."""

import re

from outpress.compressor import compress


def test_strips_ansi_codes():
    lines, _ = compress("\x1b[31mhello\x1b[0m\n")
    assert lines == ["hello"]


def test_dedupes_repeated_lines():
    lines, stats = compress("error: timeout\n" * 10)
    assert len(lines) == 1
    assert "(x10)" in lines[0]
    assert stats.folded_lines == 9


def test_normalizes_timestamps_and_numbers():
    text = "12:00:01 done 42\n12:00:02 done 43\n12:00:03 done 44\n"
    lines, _ = compress(text)
    assert len(lines) == 1
    assert "(x3)" in lines[0]


def test_collapses_progress_updates():
    text = "downloading 10%\rdownloading 20%\rdownloading 30%\ndone\n"
    lines, stats = compress(text)
    assert stats.progress_groups == 1
    assert any("downloading 30%" in line for line in lines)
    assert any("collapsed" in line for line in lines)


def test_collapses_spinner_lines():
    text = "|\n/\n-\n\\\nworking\n"
    lines, stats = compress(text)
    assert stats.progress_groups >= 1
    assert any("working" in line for line in lines)


def test_trims_long_stack_traces():
    frames = "\n".join(f'  File "file{i}.py", line {i}, in func' for i in range(50))
    text = "Traceback (most recent call last):\n" + frames + "\nValueError: boom\n"
    lines, _ = compress(text)
    assert any("Traceback" in line for line in lines)
    assert any("frames omitted" in line for line in lines)
    assert any("ValueError: boom" in line for line in lines)


def test_dedupes_repeated_stack_frames():
    frame = '  File "recurse.py", line 7, in f'
    text = (
        "Traceback (most recent call last):\n"
        + (frame + "\n    f()\n") * 20
        + "RecursionError: maximum recursion depth exceeded\n"
    )
    lines, _ = compress(text)
    assert sum(1 for line in lines if "recurse.py" in line) == 1
    assert any("RecursionError" in line for line in lines)


def test_filter_drops_matching_lines():
    lines, _ = compress("keep me\ndrop me\nkeep me too\n", drop=re.compile("drop"))
    assert lines == ["keep me", "keep me too"]


def test_keep_only_matching_lines():
    lines, _ = compress("error: a\ninfo: b\nerror: c\n", keep=re.compile("error"))
    assert lines == ["error: a", "error: c"]


def test_head_keeps_first_lines():
    lines, _ = compress("1\n2\n3\n4\n5\n", head=2)
    assert lines[:2] == ["1", "2"]
    assert any("omitted" in line for line in lines)


def test_tail_keeps_last_lines():
    lines, _ = compress("1\n2\n3\n4\n5\n", tail=2)
    assert lines[-2:] == ["4", "5"]
    assert any("omitted" in line for line in lines)


def test_minimal_level_caps_output():
    text = "\n".join(f"line {i}" for i in range(100))
    lines, _ = compress(text, level="minimal")
    assert len(lines) <= 20


def test_stats_reduction_is_sane():
    text = "same line\n" * 100
    _, stats = compress(text)
    assert 0.0 <= stats.reduction <= 1.0
    assert stats.out_lines == 1
