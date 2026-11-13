# outpress

**Terminal output compressor for AI agents.**

`outpress` sits between a terminal command and an LLM. It runs a command (or
reads a log), strips the noise that wastes context, and prints a compact
summary instead of the raw firehose.

```console
$ outpress npm install --stats
outpress npm install --stats
────────────────────────────────────────────
  248 lines → 9 lines  (96% smaller)

  added 12 packages, and audited 13 packages in 3s

  2 moderate severity vulnerabilities

  To address all issues, run:
  npm audit fix

────────────────────────────────────────────
  exit 0  ·  3.12s  ·  234 folded  ·  1 progress groups
```

## Why

LLM context is expensive, and most command output is noise:

- progress bars that redraw the same line 200 times
- stack traces with 40 identical frames
- log lines that repeat with only the timestamp changed
- ANSI color codes that eat tokens

`outpress` folds all of that into the few lines an agent actually needs.

## Install

```bash
pip install outpress
```

Or run it straight from a checkout:

```bash
pip install -e .
```

## Usage

Wrap any command (put `outpress` options **before** the command so they aren't
passed through):

```bash
outpress npm install
outpress --stats pytest -q
```

Or compress something that's already been piped:

```bash
npm install 2>&1 | outpress
```

Or compress a log file:

```bash
outpress --file build.log --stats
```

### Options

| Option | Description |
| --- | --- |
| `-l, --level` | `minimal` (≤20 lines), `normal` (≤200), `verbose` (≤5000). Default `normal`. |
| `--head N` | Keep only the first N lines. |
| `--tail N` | Keep only the last N lines. |
| `--max-lines N` | Cap total output lines. |
| `--filter REGEX` | Drop lines matching this regex. |
| `--keep REGEX` | Keep only lines matching this regex. |
| `--stats` | Show compression statistics and exit status. |
| `--raw` | Also print the raw output before the summary. |
| `--json` | Emit JSON (useful for piping into an agent). |
| `--no-color` | Disable colored output. |
| `--shell` | Run the command through the system shell. |
| `--timeout N` | Kill the command after N seconds. |

### Examples

```bash
# Only the important lines, nothing else
outpress --level minimal pytest -q

# Keep just the errors from a long log
outpress --file build.log --keep "ERROR|WARNING"

# Feed a command's output through the shell, then compress
outpress --shell "npm run build 2>&1 | tail -500"

# JSON for an agent to parse
outpress --json docker build -t myapp .
```

## How it works

The pipeline is a chain of small, independent stages:

1. **Split** — newlines become lines; carriage-return redraws are kept as
   history so progress updates can be recognized.
2. **Progress collapse** — runs of spinner/percentage/bar updates fold into
   their final state, annotated with how many updates were dropped.
3. **Stack-trace trim** — repeated frames are deduped; long traces keep the
   first and last few frames and note what was omitted.
4. **Dedupe** — consecutive lines that look the same after normalizing
   timestamps, hashes, addresses, and numbers fold into one line with a
   `(xN)` counter.
5. **Filter** — user `--filter` / `--keep` regexes drop or retain lines.
6. **Truncate** — the level's line budget (or `--head` / `--tail`) caps the
   output.

Exit codes are preserved: `outpress <cmd>` exits with the same code as
`<cmd>`, so it is safe to use in scripts.

## JSON output

```bash
$ outpress --json --stats python -c "print('hi')" 2>&1 | head -20
{
  "command": "python -c print('hi')",
  "exit_code": 0,
  "duration": 0.05,
  "summary": "hi",
  "lines": ["hi"],
  "stats": {
    "raw_lines": 2,
    "output_lines": 1,
    "raw_bytes": 3,
    "output_bytes": 2,
    "reduction": 0.333,
    "progress_groups": 0,
    "folded_lines": 0,
    "dropped_lines": 0
  }
}
```

## Development

```bash
git clone https://github.com/Anubhav3110/outpress.git
cd outpress
pip install -e . pytest
pytest
```

## License

[MIT](LICENSE)
