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

import math

import pytest

from ccs_sanitize.pipeline import (
    DEFAULT_STRIP_TYPES,
    PipelineError,
    default_skip_predicate,
    make_skip_predicate,
    run_pipeline,
    serialize_line,
    walk_strings,
)
from ccs_sanitize.subtable import SubstitutionTable


# ----- helpers -----------------------------------------------------------


def _line(obj: dict) -> str:
    """Serialize a synthetic line the same way the pipeline does, so test
    inputs and pipeline outputs use the same byte shape (otherwise a future
    pinning change in ``serialize_line`` could silently diverge from the
    test helper)."""
    return serialize_line(obj)


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
    assert dict(counts.stripped_lines) == {"file-history-snapshot": 1}
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
    assert dict(counts.stripped_lines) == {"attachment": 1}
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
    assert dict(counts.stripped_lines) == {"custom-junk": 1}


def test_stripped_counts_aggregate_across_lines() -> None:
    lines = [_line({"type": "attachment"})] * 5
    out, counts = run_pipeline(lines)
    assert out == []
    assert dict(counts.stripped_lines) == {"attachment": 5}


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
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-7",
                "id": "msg-1",
                "content": [
                    {"type": "thinking", "thinking": "REASONING", "signature": "OPAQUE"},
                    {"type": "tool_result", "tool_use_id": "toolu-1"},
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


def test_walk_strings_visits_skip_listed_names_outside_their_format_position() -> None:
    """#194. The allow-list is keyed on the ROOT-ANCHORED path, so a
    skip-listed name carries no exemption anywhere else.

    ``tool_use.input`` is arbitrary tool-defined JSON and MCP servers define
    their own schemas, so a tool parameter named ``type`` or ``sessionId`` is
    user data at a colliding key -- exactly the position the bare-name
    skip-list refused to visit. Note this test plants the SAME names as the
    test above: there they sit at their format positions and must be skipped,
    here they sit one subtree over and must be visited. That pairing is the
    whole contract."""
    transform, visited = _record_transform()
    walk_strings(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "input": {
                            "version": "PAYLOAD-version",
                            "type": "PAYLOAD-type",
                            "role": "PAYLOAD-role",
                            "requestId": "PAYLOAD-requestId",
                            "tool_use_id": "PAYLOAD-tool_use_id",
                            "sessionId": "PAYLOAD-sessionId",
                            "uuid": "PAYLOAD-uuid",
                            "agentId": "PAYLOAD-agentId",
                            "parentUuid": "PAYLOAD-parentUuid",
                            "max_tokens": "PAYLOAD-tokens-suffix",
                            "usage": {"anything": "PAYLOAD-usage-child"},
                            # The four pairs that were "anchored" but matched
                            # the immediate parent name at ANY depth.
                            "content": {"id": "PAYLOAD-content-id",
                                        "signature": "PAYLOAD-content-signature"},
                            "message": {"model": "PAYLOAD-message-model",
                                        "id": "PAYLOAD-message-id"},
                        },
                    },
                ],
            },
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    planted = {v for v in leaves if v.startswith("PAYLOAD-")}
    assert planted == {
        "PAYLOAD-version", "PAYLOAD-type", "PAYLOAD-role", "PAYLOAD-requestId",
        "PAYLOAD-tool_use_id", "PAYLOAD-sessionId", "PAYLOAD-uuid",
        "PAYLOAD-agentId", "PAYLOAD-parentUuid", "PAYLOAD-tokens-suffix",
        "PAYLOAD-usage-child", "PAYLOAD-content-id", "PAYLOAD-content-signature",
        "PAYLOAD-message-model", "PAYLOAD-message-id",
    }, f"not visited: {planted}"


def test_walk_strings_visits_a_nested_skip_listed_name_in_tool_input() -> None:
    """#194. Anchoring is by rooted POSITION, not by depth -- so burying the
    colliding key one level further down does not re-create the exemption."""
    transform, visited = _record_transform()
    walk_strings(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "input": {"a": {"type": "NESTED-PAYLOAD"}}},
                ],
            },
        },
        transform,
    )
    assert "NESTED-PAYLOAD" in {leaf for leaf, _ in visited}


def test_walk_strings_does_not_skip_bare_id_in_user_content() -> None:
    """PRD section 6b B anchors ``message.id`` and ``tool_use.id`` to their
    parents. A bare ``id`` field inside user-controlled content (e.g., an
    MCP tool input or tool_result body) must NOT be skipped — otherwise PII
    in those fields slips past scrubbing."""
    transform, visited = _record_transform()
    walk_strings(
        {
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_envelope_id",  # tool_use.id — anchored skip
                        "input": {
                            "id": "/home/user/secret-doc",  # USER content — must visit
                            "model": "gpt-4-via-/home/user",  # USER content — must visit
                            "signature": "user-supplied-sig",  # USER content — must visit
                        },
                    },
                ],
            },
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    # Anchored skips still apply.
    assert "toolu_envelope_id" not in leaves
    # User content with colliding field names is visited.
    assert "/home/user/secret-doc" in leaves
    assert "gpt-4-via-/home/user" in leaves
    assert "user-supplied-sig" in leaves


def test_walk_strings_does_not_over_skip_usage_named_user_field() -> None:
    """The skip-list scopes ``usage`` to the token-accounting subtree (PRD
    section 6b B). A user-controlled field literally named ``usage`` (e.g.,
    an MCP tool input documenting its own usage) must NOT be skipped."""
    transform, visited = _record_transform()
    walk_strings(
        {
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "input": {
                            # 'usage' here is a user-controlled string field,
                            # not the token-accounting block.
                            "usage": "call from /home/fdpearce",
                        },
                    },
                ],
            },
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    assert "call from /home/fdpearce" in leaves


def test_walk_strings_still_skips_genuine_usage_subtree() -> None:
    """``message.usage.service_tier`` (a string field directly under the
    token-accounting block) IS skipped — PRD scopes the entire usage block."""
    transform, visited = _record_transform()
    walk_strings(
        {
            "message": {
                "usage": {
                    "service_tier": "standard",
                    "input_tokens": 100,
                },
            },
        },
        transform,
    )
    leaves = {leaf for leaf, _ in visited}
    assert "standard" not in leaves


def test_skip_predicate_no_longer_has_a_tokens_suffix_rule() -> None:
    """#194 deleted the ``endswith("_tokens")`` rule rather than anchoring it.

    It was the broadest of the depth-agnostic rules -- not a name list at
    all, so EVERY tool parameter ending in ``_tokens`` was exempt, including
    ``max_tokens``, which is a real parameter on a real API. It also bought
    almost nothing: token counts are integers, and ``walk_strings`` only ever
    hands STRING leaves to the transform, so the rule never fired on the
    fields it was written for. The four string leaves that genuinely live
    under a usage block are allow-listed by rooted path instead (below)."""
    assert default_skip_predicate(("usage", "input_tokens")) is False
    assert default_skip_predicate(("message", "usage", "cache_creation_input_tokens")) is False
    assert default_skip_predicate(("message", "content", "input", "max_tokens")) is False


def test_skip_predicate_allows_the_usage_string_leaves_by_rooted_path() -> None:
    """The usage subtree is enumerated, NOT prefixed. A "skip everything
    under usage" rule is the ``"usage" in path`` membership test this module
    already deleted once; both usage blocks hold exactly four string leaves
    and all four are closed enums, so listing them costs eight entries and
    keeps the fail-closed direction for anything new that appears there."""
    for parent in (("message",), ("toolUseResult",)):
        assert default_skip_predicate(parent + ("usage", "service_tier")) is True
        assert default_skip_predicate(parent + ("usage", "speed")) is True
        assert default_skip_predicate(parent + ("usage", "inference_geo")) is True
        assert default_skip_predicate(parent + ("usage", "iterations", "type")) is True
    # Anything else under usage is NEW and is scrubbed, not assumed safe.
    assert default_skip_predicate(("message", "usage", "some_future_field")) is False


def test_skip_predicate_does_not_exempt_a_user_field_named_usage() -> None:
    """A tool input documenting its own ``usage`` is user data.

    This held before #194 for the *node* named ``usage`` and failed for its
    CHILDREN: the old rule was ``path[-2] == "usage"``, so ``input.usage``
    was visited while ``input.usage.anything`` was skipped -- the leak was
    one level below where the test was looking. Both are visited now."""
    assert default_skip_predicate(("message", "content", "input", "usage")) is False
    assert default_skip_predicate(("message", "content", "input", "usage", "anything")) is False


def test_skip_predicate_empty_path() -> None:
    """An empty path can't be a leaf in our walker but the predicate
    should answer cleanly anyway."""
    assert default_skip_predicate(()) is False


def test_make_skip_predicate_remap_uuids_visits_uuid_fields() -> None:
    """PRD section 6b B: UUID fields are skipped 'unless remap_uuids is on'.
    The factory honors that flag so #22's identifier layer can remap UUIDs
    consistently."""
    predicate = make_skip_predicate(remap_uuids=True)
    # UUID-graph fields are NOT skipped under remap_uuids.
    assert predicate(("uuid",)) is False
    assert predicate(("parentUuid",)) is False
    assert predicate(("sessionId",)) is False
    assert predicate(("agentId",)) is False
    # But other PRD skip-list members are still skipped.
    assert predicate(("type",)) is True
    assert predicate(("message", "model")) is True


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


def test_serialize_line_rejects_nan() -> None:
    """NaN / Infinity are non-RFC-8259 JSON; we refuse to emit them."""
    with pytest.raises(PipelineError, match="non-finite number"):
        serialize_line({"score": float("nan")})


def test_serialize_line_rejects_infinity() -> None:
    with pytest.raises(PipelineError, match="non-finite number"):
        serialize_line({"score": math.inf})


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
    assert dict(counts1.stripped_lines) == dict(counts2.stripped_lines)


def test_identity_run_preserves_key_order_of_input() -> None:
    """walk_strings rebuilds dicts but preserves insertion order, so an
    identity run round-trips the original key order."""
    obj = {"z": "first-key", "type": "assistant", "a": "last-key"}
    out, _ = run_pipeline([_line(obj)])
    assert out[0].index('"z"') < out[0].index('"type"') < out[0].index('"a"')


def test_malformed_jsonl_raises_pipeline_error() -> None:
    with pytest.raises(PipelineError, match="malformed JSONL"):
        run_pipeline(["this is not json"])


def test_malformed_jsonl_error_names_input_line_number() -> None:
    """When blank lines precede a malformed line, the error names the
    input line position (not the post-filter record index), so a user can
    locate the bad line in their source file."""
    lines = ["", "   ", _line({"type": "assistant"}), "this is not json"]
    with pytest.raises(PipelineError, match="line 4"):
        run_pipeline(lines)


def test_non_dict_root_raises_pipeline_error() -> None:
    """A JSONL line whose root is a scalar/array (not a record-shaped
    object) is treated as a shape violation, not silently walked through.
    PRD section 11 fails closed on malformed input."""
    # Bare string root.
    with pytest.raises(PipelineError, match="must be a JSON object"):
        run_pipeline(['"just a string"'])
    # Top-level array root.
    with pytest.raises(PipelineError, match="must be a JSON object"):
        run_pipeline(["[1, 2, 3]"])
    # Bare scalar root.
    with pytest.raises(PipelineError, match="must be a JSON object"):
        run_pipeline(["42"])


def test_missing_type_field_raises_pipeline_error() -> None:
    """All session JSONL records carry a ``type`` field; a missing one is
    treated as malformed rather than silently walked."""
    with pytest.raises(PipelineError, match="missing required 'type'"):
        run_pipeline([_line({"uuid": "u-1"})])


def test_non_string_type_field_raises_pipeline_error() -> None:
    """A non-string ``type`` value (e.g., a list-laundered attachment
    line trying to slip past the strip-type gate) is rejected."""
    # type as list — would otherwise skip the strip check.
    with pytest.raises(PipelineError, match="'type' field must be a string"):
        run_pipeline(['{"type": ["attachment"], "binary_blob": "AAAA"}'])
    # type as null — same rejection.
    with pytest.raises(PipelineError, match="'type' field must be a string"):
        run_pipeline(['{"type": null}'])


def test_blank_lines_are_tolerated() -> None:
    """Trailing newlines / incidental blank lines from file iteration
    don't trigger PipelineError — that's a footgun for file readers."""
    lines = ["", _line({"type": "assistant"}), "   \n", _line({"type": "user"})]
    out, _ = run_pipeline(lines)
    assert len(out) == 2


def test_blank_lines_are_counted_for_audit_field() -> None:
    """``PipelineCounts.blank_lines`` reports the number of whitespace-only
    input lines skipped by ``run_pipeline``, so the sidecar's
    ``lines_processed`` equals the number of items the input iterable
    produced (#43). Earlier ``_iter_records`` dropped blanks with no
    surface counter; a file with interior blank lines undercounted by
    the number of blanks.

    Mixes leading, interior, and trailing blanks with a strip-type
    survivor and a normal survivor so every category contributes
    independently: survivors=1, stripped=1, blanks=4 -> 6 total, which
    equals ``len(input_iterable)`` (the audit identity)."""
    lines = [
        "",                                                # leading blank
        _line({"type": "user"}),                           # survivor
        "   \n",                                           # whitespace-only
        _line({"type": "attachment", "blob": "AAA"}),      # stripped
        "\t",                                              # tabs only
        "\n",                                              # trailing newline
    ]
    out, counts = run_pipeline(lines)
    assert len(out) == 1
    assert counts.blank_lines == 4
    assert dict(counts.stripped_lines) == {"attachment": 1}
    # The audit identity from PRD §10 / sidecar.build_sidecar.
    total = len(out) + sum(counts.stripped_lines.values()) + counts.blank_lines
    assert total == len(lines)


def test_blank_lines_counter_zero_when_no_blanks() -> None:
    """Regression guard: a file with no whitespace-only lines reports
    ``blank_lines == 0``. Pins the default and ensures the new counter
    can't drift to a non-zero baseline that would inflate ``lines_processed``
    on the modal hand-authored fixture."""
    lines = [_line({"type": "user"}), _line({"type": "assistant"})]
    out, counts = run_pipeline(lines)
    assert len(out) == 2
    assert counts.blank_lines == 0


def test_transform_with_subtable_keeps_within_file_consistency() -> None:
    """A transform that funnels through a SubstitutionTable applies the
    same replacement to the same original on every line — the property
    PRD section 7 calls out as the safety reason per-file runs are safe.
    """
    table = SubstitutionTable()

    def transform(leaf: str, path: tuple[str, ...]) -> str:
        if "/home/fdpearce" in leaf:
            replaced = leaf.replace("/home/fdpearce", "/home/user")
            table.record("/home/fdpearce", "/home/user", label="paths")
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


def test_pipeline_counts_are_immutable_proxy() -> None:
    """PipelineCounts.stripped_lines is a MappingProxyType so callers cannot
    silently corrupt the sidecar's tallies after the fact."""
    lines = [_line({"type": "attachment"})]
    _, counts = run_pipeline(lines)
    with pytest.raises(TypeError):
        counts.stripped_lines["new_key"] = 999  # type: ignore[index]
