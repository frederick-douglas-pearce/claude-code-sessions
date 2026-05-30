"""Tests for Layer 1 path scrubbing (issue #21).

Covers PRD section 7:

  - Home dir replacement across the surfaces named in the issue body
    (``cwd``, ``tool_use.input.file_path``, ``toolUseResult.*`` paths).
  - Project-slug regex with backref preservation (the section-7 example).
  - Both slug and ``cwd`` surfaces scrubbed in the same pipeline run.
  - Cross-line consistency: the same real path maps to the same placeholder
    on line 1 and line N (PRD section 7 determinism property).
  - First-match-wins via declaration order, including a documented
    asymmetric case (specific-first vs general-first) and the dead-code
    duplicate-rule case.
  - Substitution table occurrence counts (sidecar input, PRD section 10).
  - Byte-identical output across two runs (determinism).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

from ccs_sanitize.config import Rule, load_config
from ccs_sanitize.pipeline import run_pipeline, serialize_line
from ccs_sanitize.rules.paths import build_path_transform
from ccs_sanitize.subtable import SubstitutionTable


# ----- helpers -----------------------------------------------------------


def _config(tmp_path: Path, body: str):
    """Write ``body`` to a temp config file and load it.

    Using ``load_config`` rather than direct ``Rule(...)`` construction is
    deliberate: it exercises the same compile path the CLI will use,
    including the I-3 replacement-leak guard. A test config that
    accidentally violated I-3 would fail to load -- which is the right
    signal.
    """
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return load_config(p)


def _run(rules: Iterable[Rule], lines: list[str]):
    """Build a path transform over ``rules`` and run the pipeline."""
    table = SubstitutionTable()
    transform = build_path_transform(tuple(rules), table)
    out, counts = run_pipeline(lines, transform=transform)
    return out, counts, table


# ----- home dir replacement across the issue-body surfaces ---------------


def test_home_dir_replaced_in_cwd_field(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    line = serialize_line({"type": "user", "cwd": "/home/fdpearce/proj"})
    out, _, table = _run(config.paths, [line])
    assert "/home/fdpearce" not in out[0]
    assert '"cwd":"/home/user/proj"' in out[0]
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].original == "/home/fdpearce"
    assert entries[0].replacement == "/home/user"
    assert entries[0].occurrences == 1


def test_home_dir_replaced_in_tool_use_input_file_path(tmp_path: Path) -> None:
    """``tool_use.input.file_path`` is a deeply nested string leaf -- this
    confirms the path transform composes with the structural walker rather
    than only seeing top-level fields."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    line = serialize_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "input": {"file_path": "/home/fdpearce/README.md"},
                    }
                ]
            },
        }
    )
    out, _, _ = _run(config.paths, [line])
    assert "/home/fdpearce" not in out[0]
    assert "/home/user/README.md" in out[0]


def test_home_dir_replaced_in_tool_use_result_paths(tmp_path: Path) -> None:
    """``toolUseResult.stdout`` and ``stderr`` are free-form bash output --
    the transform must scan their full content, not just exact-match."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    line = serialize_line(
        {
            "type": "user",
            "toolUseResult": {
                "stdout": "ran in /home/fdpearce/scripts",
                "stderr": "/home/fdpearce/err.log",
            },
        }
    )
    out, _, table = _run(config.paths, [line])
    assert "/home/fdpearce" not in out[0]
    assert "/home/user/scripts" in out[0]
    assert "/home/user/err.log" in out[0]
    # Same (original, replacement) seen twice -- one table entry, two occurrences.
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].occurrences == 2


# ----- regex backref: project-name preserved -----------------------------


def test_project_slug_regex_preserves_project_name(tmp_path: Path) -> None:
    """PRD section 7 example: scrub the username out of the slug while
    preserving the project name via a backref. Different project names yield
    different table entries -- the substring substitution shape, not a
    single-key mapping."""
    body = """
version: 1
paths:
  - match: "re:-home-fdpearce-([a-z0-9-]+)"
    replace: '-home-user-\\1'
"""
    config = _config(tmp_path, body)
    line = serialize_line(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "see -home-fdpearce-claude-code-sessions and -home-fdpearce-other-proj",
                    }
                ]
            },
        }
    )
    out, _, table = _run(config.paths, [line])
    assert "fdpearce" not in out[0]
    assert "-home-user-claude-code-sessions" in out[0]
    assert "-home-user-other-proj" in out[0]
    by_original = {e.original: e for e in table}
    assert (
        by_original["-home-fdpearce-claude-code-sessions"].replacement
        == "-home-user-claude-code-sessions"
    )
    assert (
        by_original["-home-fdpearce-other-proj"].replacement == "-home-user-other-proj"
    )


# ----- slug + cwd surfaces in the same run (issue AC) --------------------


def test_slug_and_cwd_surfaces_both_scrubbed_in_one_run(tmp_path: Path) -> None:
    """Issue AC: 'project slug surface (-home-USER-project) as well as the
    cwd surface (/home/USER/project)' -- both shapes must scrub coherently
    in the same pipeline run."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "re:-home-fdpearce-([a-z0-9-]+)"
    replace: '-home-user-\\1'
"""
    config = _config(tmp_path, body)
    line = serialize_line(
        {
            "type": "user",
            "cwd": "/home/fdpearce/claude-code-sessions",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": "see -home-fdpearce-claude-code-sessions and /home/fdpearce/notes",
                    }
                ]
            },
        }
    )
    out, _, table = _run(config.paths, [line])
    assert "fdpearce" not in out[0]
    assert "/home/user/claude-code-sessions" in out[0]
    assert "-home-user-claude-code-sessions" in out[0]
    assert "/home/user/notes" in out[0]
    by_original = {e.original: e for e in table}
    # Literal /home/fdpearce hit in cwd and in the text leaf.
    assert by_original["/home/fdpearce"].occurrences == 2
    # Slug regex fires once on the text leaf; cwd does not contain the slug
    # shape (no leading dash), so the regex rule doesn't run there.
    assert by_original["-home-fdpearce-claude-code-sessions"].occurrences == 1


# ----- cross-line consistency (PRD section 7 determinism) ----------------


def test_same_path_mapped_identically_across_lines(tmp_path: Path) -> None:
    """The substitution-table identity invariant: the same real path maps
    to the same placeholder on line 1 and line N. This is what lets the
    sanitizer operate one file at a time and still produce coherent output
    across a parent session + its subagent traces (PRD section 7)."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    lines = [
        serialize_line({"type": "user", "cwd": "/home/fdpearce/proj"}),
        serialize_line({"type": "user", "cwd": "/home/fdpearce/proj"}),
        serialize_line({"type": "user", "cwd": "/home/fdpearce/other"}),
    ]
    out, _, table = _run(config.paths, lines)
    assert all("/home/fdpearce" not in line for line in out)
    assert all("/home/user" in line for line in out)
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].occurrences == 3


# ----- first-match-wins ordering ----------------------------------------


def test_first_match_wins_more_specific_rule_first(tmp_path: Path) -> None:
    """A more specific rule declared first claims the longer match; the
    more general rule still fires elsewhere in the leaf. Each rule appears
    in the subtable with its own (original, replacement) entry."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce/secret"
    replace: "/home/REDACTED"
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    line = serialize_line(
        {"type": "user", "cwd": "/home/fdpearce/secret/a and /home/fdpearce/b"}
    )
    out, _, table = _run(config.paths, [line])
    assert "/home/REDACTED/a" in out[0]
    assert "/home/user/b" in out[0]
    by_original = {e.original: e for e in table}
    assert by_original["/home/fdpearce/secret"].replacement == "/home/REDACTED"
    assert by_original["/home/fdpearce"].replacement == "/home/user"


def test_first_match_wins_general_rule_first_blocks_specific(tmp_path: Path) -> None:
    """When the general rule is declared first, sequential application
    consumes its match before the more specific rule can fire. The specific
    rule's pattern no longer finds its substring anchor and silently never
    runs. This is the declaration-order semantic the module docstring
    documents (vs true leftmost-position alternation)."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "/home/fdpearce/secret"
    replace: "/home/REDACTED"
""",
    )
    line = serialize_line({"type": "user", "cwd": "/home/fdpearce/secret/a"})
    out, _, table = _run(config.paths, [line])
    assert "/home/user/secret/a" in out[0]
    assert "REDACTED" not in out[0]
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].original == "/home/fdpearce"


def test_duplicate_rules_second_silently_never_fires(tmp_path: Path) -> None:
    """Two identical rules: the second is dead code because the first's
    ``re.sub`` consumes every match. The subtable shows one entry, no
    conflict raised. Documented behavior, not a bug."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    line = serialize_line({"type": "user", "cwd": "/home/fdpearce/x"})
    out, _, table = _run(config.paths, [line])
    assert "/home/user/x" in out[0]
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].occurrences == 1


# ----- determinism --------------------------------------------------------


def test_two_runs_byte_identical(tmp_path: Path) -> None:
    """No randomness, no time-dependent state -- two pipeline runs over the
    same input produce identical bytes. This is the property that lets the
    fixture validator gate on the sanitizer output (PRD section 13)."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "re:-home-fdpearce-([a-z0-9-]+)"
    replace: '-home-user-\\1'
"""
    config = _config(tmp_path, body)
    lines = [
        serialize_line({"type": "user", "cwd": "/home/fdpearce/proj"}),
        serialize_line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "-home-fdpearce-proj-sub"}
                    ]
                },
            }
        ),
    ]
    out1, _, _ = _run(config.paths, lines)
    out2, _, _ = _run(config.paths, lines)
    assert out1 == out2


# ----- no-op paths --------------------------------------------------------


def test_non_matching_leaves_pass_through(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
""",
    )
    line = serialize_line(
        {
            "type": "user",
            "message": {"content": "no paths here"},
        }
    )
    out, _, table = _run(config.paths, [line])
    assert '"no paths here"' in out[0]
    assert list(table) == []


def test_empty_rules_is_identity(tmp_path: Path) -> None:
    """An empty ``paths:`` list (or omitted section) yields a transform that
    passes every leaf through unchanged. Useful for sanity-checking that
    the build factory doesn't require non-empty rules to be safe."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "cwd": "/home/fdpearce/proj"})
    out, _, table = _run(config.paths, [line])
    assert "/home/fdpearce/proj" in out[0]
    assert list(table) == []
