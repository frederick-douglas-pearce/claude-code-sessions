"""Tests for Layer 2 identifier scrubbing (issue #22).

Covers PRD section 8:

  - Email replacement (exact + catch-all regex) across multiple lines, with
    first-match-wins ordering placing the specific replacement before the
    catch-all.
  - ``gitBranch`` field substitution with ``scrub_git_branch`` on/off
    semantics, including the empty-string passthrough (not-in-a-repo
    signal) and the field-anchored vs identifier-regex precedence.
  - UUID remap off (default): UUID-graph fields never reach the transform
    (pipeline skip-list filters them out). UUID remap on: ``parentUuid →
    uuid`` links resolve after remap, ``sessionId`` shared key stays
    shared, and ``toolUseResult.agentId`` remaps to the same value as a
    top-level ``agentId`` for the same input (the parent↔subagent link).
  - Determinism: byte-identical output AND table-snapshot equality across
    two runs.
  - Substitution-table counts feed sidecar reporting (per-mapping
    occurrence counts).
  - Composition: paths + identifiers run together with one shared
    substitution table, demonstrating layer ordering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

from ccs_sanitize.config import Rule
from ccs_sanitize.pipeline import (
    JsonPath,
    make_skip_predicate,
    run_pipeline,
    serialize_line,
)
from ccs_sanitize.rules.identifiers import (
    GIT_BRANCH_PLACEHOLDER,
    UUID_FIELDS,
    build_identifier_transform,
)
from ccs_sanitize.rules.paths import build_path_transform
from ccs_sanitize.subtable import SubstitutionTable

from ._helpers import table_snapshot as _table_snapshot
from ._helpers import write_config as _config


# ----- helpers -----------------------------------------------------------


def _run(
    rules: Iterable[Rule],
    lines: list[str],
    *,
    scrub_git_branch: bool = True,
    remap_uuids: bool = False,
    uuid_seed: str = "ccs-sanitize/v1",
):
    """Build an identifier transform and run the pipeline.

    The skip-predicate is matched to ``remap_uuids`` so a test that sets
    ``remap_uuids=True`` on the transform also lifts the skip-list for
    UUID fields. A mismatch (transform on, predicate off) would silently
    no-op the remap -- valid but not what the test means to exercise.
    """
    table = SubstitutionTable()
    transform = build_identifier_transform(
        tuple(rules),
        table,
        scrub_git_branch=scrub_git_branch,
        remap_uuids=remap_uuids,
        uuid_seed=uuid_seed,
    )
    skip_predicate = make_skip_predicate(remap_uuids=remap_uuids)
    out, counts = run_pipeline(lines, transform=transform, skip_predicate=skip_predicate)
    return out, counts, table


# ----- email replacement --------------------------------------------------


def test_exact_email_replaced_across_multiple_lines(tmp_path: Path) -> None:
    """Subtable: one entry, occurrence count == number of hits across the
    file. Cross-line consistency is the §7 safety property."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
""",
    )
    lines = [
        serialize_line({"type": "user", "message": {"content": "from fpearce@gmail.com"}}),
        serialize_line({"type": "assistant", "message": {"content": "to fpearce@gmail.com again"}}),
    ]
    out, _, table = _run(config.identifiers, lines)
    assert all("fpearce@gmail.com" not in line for line in out)
    assert all("user@example.com" in line for line in out)
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].original == "fpearce@gmail.com"
    assert entries[0].replacement == "user@example.com"
    assert entries[0].occurrences == 2


def test_catch_all_email_regex_replaces_unknown_addresses(tmp_path: Path) -> None:
    """The PRD §8 catch-all regex covers addresses the exact rule misses.
    Each distinct email gets its own subtable entry (substring replacement,
    not single-key mapping).

    The replacement is ``[redacted-email]`` rather than the PRD's literal
    ``user@example.com``: the latter is a valid email shape that self-
    matches the catch-all regex and would be rejected by the I-3
    replacement-leak guard at load time. PRD §8 shows ``user@example.com``
    as the example placeholder, but its catch-all variant in the same
    config can't actually use it -- a documentation tension worth flagging
    separately."""
    body = r"""
version: 1
identifiers:
  - match: 're:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
    replace: "[redacted-email]"
"""
    config = _config(tmp_path, body)
    line = serialize_line(
        {
            "type": "user",
            "message": {
                "content": "see alice@foo.io and bob.smith+ci@example.co.uk",
            },
        }
    )
    out, _, table = _run(config.identifiers, [line])
    assert "alice@foo.io" not in out[0]
    assert "bob.smith+ci@example.co.uk" not in out[0]
    assert out[0].count("[redacted-email]") == 2
    originals = {e.original for e in table}
    assert "alice@foo.io" in originals
    assert "bob.smith+ci@example.co.uk" in originals


def test_exact_rule_before_catch_all_wins(tmp_path: Path) -> None:
    """PRD section 8 implementation note: place the exact email rule
    before the catch-all to get a specific replacement for known
    addresses; the catch-all only fires for everything else. This is
    the same first-match-wins semantic the paths layer documents -- once
    the exact rule's ``re.sub`` consumes the known address, the catch-all
    regex no longer finds it."""
    body = r"""
version: 1
identifiers:
  - match: "fpearce@gmail.com"
    replace: "[known-user]"
  - match: 're:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
    replace: "[redacted-email]"
"""
    config = _config(tmp_path, body)
    line = serialize_line(
        {
            "type": "user",
            "message": {"content": "fpearce@gmail.com and alice@foo.io"},
        }
    )
    out, _, table = _run(config.identifiers, [line])
    # Exact match got its specific replacement.
    assert "[known-user]" in out[0]
    # Unknown address fell through to the catch-all.
    assert "[redacted-email]" in out[0]
    by_original = {e.original: e for e in table}
    assert by_original["fpearce@gmail.com"].replacement == "[known-user]"
    assert by_original["alice@foo.io"].replacement == "[redacted-email]"


# ----- gitBranch ----------------------------------------------------------


def test_git_branch_scrubbed_when_option_on(tmp_path: Path) -> None:
    """PRD §8: ``gitBranch`` values leak ticket IDs; ``scrub_git_branch:
    true`` replaces them with a fixed placeholder."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "gitBranch": "feature/issue-22-secret-name"})
    out, _, table = _run(config.identifiers, [line], scrub_git_branch=True)
    assert "issue-22-secret-name" not in out[0]
    assert f'"gitBranch":"{GIT_BRANCH_PLACEHOLDER}"' in out[0]
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].original == "feature/issue-22-secret-name"
    assert entries[0].replacement == GIT_BRANCH_PLACEHOLDER


def test_git_branch_left_alone_when_option_off(tmp_path: Path) -> None:
    """When ``scrub_git_branch: false`` the field is not rewritten by the
    field-anchored placeholder and (in the absence of identifier rules
    that would otherwise match) is not recorded in the subtable. The
    value falls through to the standard identifier rule loop, so a user
    who configures both ``scrub_git_branch: false`` and an identifier
    rule that matches branch-name substrings WILL get the rule applied
    to the gitBranch leaf -- the option opts out of the placeholder, not
    out of all scrubbing."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "gitBranch": "feature/issue-22"})
    out, _, table = _run(config.identifiers, [line], scrub_git_branch=False)
    assert '"gitBranch":"feature/issue-22"' in out[0]
    assert list(table) == []


def test_git_branch_empty_string_passes_through(tmp_path: Path) -> None:
    """Per the reference docs, ``gitBranch`` is empty when ``cwd`` is not
    in a git repo. That's itself information about the session shape;
    don't replace empty with a fake branch name, and don't pollute the
    subtable with a ('' -> placeholder) row the sidecar can't interpret."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "gitBranch": ""})
    out, _, table = _run(config.identifiers, [line], scrub_git_branch=True)
    assert '"gitBranch":""' in out[0]
    assert list(table) == []


def test_git_branch_wins_over_identifier_rules(tmp_path: Path) -> None:
    """The field-anchored gitBranch substitution is a whole-value
    replacement, not composed with the regex rules. A user identifier
    rule that would match the branch name's substring (e.g., an exact
    'fdpearce' rule) must NOT also fire on the gitBranch leaf -- doing
    so would either double-record or produce nonsense, and it'd hide the
    fact that the gitBranch placeholder is supposed to be a stable,
    audit-friendly constant."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "fdpearce"
    replace: "user"
""",
    )
    line = serialize_line({"type": "user", "gitBranch": "feature/fdpearce-secret"})
    out, _, table = _run(config.identifiers, [line], scrub_git_branch=True)
    assert f'"gitBranch":"{GIT_BRANCH_PLACEHOLDER}"' in out[0]
    # Only the gitBranch placeholder row in the table; the identifier rule
    # did NOT fire on the gitBranch leaf.
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].original == "feature/fdpearce-secret"
    assert entries[0].replacement == GIT_BRANCH_PLACEHOLDER


# ----- UUID remap: off (default) -----------------------------------------


def test_uuid_remap_off_uuids_untouched(tmp_path: Path) -> None:
    """Default skip-predicate filters out UUID-graph fields before the
    transform sees them -- so even an identifier regex that would match
    a UUID substring doesn't fire on those fields. The values appear
    verbatim in the output."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line(
        {
            "type": "user",
            "uuid": "11111111-1111-1111-1111-111111111001",
            "parentUuid": "11111111-1111-1111-1111-111111111000",
            "sessionId": "00000000-0000-0000-0000-000000000001",
        }
    )
    out, _, table = _run(config.identifiers, [line], remap_uuids=False)
    assert "11111111-1111-1111-1111-111111111001" in out[0]
    assert "11111111-1111-1111-1111-111111111000" in out[0]
    assert "00000000-0000-0000-0000-000000000001" in out[0]
    assert list(table) == []


# ----- UUID remap: on ----------------------------------------------------


def test_uuid_remap_preserves_parent_child_graph(tmp_path: Path) -> None:
    """The graph-integrity invariant: ``parentUuid → uuid`` linkage
    survives remapping. Line 2's parentUuid points at line 1's uuid; after
    sanitization, line 2's (remapped) parentUuid still equals line 1's
    (remapped) uuid -- because the remap is a pure function of the
    original value and the same value appears in both places."""
    config = _config(tmp_path, "version: 1\n")
    lines = [
        serialize_line(
            {
                "type": "user",
                "uuid": "11111111-1111-1111-1111-111111111001",
                "parentUuid": None,
            }
        ),
        serialize_line(
            {
                "type": "assistant",
                "uuid": "11111111-1111-1111-1111-111111111002",
                "parentUuid": "11111111-1111-1111-1111-111111111001",
            }
        ),
    ]
    out, _, table = _run(config.identifiers, lines, remap_uuids=True)
    # Both originals are out of the output.
    serialized = "\n".join(out)
    assert "11111111-1111-1111-1111-111111111001" not in serialized
    assert "11111111-1111-1111-1111-111111111002" not in serialized
    # null parentUuid stays null (string-only walker; never visits).
    assert '"parentUuid":null' in out[0]
    # Graph link survives: line 1's remapped uuid == line 2's remapped parentUuid.
    line1_uuid_remap = table.get("11111111-1111-1111-1111-111111111001")
    assert line1_uuid_remap is not None
    assert line1_uuid_remap in out[1]
    # And it appears in line 2 specifically in the parentUuid slot.
    assert f'"parentUuid":"{line1_uuid_remap}"' in out[1]


def test_uuid_remap_preserves_session_id_shared_key(tmp_path: Path) -> None:
    """Every line in a session shares one ``sessionId``. After remap they
    must still share -- otherwise downstream tooling that groups by
    ``sessionId`` would see one file as many sessions."""
    config = _config(tmp_path, "version: 1\n")
    sid = "00000000-0000-0000-0000-000000000001"
    lines = [
        serialize_line({"type": "user", "sessionId": sid, "uuid": "u1"}),
        serialize_line({"type": "assistant", "sessionId": sid, "uuid": "u2"}),
        serialize_line({"type": "user", "sessionId": sid, "uuid": "u3"}),
    ]
    out, _, table = _run(config.identifiers, lines, remap_uuids=True)
    remap = table.get(sid)
    assert remap is not None
    for serialized in out:
        assert sid not in serialized
        assert f'"sessionId":"{remap}"' in serialized
    # Subtable: one entry for sessionId, three occurrences (once per line).
    entries = list(table)
    sid_entry = next(e for e in entries if e.original == sid)
    assert sid_entry.occurrences == 3


def test_uuid_remap_links_nested_agent_id_to_top_level(tmp_path: Path) -> None:
    """The parent↔subagent link: parent file's ``toolUseResult.agentId``
    points at the subagent file's top-level ``agentId``. They are the
    same value in raw form. After remap they must still be the same
    value, otherwise the link is broken and the fixture is useless
    (PRD §8 'agentId parent↔subagent link')."""
    config = _config(tmp_path, "version: 1\n")
    agent = "22222222-2222-2222-2222-222222222001"
    parent_line = serialize_line(
        {
            "type": "user",
            "toolUseResult": {"agentId": agent, "totalTokens": 100},
        }
    )
    subagent_line = serialize_line(
        {
            "type": "assistant",
            "agentId": agent,
            "isSidechain": True,
        }
    )
    out, _, table = _run(
        config.identifiers, [parent_line, subagent_line], remap_uuids=True
    )
    remap = table.get(agent)
    assert remap is not None
    assert agent not in "\n".join(out)
    # Both occurrences resolve to the same remapped agentId.
    assert f'"agentId":"{remap}"' in out[0]  # nested in toolUseResult
    assert f'"agentId":"{remap}"' in out[1]  # top-level
    # Subtable: one entry, two occurrences.
    entries = [e for e in table if e.original == agent]
    assert len(entries) == 1
    assert entries[0].occurrences == 2


def test_uuid_remap_injective_on_distinct_inputs(tmp_path: Path) -> None:
    """Distinct UUIDs in the same file must remap to distinct values.
    SHA-256 collisions are astronomically unlikely, but this test would
    catch an implementation bug like accidentally hashing only the seed
    and ignoring the original."""
    config = _config(tmp_path, "version: 1\n")
    originals = [
        "11111111-1111-1111-1111-111111111001",
        "11111111-1111-1111-1111-111111111002",
        "22222222-2222-2222-2222-222222222001",
        "00000000-0000-0000-0000-000000000001",
    ]
    lines = [serialize_line({"type": "user", "uuid": u}) for u in originals]
    _, _, table = _run(config.identifiers, lines, remap_uuids=True)
    remaps = [table.get(u) for u in originals]
    assert all(r is not None for r in remaps)
    assert len(set(remaps)) == len(originals)


def test_uuid_remap_empty_string_passes_through(tmp_path: Path) -> None:
    """An empty-string UUID is malformed but harmless; silently hashing
    it would create a phantom node where every empty UUID across files
    maps to the same real-looking placeholder. Pass through unchanged."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "uuid": ""})
    out, _, table = _run(config.identifiers, [line], remap_uuids=True)
    assert '"uuid":""' in out[0]
    assert list(table) == []


def test_uuid_remap_null_parent_uuid_passes_through(tmp_path: Path) -> None:
    """``parentUuid: null`` on the first line of a session must stay null
    after remap. The walker only visits string leaves, so null never
    reaches the transform -- this test pins the non-obvious invariant the
    graph-integrity claim depends on."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "uuid": "u-1", "parentUuid": None})
    out, _, table = _run(config.identifiers, [line], remap_uuids=True)
    assert '"parentUuid":null' in out[0]
    # The table has exactly one row (the uuid leaf); the null parentUuid
    # was passed through by the walker without invoking the transform.
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].original == "u-1"


def test_uuid_remap_deterministic_across_runs(tmp_path: Path) -> None:
    """Two runs over the same input produce byte-identical output AND
    table-snapshot equality. PRD §10 sidecar emits the table verbatim,
    so table-shape determinism is part of the same contract as
    output-bytes determinism."""
    config = _config(tmp_path, "version: 1\n")
    lines = [
        serialize_line(
            {
                "type": "user",
                "uuid": "11111111-1111-1111-1111-111111111001",
                "sessionId": "00000000-0000-0000-0000-000000000001",
            }
        ),
        serialize_line(
            {
                "type": "assistant",
                "uuid": "11111111-1111-1111-1111-111111111002",
                "parentUuid": "11111111-1111-1111-1111-111111111001",
                "sessionId": "00000000-0000-0000-0000-000000000001",
            }
        ),
    ]
    out1, _, table1 = _run(config.identifiers, lines, remap_uuids=True)
    out2, _, table2 = _run(config.identifiers, lines, remap_uuids=True)
    assert out1 == out2
    assert _table_snapshot(table1) == _table_snapshot(table2)


def test_uuid_remap_seed_changes_output(tmp_path: Path) -> None:
    """Changing ``uuid_seed`` changes every remapped UUID. Without this,
    the seed isn't actually feeding the hash and the determinism
    contract becomes meaningless."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line({"type": "user", "uuid": "11111111-1111-1111-1111-111111111001"})
    out_a, _, _ = _run(config.identifiers, [line], remap_uuids=True, uuid_seed="seed-A")
    out_b, _, _ = _run(config.identifiers, [line], remap_uuids=True, uuid_seed="seed-B")
    assert out_a != out_b


def test_uuid_remap_consistent_within_file(tmp_path: Path) -> None:
    """Subtable.record short-circuits on repeat (original, replacement)
    pairs, so the same UUID appearing twice in the same file produces
    one entry with occurrence count 2 -- not two entries, and not a
    SubstitutionConflictError."""
    config = _config(tmp_path, "version: 1\n")
    u = "11111111-1111-1111-1111-111111111001"
    lines = [
        serialize_line({"type": "user", "uuid": u}),
        serialize_line({"type": "assistant", "uuid": u}),  # same uuid repeated
    ]
    _, _, table = _run(config.identifiers, lines, remap_uuids=True)
    entries = [e for e in table if e.original == u]
    assert len(entries) == 1
    assert entries[0].occurrences == 2


def test_uuid_fields_match_pipeline_skip_list() -> None:
    """``UUID_FIELDS`` here and ``_UUID_NAMES`` in the pipeline govern two
    sides of the same contract: what to skip when ``remap_uuids`` is off,
    and what to remap when it's on. They MUST stay equal -- adding a
    field to one without the other would silently leak (visited but
    never remapped) or silently no-op (remapped but never visited)."""
    from ccs_sanitize.pipeline import _UUID_NAMES  # noqa: PLC2701 — pin the contract
    assert UUID_FIELDS == _UUID_NAMES


# ----- composition with Layer 1 -----------------------------------------


def test_paths_and_identifiers_compose_with_one_shared_table(tmp_path: Path) -> None:
    """The two layers chain via a single transform that calls each in
    order; they share one ``SubstitutionTable`` so the sidecar shows
    both paths' and identifiers' substitutions in one coherent list.
    PRD layer ordering (§7 paths first, §8 identifiers next) is the
    contract the CLI in #26 will enforce."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
"""
    config = _config(tmp_path, body)
    table = SubstitutionTable()
    path_transform = build_path_transform(config.paths, table)
    id_transform = build_identifier_transform(
        config.identifiers, table, scrub_git_branch=True
    )

    def composed(leaf: str, path: JsonPath) -> str:
        return id_transform(path_transform(leaf, path), path)

    line = serialize_line(
        {
            "type": "user",
            "cwd": "/home/fdpearce/proj",
            "gitBranch": "feature/issue-22",
            "message": {"content": "mail to fpearce@gmail.com"},
        }
    )
    out, _ = run_pipeline([line], transform=composed)
    assert "/home/user/proj" in out[0]
    assert "fpearce@gmail.com" not in out[0]
    assert "user@example.com" in out[0]
    assert f'"gitBranch":"{GIT_BRANCH_PLACEHOLDER}"' in out[0]
    # One shared table -- three distinct originals.
    originals = {e.original for e in table}
    assert "/home/fdpearce" in originals
    assert "fpearce@gmail.com" in originals
    assert "feature/issue-22" in originals


def test_paths_and_identifiers_compose_under_remap_uuids(tmp_path: Path) -> None:
    """When ``remap_uuids=True`` the pipeline skip-list lifts and the
    composed transform sees UUID-graph leaves. Layer 1 (paths) runs
    first, so a path rule that happens to match a UUID substring would
    mutate the leaf before Layer 2's whole-value remap fires --
    silently breaking the parent↔subagent graph. This test pins that
    a benign, well-scoped path rule does NOT interfere with the UUID
    remap, and the graph link survives end-to-end."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
identifiers: []
"""
    config = _config(tmp_path, body)
    table = SubstitutionTable()
    path_transform = build_path_transform(config.paths, table)
    id_transform = build_identifier_transform(
        config.identifiers, table, remap_uuids=True
    )

    def composed(leaf: str, path: JsonPath) -> str:
        return id_transform(path_transform(leaf, path), path)

    parent_uuid = "11111111-1111-1111-1111-111111111001"
    child_uuid = "11111111-1111-1111-1111-111111111002"
    lines = [
        serialize_line({"type": "user", "cwd": "/home/fdpearce/x", "uuid": parent_uuid}),
        serialize_line(
            {"type": "assistant", "uuid": child_uuid, "parentUuid": parent_uuid}
        ),
    ]
    out, _ = run_pipeline(
        lines,
        transform=composed,
        skip_predicate=make_skip_predicate(remap_uuids=True),
    )
    # Path scrubbing still works.
    assert "/home/user/x" in out[0]
    # UUID scrubbing still works.
    assert parent_uuid not in "\n".join(out)
    assert child_uuid not in "\n".join(out)
    # Graph link survives: line 1's remapped uuid == line 2's remapped parentUuid.
    remap_parent = table.get(parent_uuid)
    assert remap_parent is not None
    assert f'"parentUuid":"{remap_parent}"' in out[1]


# ----- no-op edges --------------------------------------------------------


def test_empty_rules_no_options_is_identity(tmp_path: Path) -> None:
    """No identifier rules + scrub_git_branch=False + remap_uuids=False
    yields a transform that passes every leaf through unchanged. Sanity
    check: the routing-only branches don't accidentally short-circuit."""
    config = _config(tmp_path, "version: 1\n")
    line = serialize_line(
        {
            "type": "user",
            "cwd": "/home/x",
            "gitBranch": "feature/keep-me",
            "uuid": "u-1",
            "message": {"content": "alice@foo.io"},
        }
    )
    out, _, table = _run(
        config.identifiers, [line], scrub_git_branch=False, remap_uuids=False
    )
    assert "/home/x" in out[0]
    assert "feature/keep-me" in out[0]
    assert "u-1" in out[0]
    assert "alice@foo.io" in out[0]
    assert list(table) == []


def test_email_rule_does_not_fire_on_skip_listed_fields(tmp_path: Path) -> None:
    """An identifier regex broad enough to match a UUID-shaped string must
    NOT match UUID-graph fields when ``remap_uuids`` is off -- because
    the pipeline's skip-list filters them out before the transform runs.
    Belt-and-suspenders test: a regression in the skip-list could turn
    this into a substitution-conflict explosion."""
    body = r"""
version: 1
identifiers:
  - match: "re:[0-9a-f]{8}-[0-9a-f]{4}"
    replace: "<scrubbed-shape>"
"""
    config = _config(tmp_path, body)
    line = serialize_line({"type": "user", "uuid": "11111111-1111-1111-1111-111111111001"})
    out, _, table = _run(config.identifiers, [line], remap_uuids=False)
    # The uuid leaf was never visited (skip-list); the regex did not fire on it.
    assert "11111111-1111" in out[0]
    assert "<scrubbed-shape>" not in out[0]
    assert list(table) == []


def test_pipeline_error_on_subtable_conflict_is_propagated(tmp_path: Path) -> None:
    """If a future config bug or rule-layer change introduced a
    substitution conflict, the SubstitutionTable raises and the pipeline
    propagates -- fail-closed (PRD §11). Synthetic case: pre-load the
    table with a contradicting mapping for an email, then run the
    transform; the second record() call raises."""
    from ccs_sanitize.subtable import SubstitutionConflictError

    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
""",
    )
    table = SubstitutionTable()
    table.record("fpearce@gmail.com", "DIFFERENT@example.com", label="identifiers")
    transform = build_identifier_transform(config.identifiers, table)
    line = serialize_line({"type": "user", "message": {"content": "fpearce@gmail.com"}})
    with pytest.raises(SubstitutionConflictError):
        run_pipeline([line], transform=transform)
