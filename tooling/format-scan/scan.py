#!/usr/bin/env python3
"""Local observational scanner for Claude Code JSONL session-format drift.

Walks a Claude Code projects root (default ~/.claude/projects/) and reports the
*shape* of the session data on disk: which top-level `type` values appear, which
envelope keys appear (overall and per type), which content-block types appear,
which session subdirectories exist (e.g. subagents/, tool-results/), the file
shape inside tool-results/, and which Claude Code `version` values produced the
data. With --baseline it diffs the observed taxonomy against a checked-in list
of what `reference/` already documents, so the delta is "undocumented drift" —
exactly the input the jsonl-format-watch queue wants.

SECURITY CONTRACT (read before editing — see CLAUDE.md "Security posture"):

    This tool reads raw, unsanitized session transcripts. It MUST NOT emit their
    contents. Everything this script prints is one of:

      - a structural KEY NAME (a JSON object key, e.g. "toolUseResult")
      - a TAXONOMY ENUM that reference/ already publishes as a public value
        (the `type` field, content-block `type`, and the `version` string)
      - a COUNT, a SIZE in bytes, a file EXTENSION, or a DIRECTORY name

    It MUST NEVER emit a message value: no prompt text, no file contents, no
    command output, no tool inputs/results, no paths from inside the data, no
    UUIDs, no filenames-with-arbitrary-content. The whitelist of value-bearing
    fields is defined once in EMITTABLE_VALUE_FIELDS below; if you find yourself
    wanting to print anything else, stop — that is a leak, and it defeats the
    reason this scanner exists instead of `cat`.

    The block_secret_reads.py hook deliberately does NOT block Bash from reading
    ~/.claude/projects/ (so this scanner and the sanitizer CLI work). That makes
    the no-values discipline this script's responsibility, not the hook's. The
    PostToolUse detect_secrets_in_output.py scanner is a backstop for credential
    patterns only — it will not catch arbitrary PII, so do not rely on it.

Cross-platform: stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

# The ONLY message fields whose *values* may be emitted. Each is a public
# taxonomy enum already documented in reference/ — not user content. Do not add
# a field here without confirming its value space is a closed, content-free
# vocabulary (and update the SECURITY CONTRACT above if you do).
EMITTABLE_VALUE_FIELDS = frozenset({"type", "version"})


def default_root() -> Path:
    """Claude Code projects root, honoring CLAUDE_CONFIG_DIR like Claude Code."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(cfg) if cfg else Path.home() / ".claude"
    return base / "projects"


class Observation:
    """Accumulates content-free structural facts across all scanned files."""

    def __init__(self) -> None:
        self.files_scanned = 0
        self.lines_scanned = 0
        self.parse_errors = 0
        self.top_level_types: Counter[str] = Counter()
        self.top_level_keys: Counter[str] = Counter()
        self.keys_by_type: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.content_block_types: Counter[str] = Counter()
        self.versions: Counter[str] = Counter()
        # Top-level keys seen on user lines that carry a tool_result block.
        # A new key here is the prime suspect for a tool-results/ sidecar pointer.
        self.tool_result_line_keys: Counter[str] = Counter()
        # Directory shape.
        self.session_subdirs: Counter[str] = Counter()
        self.tool_results_extensions: Counter[str] = Counter()
        self.tool_results_sizes: list[int] = []
        self.tool_results_name_prefixes: Counter[str] = Counter()
        self.sessions_with_subdir_dir = 0

    # --- line-level ingestion -------------------------------------------------

    def ingest_line(self, obj: dict) -> None:
        if not isinstance(obj, dict):
            return
        self.lines_scanned += 1

        line_type = obj.get("type")
        type_label = line_type if isinstance(line_type, str) else "<no-type>"
        self.top_level_types[type_label] += 1

        for key in obj.keys():
            self.top_level_keys[key] += 1
            self.keys_by_type[type_label][key] += 1

        if isinstance(line_type, str) and "type" in EMITTABLE_VALUE_FIELDS:
            pass  # type already recorded as the label above

        version = obj.get("version")
        if isinstance(version, str):
            self.versions[version] += 1

        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        bt = block.get("type")
                        if isinstance(bt, str):
                            self.content_block_types[bt] += 1
                        # Detect tool_result-bearing user lines for pointer hunt.
                        if bt == "tool_result":
                            for key in obj.keys():
                                self.tool_result_line_keys[key] += 1

    # --- directory-level ingestion -------------------------------------------

    def ingest_session_dir(self, session_dir: Path) -> None:
        """Record the child directories of a <session-uuid>/ directory."""
        self.sessions_with_subdir_dir += 1
        for child in session_dir.iterdir():
            if child.is_dir():
                self.session_subdirs[child.name] += 1
                if child.name == "tool-results":
                    self._ingest_tool_results(child)

    def _ingest_tool_results(self, tr_dir: Path) -> None:
        for f in tr_dir.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lstrip(".") or "<none>"
            self.tool_results_extensions[ext] += 1
            try:
                self.tool_results_sizes.append(f.stat().st_size)
            except OSError:
                pass
            # Prefix = chars before the first underscore or dot. This is a
            # tool-kind label (toolu, mcp-github-list, ...), not content.
            stem = f.name
            for sep in ("_", "."):
                idx = stem.find(sep)
                if idx != -1:
                    stem = stem[:idx]
            self.tool_results_name_prefixes[stem] += 1


def scan(root: Path, obs: Observation, max_files: int | None = None) -> None:
    if not root.exists():
        print(f"error: projects root does not exist: {root}", file=sys.stderr)
        sys.exit(2)

    # 1) Parse every .jsonl (parent sessions + subagent traces) for line shape.
    for jsonl_path in sorted(root.rglob("*.jsonl")):
        if max_files is not None and obs.files_scanned >= max_files:
            break
        obs.files_scanned += 1
        try:
            with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        obs.parse_errors += 1
                        continue
                    obs.ingest_line(obj)
        except OSError:
            continue

    # 2) Inventory <session-uuid>/ directories for subdir shape. A session dir
    #    is a directory whose name matches a sibling "<name>.jsonl" parent file.
    for slug_dir in root.iterdir() if root.is_dir() else []:
        if not slug_dir.is_dir():
            continue
        for child in slug_dir.iterdir():
            if child.is_dir() and (slug_dir / f"{child.name}.jsonl").exists():
                obs.ingest_session_dir(child)


# --- baseline diff -----------------------------------------------------------


def load_baseline(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def diff_against_baseline(obs: Observation, baseline: dict) -> dict:
    def new_items(observed, known):
        known_set = set(known or [])
        return sorted(k for k in observed if k not in known_set)

    return {
        "new_top_level_types": new_items(obs.top_level_types, baseline.get("top_level_types")),
        "new_top_level_keys": new_items(obs.top_level_keys, baseline.get("top_level_keys")),
        "new_content_block_types": new_items(
            obs.content_block_types, baseline.get("content_block_types")
        ),
        "new_session_subdirs": new_items(obs.session_subdirs, baseline.get("session_subdirs")),
        "new_versions": new_items(obs.versions, baseline.get("versions")),
    }


# --- reporting ---------------------------------------------------------------


def size_summary(sizes: list[int]) -> dict:
    if not sizes:
        return {}
    return {
        "count": len(sizes),
        "min": min(sizes),
        "median": int(statistics.median(sizes)),
        "max": max(sizes),
    }


def build_report(obs: Observation, diff: dict | None) -> dict:
    return {
        "summary": {
            "files_scanned": obs.files_scanned,
            "lines_scanned": obs.lines_scanned,
            "parse_errors": obs.parse_errors,
            "session_dirs_with_subdirectories": obs.sessions_with_subdir_dir,
        },
        "top_level_types": dict(obs.top_level_types.most_common()),
        "top_level_keys": dict(obs.top_level_keys.most_common()),
        "keys_by_type": {t: dict(c.most_common()) for t, c in sorted(obs.keys_by_type.items())},
        "content_block_types": dict(obs.content_block_types.most_common()),
        "tool_result_line_keys": dict(obs.tool_result_line_keys.most_common()),
        "session_subdirs": dict(obs.session_subdirs.most_common()),
        "tool_results": {
            "extensions": dict(obs.tool_results_extensions.most_common()),
            "name_prefixes": dict(obs.tool_results_name_prefixes.most_common()),
            "size_bytes": size_summary(obs.tool_results_sizes),
        },
        "versions": dict(obs.versions.most_common()),
        "baseline_diff": diff,
    }


def print_human(report: dict) -> None:
    s = report["summary"]
    print("# JSONL format scan\n")
    print(
        f"Scanned {s['files_scanned']} files / {s['lines_scanned']} lines "
        f"({s['parse_errors']} parse errors). "
        f"{s['session_dirs_with_subdirectories']} session dirs have subdirectories.\n"
    )

    def table(title: str, mapping: dict, value_label: str = "count") -> None:
        print(f"## {title}\n")
        if not mapping:
            print("_none observed_\n")
            return
        for k, v in mapping.items():
            print(f"- `{k}` — {v} {value_label}")
        print()

    table("Top-level `type` values", report["top_level_types"], "lines")
    table("Top-level envelope keys", report["top_level_keys"], "lines")
    table("Content-block `type` values", report["content_block_types"], "blocks")
    table("Top-level keys on tool_result-bearing user lines", report["tool_result_line_keys"], "lines")
    table("Session subdirectories", report["session_subdirs"], "sessions")

    tr = report["tool_results"]
    print("## tool-results/ file shape\n")
    if tr["size_bytes"]:
        sz = tr["size_bytes"]
        print(f"- files: {sz['count']}  |  size bytes: min={sz['min']} median={sz['median']} max={sz['max']}")
        print(f"- extensions: {tr['extensions']}")
        print(f"- name prefixes: {tr['name_prefixes']}\n")
    else:
        print("_no tool-results/ files observed_\n")

    table("Claude Code `version` values", report["versions"], "lines")

    if report["baseline_diff"] is not None:
        print("## Drift vs. baseline (undocumented observations)\n")
        diff = report["baseline_diff"]
        any_drift = any(diff.values())
        if not any_drift:
            print("_no drift — everything observed is in the baseline_\n")
        for label, items in diff.items():
            if items:
                pretty = label.replace("new_", "new ").replace("_", " ")
                print(f"- **{pretty}:** {', '.join('`' + i + '`' for i in items)}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=default_root(),
        help="Claude Code projects root (default: ~/.claude/projects or $CLAUDE_CONFIG_DIR/projects)",
    )
    parser.add_argument("--baseline", type=Path, help="JSON baseline to diff observed taxonomy against")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a human report")
    parser.add_argument("--max-files", type=int, help="stop after N jsonl files (sampling)")
    args = parser.parse_args(argv)

    obs = Observation()
    scan(args.root, obs, max_files=args.max_files)

    diff = None
    if args.baseline:
        diff = diff_against_baseline(obs, load_baseline(args.baseline))

    report = build_report(obs, diff)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
