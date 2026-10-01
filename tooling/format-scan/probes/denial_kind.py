#!/usr/bin/env python3
"""denial_kind.py: what values does `toolDenialKind` take, and what kind of
denial does each one label?

A standalone probe, deliberately kept out of scan.py (issue #276). It reads raw
session transcripts and prints, per `toolDenialKind` value: how many lines carry
it, the Claude Code versions it was seen on, the `is_error` split of the
`tool_result` block on the same line, and which of a few FIXED phrases that
block's text matches.

OUTPUT CONTRACT: weaker than scan.py's, and that is why it lives here.

scan.py prints a value only if a committed fixture attests it, and folds
everything else to `<other>`. This probe exists to name the values the fold
would not, so it uses a weaker bar:

  - A `toolDenialKind` value is printed if it matches ENUM_RE: lowercase,
    [a-z0-9_-], at most 40 characters. Anything else is printed as
    `<non-enum len=N>` or `<TYPE>`, never as itself. The bet is that a
    harness-supplied label is enum-shaped and user content almost never is.
    It is a bet about shape, not an attestation: a short lowercase string
    written into this field would be printed.
  - The `tool_result` text is NEVER printed. Its first TEXT_WINDOW characters
    are tested against MARKERS, and only the matching marker's NAME is counted.
  - `version` is printed only if it matches VERSION_RE (dotted digits).
  - Nothing else from a line is read.

tests/test_denial_kind_probe.py plants sentinels in every surface this probe
reads and asserts none reaches stdout, in both output modes. It also pins the
one place the bar is weaker on purpose: an enum-shaped value is printed.

Usage:
  python3 denial_kind.py [ROOT] [--json]

ROOT defaults to $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects.
Stdlib only, like scan.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

__version__ = "0.1.0"

ENUM_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
TEXT_WINDOW = 300
NO_MARKER = "no-marker"

# Tested in order against the first TEXT_WINDOW characters of the tool_result
# text; first match wins. Only the NAME on the left is ever emitted. The order
# puts specific phrases ahead of the bare words they contain.
MARKERS = (
    ("hook-error-prefix", re.compile(r"^(Error: )?[A-Za-z]+(:[^\s]+)? hook error:")),
    ("user-declined", re.compile(r"user doesn't want to (proceed|take this action)", re.I)),
    ("blocked-by-hook-phrase", re.compile(r"blocked by\b.{0,80}\bhook", re.I)),
    ("has-been-denied-phrase", re.compile(r"has been denied", re.I)),
    ("permission-phrase", re.compile(r"permission", re.I)),
    ("denied-phrase", re.compile(r"denied", re.I)),
    ("blocked-phrase", re.compile(r"blocked", re.I)),
)


def default_root() -> Path:
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(cfg) if cfg else Path.home() / ".claude") / "projects"


def fold_kind(value) -> str:
    if isinstance(value, str):
        return value if ENUM_RE.match(value) else f"<non-enum len={len(value)}>"
    return f"<{type(value).__name__}>"


def first_tool_result(line: dict) -> dict | None:
    content = (line.get("message") or {}).get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return block
    return None


def result_text(block: dict | None) -> str:
    if block is None:
        return ""
    c = block.get("content")
    if isinstance(c, str):
        return c[:TEXT_WINDOW]
    if isinstance(c, list):
        for sub in c:
            if isinstance(sub, dict) and isinstance(sub.get("text"), str):
                return sub["text"][:TEXT_WINDOW]
    return ""


def match_marker(text: str) -> str:
    for name, rx in MARKERS:
        if rx.search(text):
            return name
    return NO_MARKER


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def probe(root: Path) -> dict:
    kinds: Counter = Counter()
    markers: dict[str, Counter] = defaultdict(Counter)
    is_error: dict[str, Counter] = defaultdict(Counter)
    versions: dict[str, set] = defaultdict(set)
    files = lines = parse_errors = 0

    for path in sorted(root.rglob("*.jsonl")):
        files += 1
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                lines += 1
                try:
                    line = json.loads(raw)
                except ValueError:
                    parse_errors += 1
                    continue
                if not isinstance(line, dict) or "toolDenialKind" not in line:
                    continue
                kind = fold_kind(line["toolDenialKind"])
                kinds[kind] += 1
                block = first_tool_result(line)
                markers[kind][match_marker(result_text(block))] += 1
                err = block.get("is_error") if block is not None else None
                is_error[kind][json.dumps(err) if isinstance(err, (bool, type(None))) else "<other>"] += 1
                v = line.get("version")
                if isinstance(v, str) and VERSION_RE.match(v):
                    versions[kind].add(v)

    by_kind = {}
    for kind, n in kinds.most_common():
        vs = sorted(versions[kind], key=_vkey)
        by_kind[kind] = {
            "lines": n,
            "first_version": vs[0] if vs else None,
            "last_version": vs[-1] if vs else None,
            "distinct_versions": len(vs),
            "is_error": dict(is_error[kind].most_common()),
            "markers": dict(markers[kind].most_common()),
        }
    return {
        "tool": "ccs-denial-kind-probe",
        "probe_version": __version__,
        "summary": {
            "files_scanned": files,
            "lines_scanned": lines,
            "parse_errors": parse_errors,
            "tool_denial_lines": sum(kinds.values()),
        },
        "by_kind": by_kind,
    }


def print_human(report: dict) -> None:
    s = report["summary"]
    print(
        f"files={s['files_scanned']} lines={s['lines_scanned']} "
        f"parse_errors={s['parse_errors']} toolDenialKind_lines={s['tool_denial_lines']}"
    )
    for kind, row in report["by_kind"].items():
        span = (
            f"{row['first_version']}..{row['last_version']} ({row['distinct_versions']} versions)"
            if row["first_version"]
            else "no version"
        )
        print(f"\n{kind}: {row['lines']}  seen {span}")
        print(f"  is_error: {row['is_error']}")
        print(f"  markers:  {row['markers']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", nargs="?", type=Path, default=None, help="projects root (default: ~/.claude/projects)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    root = args.root or default_root()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    report = probe(root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
