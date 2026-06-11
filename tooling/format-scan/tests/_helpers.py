"""Shared helpers for the format-scan test suite.

Two jobs:

  - load ``scan.py`` as an importable module (it's a standalone script, not a
    package), so functional tests can call ``scan()``/``build_report()``
    directly.
  - build a synthetic ``~/.claude/projects/``-shaped tree in a tmp dir. Fixtures
    are ALWAYS synthetic — no test ever points the scanner at real session data
    (CLAUDE.md security posture). The builder takes the content verbatim so the
    security-contract test can plant known sentinels and assert they never
    surface in scanner output.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCAN_PY = Path(__file__).resolve().parent.parent / "scan.py"
BASELINE = Path(__file__).resolve().parent.parent / "baseline-v2.1.150.json"


def load_scan():
    """Import scan.py as a module via its file path (it has no package)."""
    spec = importlib.util.spec_from_file_location("ccs_format_scan", SCAN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, objects: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(obj) + "\n" for obj in objects),
        encoding="utf-8",
    )


def make_session(
    projects_root: Path,
    slug: str,
    session_id: str,
    *,
    lines: list[dict],
    subagent_traces: dict[str, list[dict]] | None = None,
    meta_manifests: dict[str, dict] | None = None,
    tool_results: dict[str, bytes] | None = None,
) -> Path:
    """Write one synthetic session into ``projects_root``.

    Layout mirrors real Claude Code on disk:

        <slug>/<session_id>.jsonl                       # parent transcript
        <slug>/<session_id>/subagents/<name>.jsonl      # subagent traces
        <slug>/<session_id>/subagents/<name>.meta.json  # manifest sidecars
        <slug>/<session_id>/tool-results/<name>         # externalized output

    ``meta_manifests`` maps a filename (e.g. ``agent-abc.meta.json``) to the dict
    written as its JSON body — values are written verbatim so a test can plant a
    sentinel inside ``description``/``worktreePath``. Returns the session dir.
    """
    slug_dir = projects_root / slug
    write_jsonl(slug_dir / f"{session_id}.jsonl", lines)
    session_dir = slug_dir / session_id

    if subagent_traces:
        for name, trace_lines in subagent_traces.items():
            write_jsonl(session_dir / "subagents" / name, trace_lines)
    if meta_manifests:
        sub = session_dir / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        for name, body in meta_manifests.items():
            (sub / name).write_text(json.dumps(body), encoding="utf-8")
    if tool_results:
        tr = session_dir / "tool-results"
        tr.mkdir(parents=True, exist_ok=True)
        for name, blob in tool_results.items():
            (tr / name).write_bytes(blob)

    return session_dir
