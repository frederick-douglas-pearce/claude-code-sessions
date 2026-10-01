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

  - A `toolDenialKind` string is printed if it fully matches ENUM_RE: a
    lowercase ASCII letter, then [a-z0-9_-], at most 40 characters in all.
    Any other string is printed as `<non-enum len=N>`, a JSON null as `<null>`,
    and any other type as `<other>`, never as itself. The bet is that a
    harness-supplied label is enum-shaped and user content almost never is.
    It is a bet about shape, not an attestation: a short lowercase string
    written into this field would be printed.
  - The `tool_result` text is NEVER printed. Its first TEXT_WINDOW characters
    are tested against MARKERS, and only the matching marker's NAME is counted.
  - `is_error` is printed only as `true`, `false`, `<null>`, `<absent>` or
    `<other>`.
  - `version` is printed only if it fully matches VERSION_RE (dotted ASCII
    digits).
  - Error messages never name a session file.
  - Nothing else from a line is read.

Bucket labels (`<null>`, `<other>`, `<absent>`, `<no-tool-result>`,
`<non-enum len=N>`) all start with `<`, which ENUM_RE cannot match, so a
printed value can never be mistaken for a bucket.

`lines_scanned` and `parse_errors` follow scan.py's rules, so `lines_scanned`
means what it means in a scan-*.json artifact: non-blank lines that parsed to a
JSON object. The default root, version ordering and `<other>` bucket label are
loaded from scan.py itself, next door.

tests/test_denial_kind_probe.py plants sentinels in every surface this probe
reads and asserts none reaches stdout or stderr in either output mode. It also
pins the one place the bar is weaker on purpose: an enum-shaped value is
printed.

Usage:
  python3 denial_kind.py [ROOT] [--json]

ROOT defaults to $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects.
Stdlib only, like scan.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

__version__ = "0.2.0"


def _load_scan():
    """Import the sibling scan.py by path (it is a script, not a package)."""
    path = Path(__file__).resolve().parent.parent / "scan.py"
    spec = importlib.util.spec_from_file_location("ccs_format_scan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = _load_scan()

ENUM_RE = re.compile(r"[a-z][a-z0-9_-]{0,39}", re.ASCII)
VERSION_RE = re.compile(r"\d+\.\d+\.\d+", re.ASCII)
TEXT_WINDOW = 300
NO_MARKER = "no-marker"
NO_TOOL_RESULT = "<no-tool-result>"

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


def fold_kind(value) -> str:
    if value is None:
        return "<null>"
    if isinstance(value, str):
        return value if ENUM_RE.fullmatch(value) else f"<non-enum len={len(value)}>"
    return scan.OTHER_BUCKET


def tool_result_blocks(line: dict) -> list[dict]:
    message = line.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def result_text(block: dict) -> str:
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


def is_error_label(block: dict) -> str:
    if "is_error" not in block:
        return "<absent>"
    value = block["is_error"]
    if value is None:
        return "<null>"
    if isinstance(value, bool):
        return json.dumps(value)
    return scan.OTHER_BUCKET


def probe(root: Path) -> dict:
    kinds: Counter = Counter()
    markers: dict[str, Counter] = defaultdict(Counter)
    is_error: dict[str, Counter] = defaultdict(Counter)
    multi_block: Counter = Counter()
    versions: dict[str, set] = defaultdict(set)
    files = lines = parse_errors = dropped = 0

    for path in sorted(root.rglob("*.jsonl")):
        files += 1
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        line = json.loads(raw)
                    except json.JSONDecodeError:
                        parse_errors += 1
                        continue
                    if not isinstance(line, dict):
                        continue
                    lines += 1
                    if "toolDenialKind" not in line:
                        continue
                    kind = fold_kind(line["toolDenialKind"])
                    kinds[kind] += 1
                    # Classify the first tool_result block. A line with more
                    # than one is counted in multi_tool_result_lines, which is
                    # what says whether "the first" was ever ambiguous.
                    blocks = tool_result_blocks(line)
                    if blocks:
                        markers[kind][match_marker(result_text(blocks[0]))] += 1
                        is_error[kind][is_error_label(blocks[0])] += 1
                        if len(blocks) > 1:
                            multi_block[kind] += 1
                    else:
                        markers[kind][NO_TOOL_RESULT] += 1
                        is_error[kind][NO_TOOL_RESULT] += 1
                    v = line.get("version")
                    if isinstance(v, str) and VERSION_RE.fullmatch(v):
                        versions[kind].add(v)
        except OSError:
            # Unreadable, vanished, or a directory named *.jsonl. Counted, and
            # never named: a session path is not ours to print.
            dropped += 1

    by_kind = {}
    for kind, n in kinds.most_common():
        vs = sorted(versions[kind], key=scan.version_sort_key)
        by_kind[kind] = {
            "lines": n,
            "first_version": vs[0] if vs else None,
            "last_version": vs[-1] if vs else None,
            "distinct_versions": len(vs),
            "is_error": dict(is_error[kind].most_common()),
            "markers": dict(markers[kind].most_common()),
            "multi_tool_result_lines": multi_block[kind],
        }
    return {
        "tool": "ccs-denial-kind-probe",
        "probe_version": __version__,
        "summary": {
            "files_scanned": files,
            "files_dropped": dropped,
            "lines_scanned": lines,
            "parse_errors": parse_errors,
            "tool_denial_lines": sum(kinds.values()),
        },
        "by_kind": by_kind,
    }


def print_human(report: dict) -> None:
    s = report["summary"]
    print(
        f"files={s['files_scanned']} dropped={s['files_dropped']} lines={s['lines_scanned']} "
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
        if row["multi_tool_result_lines"]:
            print(f"  lines with >1 tool_result (first block classified): {row['multi_tool_result_lines']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Name and classify toolDenialKind values (content-free).")
    parser.add_argument("root", nargs="?", type=Path, default=None, help="projects root (default: ~/.claude/projects)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    root = args.root or scan.default_root()
    if not root.is_dir():
        print("error: projects root is not a directory", file=sys.stderr)
        return 2
    report = probe(root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
