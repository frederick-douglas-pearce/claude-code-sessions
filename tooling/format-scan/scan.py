#!/usr/bin/env python3
"""Local observational scanner for Claude Code JSONL session-format drift.

Walks a Claude Code projects root (default ~/.claude/projects/) and reports the
*shape* of the session data on disk: which top-level `type` values appear, which
envelope keys appear (overall and per type), which content-block types appear,
which session subdirectories exist (e.g. subagents/, tool-results/), the file
shape inside tool-results/, the key set of the per-subagent `meta.json` manifest
sidecars, and which Claude Code `version` values produced the data. With
--baseline it diffs the observed taxonomy against a checked-in list of what
`reference/` already documents, so the delta is "undocumented drift" — exactly
the input the jsonl-format-watch queue wants.

SECURITY CONTRACT (read before editing — see CLAUDE.md "Security posture"):

    This tool reads raw, unsanitized session transcripts. It MUST NOT emit their
    contents. Everything this script prints is one of:

      - a structural KEY NAME (a JSON object key, e.g. "toolUseResult", or a
        top-level key of a subagent `meta.json` manifest)
      - a TAXONOMY ENUM that reference/ already publishes as a public value
        (the `type` field, content-block `type`, and the `version` string)
      - a VALUE JSON-TYPE drawn from the fixed, content-free vocabulary
        {str, int, float, bool, list, dict, null} — the *type* of a value, never
        the value itself (mirrors how keys_by_type and meta_json_keys describe
        what a key holds without revealing what it holds)
      - a COUNT, a SIZE in bytes, a file EXTENSION, or a DIRECTORY name

    It MUST NEVER emit a message value: no prompt text, no file contents, no
    command output, no tool inputs/results, no paths from inside the data, no
    UUIDs, no filenames-with-arbitrary-content. This bites hardest for the
    `meta.json` probe: its `description` and `worktreePath` keys carry free-text
    and filesystem-path PII, so the probe emits only those keys' NAMES, counts,
    and value JSON-types — never their string values. The whitelist of
    value-bearing fields is defined once in EMITTABLE_VALUE_FIELDS below; if you
    find yourself wanting to print anything else, stop — that is a leak, and it
    defeats the reason this scanner exists instead of `cat`.

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
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

# The ONLY message fields whose *values* may be emitted. Each is a public
# taxonomy enum already documented in reference/ — not user content. Do not add
# a field here without confirming its value space is a closed, content-free
# vocabulary (and update the SECURITY CONTRACT above if you do). Note that the
# meta.json manifest keys (agentType, description, toolUseId, worktreePath) are
# deliberately ABSENT: the probe reports their key names + value JSON-types, not
# their values — description/worktreePath carry PII and must never be printed.
EMITTABLE_VALUE_FIELDS = frozenset({"type", "version"})


def json_type(value) -> str:
    """Name the JSON type of a value, drawn from a fixed content-free vocabulary.

    Returns one of: null, bool, int, float, str, list, dict (or "<unknown>" for
    anything else). This is the ONLY thing the meta.json probe records about a
    value — never the value itself. bool is checked before int because Python's
    bool is an int subclass.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "<unknown>"

# --probe-tool-results hypothesis markers. The probe reports only how many
# tool_result contents CONTAIN each of these fixed strings (presence + count) —
# it never emits the content around a match. This lets us confirm the shape of
# the tool-results/ externalization wrapper (candidate F-001) without reading the
# spilled output (the wrapper carries a preview of real tool output, which IS
# content and must not be surfaced). Add hypotheses freely; they are strings WE
# supply, so testing for them leaks nothing.
PERSISTED_MARKERS = (
    "<persisted-output",
    "</persisted-output>",
    "persisted-output",
    "persisted_output",
    "Preview (first",
    "Preview of",
    "tool-results/",
    "characters truncated",
    "truncated",
    "saved to",
    "output exceeds",
    "[Tool",
)


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
        # Per-subagent meta.json manifest sidecars (subagents/*.meta.json).
        # Key NAMES + counts, and value JSON-TYPES per key — never values.
        self.meta_json_files = 0
        self.meta_json_parse_errors = 0
        self.meta_json_keys: Counter[str] = Counter()
        self.meta_json_key_types: defaultdict[str, Counter[str]] = defaultdict(Counter)

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
                elif child.name == "subagents":
                    self._ingest_subagent_meta(child)

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

    def _ingest_subagent_meta(self, subagents_dir: Path) -> None:
        """Probe each subagents/*.meta.json manifest for its top-level key shape.

        Records key NAMES + counts and value JSON-TYPES per key only. The values
        (notably `description` and `worktreePath`) are PII and are never read
        into anything that gets emitted — see the SECURITY CONTRACT.
        """
        for f in sorted(subagents_dir.glob("*.meta.json")):
            if not f.is_file():
                continue
            self.meta_json_files += 1
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    manifest = json.load(fh)
            except (OSError, json.JSONDecodeError):
                self.meta_json_parse_errors += 1
                continue
            if not isinstance(manifest, dict):
                continue
            for key, value in manifest.items():
                self.meta_json_keys[key] += 1
                self.meta_json_key_types[key][json_type(value)] += 1


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
        # Observed in the data but absent from the baseline — a hard signal: this
        # item exists in real sessions and reference/ hasn't documented it.
        known_set = set(known or [])
        return sorted(k for k in observed if k not in known_set)

    def removed_items(observed, known):
        # Documented in the baseline but absent from the scanned data — a softer
        # signal than new_*: a candidate removal/deprecation, but a documented
        # item can also be absent simply because this corpus (or a --max-files
        # sample) didn't happen to contain it. NOT computed for `versions`, which
        # is an open, ever-growing set rather than a closed vocabulary — you would
        # never expect a scan to contain every version reference/ has ever seen.
        observed_set = set(observed)
        return sorted(k for k in (known or []) if k not in observed_set)

    # Per category: new_* then removed_*, so a diff reads as additions then
    # candidate removals. `versions` is additive-only (see removed_items).
    return {
        "new_top_level_types": new_items(obs.top_level_types, baseline.get("top_level_types")),
        "removed_top_level_types": removed_items(
            obs.top_level_types, baseline.get("top_level_types")
        ),
        "new_top_level_keys": new_items(obs.top_level_keys, baseline.get("top_level_keys")),
        "removed_top_level_keys": removed_items(
            obs.top_level_keys, baseline.get("top_level_keys")
        ),
        "new_content_block_types": new_items(
            obs.content_block_types, baseline.get("content_block_types")
        ),
        "removed_content_block_types": removed_items(
            obs.content_block_types, baseline.get("content_block_types")
        ),
        "new_session_subdirs": new_items(obs.session_subdirs, baseline.get("session_subdirs")),
        "removed_session_subdirs": removed_items(
            obs.session_subdirs, baseline.get("session_subdirs")
        ),
        "new_meta_json_keys": new_items(obs.meta_json_keys, baseline.get("meta_json_keys")),
        "removed_meta_json_keys": removed_items(
            obs.meta_json_keys, baseline.get("meta_json_keys")
        ),
        "new_versions": new_items(obs.versions, baseline.get("versions")),
    }


# --- tool-results pointer probe ----------------------------------------------

# A bounded, vocabulary-anchored tag matcher: an angle-bracket tag of <=40 chars
# that contains "persist" or "output". This only ever yields the wrapper tag
# itself (e.g. "<persisted-output>"), never the content inside it.
_TAG_RE = re.compile(r"<[^>\n]{1,40}>")


def _iter_tool_result_strings(root: Path, max_files: int | None):
    """Yield the string content of each tool_result block. Content is consumed
    only for fixed-marker membership tests in probe_tool_results — never emitted.
    """
    files = 0
    for jsonl_path in sorted(root.rglob("*.jsonl")):
        if max_files is not None and files >= max_files:
            break
        files += 1
        try:
            with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message") if isinstance(obj, dict) else None
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            c = block.get("content")
                            if isinstance(c, str):
                                yield c
                            elif isinstance(c, list):
                                for part in c:
                                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                                        yield part["text"]
        except OSError:
            continue


def probe_tool_results(root: Path, max_files: int | None = None) -> dict:
    marker_counts: Counter[str] = Counter()
    persist_tags: Counter[str] = Counter()
    total = 0
    for text in _iter_tool_result_strings(root, max_files):
        total += 1
        for marker in PERSISTED_MARKERS:
            if marker in text:
                marker_counts[marker] += 1
        if "persist" in text or "Preview (first" in text:
            for tag in _TAG_RE.findall(text):
                low = tag.lower()
                if "persist" in low or "output" in low:
                    persist_tags[tag] += 1
    return {
        "tool_result_string_contents": total,
        "marker_counts": dict(marker_counts.most_common()),
        "persist_anchored_tags": dict(persist_tags.most_common()),
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
        "meta_json_keys": {
            "files": obs.meta_json_files,
            "parse_errors": obs.meta_json_parse_errors,
            "keys": dict(obs.meta_json_keys.most_common()),
            "key_types": {
                k: dict(c.most_common()) for k, c in sorted(obs.meta_json_key_types.items())
            },
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

    mj = report["meta_json_keys"]
    print("## subagents/ meta.json manifest keys\n")
    if mj["files"]:
        print(f"_{mj['files']} manifest(s) scanned, {mj['parse_errors']} parse error(s)._\n")
        for k, v in mj["keys"].items():
            types = mj["key_types"].get(k, {})
            type_str = ", ".join(f"{t}×{n}" for t, n in types.items())
            print(f"- `{k}` — {v} manifests ({type_str})")
        print()
    else:
        print("_no subagents/*.meta.json manifests observed_\n")

    table("Claude Code `version` values", report["versions"], "lines")

    if report["baseline_diff"] is not None:
        print("## Drift vs. baseline\n")
        diff = report["baseline_diff"]
        any_drift = any(diff.values())
        if not any_drift:
            print("_no drift — observed taxonomy matches the baseline (both directions)_\n")
        else:
            for label, items in diff.items():
                if items:
                    pretty = label.replace("_", " ")
                    print(f"- **{pretty}:** {', '.join('`' + i + '`' for i in items)}")
            if any(items for label, items in diff.items() if label.startswith("removed_")):
                print(
                    "\n_`removed` = documented in the baseline but not seen in this scan; "
                    "could be a real removal/deprecation, or just absent from this "
                    "corpus or --max-files sample._"
                )
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
    parser.add_argument(
        "--probe-tool-results",
        action="store_true",
        help="probe tool_result contents for the tool-results/ externalization wrapper "
        "(fixed-marker presence + counts only — no content emitted)",
    )
    args = parser.parse_args(argv)

    if args.probe_tool_results:
        result = probe_tool_results(args.root, max_files=args.max_files)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("# tool-results pointer probe\n")
            print(f"tool_result string contents scanned: {result['tool_result_string_contents']}\n")
            print("## Fixed-marker presence (count of tool_result contents containing each)\n")
            if result["marker_counts"]:
                for m, c in result["marker_counts"].items():
                    print(f"- `{m}` — {c}")
            else:
                print("_none of the hypothesis markers matched_")
            print("\n## Distinct persist/output-anchored tags observed\n")
            if result["persist_anchored_tags"]:
                for t, c in result["persist_anchored_tags"].items():
                    print(f"- `{t}` — {c}")
            else:
                print("_none_")
        return 0

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
