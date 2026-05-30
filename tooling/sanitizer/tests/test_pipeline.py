"""Tests for the pipeline core: strip-types, structural traversal, and
serialization pins (issue #20).

Covers PRD section 6b A (line-type stripping), section 6b B (structural
traversal with skip-list), section 7 (within-file consistency via the
SubstitutionTable), and section 11 I-1 (serialization pins).

Synthetic fixtures only — no real session data. Per PRD section 14,
secret-pattern test inputs are not needed in this story (no rules wired
yet); those land with #23.
"""

from __future__ import annotations

import json

import pytest

from ccs_sanitize.pipeline import (
    DEFAULT_STRIP_TYPES,
    PipelineError,
    default_skip_predicate,
    run_pipeline,
    serialize_line,
    walk_strings,
)
from ccs_sanitize.subtable import SubstitutionTable


# ----- helpers -----------------------------------------------------------


def _line(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"))


def _record_transform():
    """A transform that records every (leaf, path) it sees and passes the
    leaf through unchanged. Returns (transform, visited)."""
    visited: list[tuple[str, tuple[str, ...]]] = []

    def transform(leaf, path):
        visited.append((leaf, path))
        return leaf

    return transform, visited


# ----- strip-types (PRD section 6b A) ------------------------------------


def test_strip_types_drops_file_history_snapshot() -> None:
    lines = [
        _line({"type": "assistant", "uuid": "u1"}),
        _line({"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {"/a": "..."}}}),
        _line({"type": "user", "uuid": "u2"}),
    ]
    out, counts = run_pipeline(lines)
    assert len(out) == 2
    assert counts.stripped_lines == {"file-history-snapshot": 1}
    # The dropped line's content must not appear anywhere in the output.
    serialized = "\n".join(out)
    assert "trackedFileBackups" not in serialized
    assert "/a" not in serialized


def test_strip_types_drops_attachment() -> None:
    lines = [
        _line({"type": "attachment", "binary_blob": "AAAAA"}),
        _line({"type": "assistant"}),
    ]
    out, counts = run_pipeline(lines)
    assert len(out) == 1
    assert counts.stripped_lines == {"attachment": 1}
    assert "AAAAA" not in "\n".join(out)


def test_default_strip_types_covers_prd_section_6b_a() -> None:
    assert DEFAULT_STRIP_TYPES == frozenset({"file-history-snapshot", "attachment"})


def test_custom_strip_types_replaces_default() -> None:
    lines = [
        _line({"type": "file-history-snapshot", "x": "kept"}),
        _line({"type": "attachment", "x": "kept-too"}),
        _line({"type": "custom-junk", "x": "dropped"}),
    ]
    out, counts = run_pipeline(lines, strip_types=frozenset({"custom-junk"}))
    assert len(out) == 2  # the two default-stripped types now pass through
    assert counts.stripped_lines == {"custom-junk": 1}


def test_stripped_counts_aggregate_across_lines() -> None:
    lines = [_line({"type": "attachment"})] * 5
    out, counts = run_pipeline(lines)
    assert out == []
    assert counts.stripped_lines == {"attachment": 5}


# ----- structural traversal (PRD section 6b B) ---------------------------


def test_walk_strings_visits_top_level_string_leaves() -> None:
    transform, visited = _record_transform()
    walk_strings({"cwd": "/home/fdpearce"}, transform)
    assert (("/home/fdpearce", ("cwd",))) in visited


def test_walk_strings_visits_nested_content_blocks() -> None:
    """Array-shape message.content with text + tool_use input + tool_result."""
    transform, visited = _record_transform()
    walk_strings(
        {
            "message": {
                "content": [
                    {"type": "text", "text": "hi there"},
                    {
                        "type": "tool_use",
                        "input": {"command": "ls /home/fdpearce"},
                    },
                    {
                        "type": "tool_result",
                        "content": "command output here",
                    },
                ]
            }
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    assert "hi there" in leaves
    assert "ls /home/fdpearce" in leaves
    assert "command output here" in leaves


def test_walk_strings_visits_string_shape_message_content() -> None:
    """The other message.content shape — plain string instead of array."""
    transform, visited = _record_transform()
    walk_strings(
        {"message": {"content": "just a plain string here"}},
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    assert "just a plain string here" in leaves


def test_walk_strings_visits_tool_use_result_paths() -> None:
    transform, visited = _record_transform()
    walk_strings(
        {
            "toolUseResult": {
                "stdout": "secret_token_here",
                "stderr": "/home/fdpearce/log",
            }
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    assert "secret_token_here" in leaves
    assert "/home/fdpearce/log" in leaves


def test_walk_strings_skips_documented_fields() -> None:
    transform, visited = _record_transform()
    walk_strings(
        {
            "type": "assistant",
            "version": "1.0.5",
            "uuid": "u-1",
            "parentUuid": "u-0",
            "sessionId": "sess-1",
            "agentId": "agent-1",
            "requestId": "req-1",
            "tool_use_id": "toolu-1",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-7",
                "id": "msg-1",
                "content": [
                    {"type": "thinking", "thinking": "REASONING", "signature": "OPAQUE"},
                ],
            },
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    # The "type"/"role"/"model"/"version"/UUID/id/signature fields must NOT
    # have been visited.
    skipped_values = {
        "assistant",  # type and role both have this value
        "1.0.5",  # version
        "u-1",
        "u-0",
        "sess-1",
        "agent-1",
        "req-1",
        "toolu-1",
        "claude-opus-4-7",  # message.model
        "msg-1",  # message.id
        "thinking",  # content[].type
        "OPAQUE",  # thinking.signature
    }
    assert leaves & skipped_values == set(), (
        f"these skip-listed values were visited: {leaves & skipped_values}"
    )
    # But the "thinking" field's actual reasoning text IS scrubbable
    # content — confirm it was visited.
    assert "REASONING" in leaves


def test_skip_predicate_handles_tokens_suffix() -> None:
    """Any field ending in _tokens is skipped (usage.input_tokens etc.).
    Numeric in practice, but the predicate covers strings defensively."""
    assert default_skip_predicate(("usage", "input_tokens")) is True
    assert default_skip_predicate(("usage", "cache_creation_input_tokens")) is True


def test_skip_predicate_usage_subtree() -> None:
    """Anything under usage.* is skipped, even non-token names."""
    assert default_skip_predicate(("message", "usage", "service_tier")) is True


def test_skip_predicate_empty_path() -> None:
    """An empty path can't be a leaf in our walker but the predicate
    should answer cleanly anyway."""
    assert default_skip_predicate(()) is False


# ----- serialization pins (PRD section 11 I-1) ---------------------------


def test_serialize_line_uses_compact_separators() -> None:
    out = serialize_line({"a": 1, "b": [1, 2]})
    assert " " not in out  # no whitespace from json.dumps' default separators


def test_serialize_line_preserves_unicode() -> None:
    out = serialize_line({"x": "naïve café"})
    assert "naïve café" in out  # ensure_ascii=False keeps it readable


def test_serialize_line_preserves_key_order() -> None:
    """Keys are NOT sorted — original insertion order is preserved."""
    obj = {"z_last": 1, "m_middle": 2, "a_first": 3}
    out = serialize_line(obj)
    # z comes before m comes before a in the output (insertion order).
    assert out.index("z_last") < out.index("m_middle") < out.index("a_first")


# ----- end-to-end pipeline integration -----------------------------------


def test_identity_run_is_byte_identical_across_runs() -> None:
    """Determinism is the safety property (PRD section 7). Two runs with
    the same input and (identity) transform must produce byte-identical
    output."""
    lines = [
        _line({"type": "assistant", "cwd": "/home/x", "message": {"content": "hi"}}),
        _line({"type": "user", "cwd": "/home/x", "uuid": "u-2"}),
    ]
    out1, counts1 = run_pipeline(lines)
    out2, counts2 = run_pipeline(lines)
    assert out1 == out2
    assert counts1.stripped_lines == counts2.stripped_lines


def test_identity_run_preserves_key_order_of_input() -> None:
    """walk_strings rebuilds dicts but preserves insertion order, so an
    identity run round-trips the original key order."""
    obj = {"z": "first-key", "type": "assistant", "a": "last-key"}
    out, _ = run_pipeline([_line(obj)])
    assert out[0].index('"z"') < out[0].index('"type"') < out[0].index('"a"')


def test_malformed_jsonl_raises_pipeline_error() -> None:
    with pytest.raises(PipelineError, match="malformed JSONL"):
        run_pipeline(["this is not json"])


def test_blank_lines_are_tolerated() -> None:
    """Trailing newlines / incidental blank lines from file iteration
    don't trigger PipelineError — that's a footgun for file readers."""
    lines = ["", _line({"type": "assistant"}), "   \n", _line({"type": "user"})]
    out, _ = run_pipeline(lines)
    assert len(out) == 2


def test_transform_with_subtable_keeps_within_file_consistency() -> None:
    """A transform that funnels through a SubstitutionTable applies the
    same replacement to the same original on every line — the property
    PRD section 7 calls out as the safety reason per-file runs are safe.
    """
    table = SubstitutionTable()

    def transform(leaf: str, path: tuple[str, ...]) -> str:
        if "/home/fdpearce" in leaf:
            replaced = leaf.replace("/home/fdpearce", "/home/user")
            table.record("/home/fdpearce", "/home/user")
            return replaced
        return leaf

    lines = [
        _line({"type": "a", "cwd": "/home/fdpearce/proj"}),
        _line({"type": "a", "cwd": "/home/fdpearce/proj"}),
        _line({"type": "a", "cwd": "/home/fdpearce/other"}),
    ]
    out, _ = run_pipeline(lines, transform=transform)
    assert all("/home/fdpearce" not in line for line in out)
    assert all("/home/user" in line for line in out)
    entries = list(table)
    assert len(entries) == 1
    assert entries[0].occurrences == 3  # one per line


def test_pipeline_does_not_visit_skipped_fields_via_transform() -> None:
    """End-to-end check: a transform passed through the pipeline never
    sees skip-listed fields, even via the real run loop (not just
    walk_strings in isolation)."""
    transform, visited = _record_transform()
    line = _line(
        {
            "type": "assistant",
            "uuid": "u-1",
            "cwd": "/scrubme",
            "message": {"role": "assistant", "model": "claude-opus-4-7"},
        }
    )
    run_pipeline([line], transform=transform)
    leaves = {leaf for leaf, _ in visited}
    assert "/scrubme" in leaves  # the cwd value IS scrubbable
    assert leaves & {"assistant", "u-1", "claude-opus-4-7"} == set()
