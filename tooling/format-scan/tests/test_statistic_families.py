"""Functional tests for the five statistic families added in issue #237.

These are the *correctness* half. The *security* half lives in
``test_content_free_contract.py``, which plants sentinels in every surface these
counters read and asserts none reaches stdout; the two suites are deliberately
separate, because a counter can be perfectly correct and still leak.

The emphasis here is denominators. The 2026-08-25 pass that produced Part 5's
figures stated none of its definitions, which is why its numbers could not be
re-derived and why this issue exists. So most of what follows pins a denominator
rather than a headline number: the three-way ``stop_reason`` presence split, the
per-file join scope, the bare-string ``toolUseResult`` shape, and the folds.

Run: ``python3 -m pytest tooling/format-scan/tests/``
"""

from __future__ import annotations

from pathlib import Path

from ._helpers import load_scan, make_session

scan_mod = load_scan()


def _report(root: Path, max_files: int | None = None) -> dict:
    obs = scan_mod.Observation()
    scan_mod.scan(root, obs, max_files=max_files)
    return scan_mod.build_report(obs, None, max_files=max_files)


def _assistant(uuid: str, **message) -> dict:
    return {"type": "assistant", "uuid": uuid, "version": "2.1.150", "message": message}


# --- family 1: stop_reason ----------------------------------------------------


def test_stop_reason_presence_is_three_way(tmp_path):
    """Key-absent, present-null and present-non-null are counted separately.

    reference/data-dictionary.md:99 treats a null `stop_reason` as a real
    observation — a line recording an incomplete turn, explicitly "not safe to
    discard" — rather than as an absence. Collapsing the two would merge counts
    that reference/ cites separately, and a real-corpus sample turned out to be
    *entirely* present-null with zero truly-absent, so a two-way split would
    have mislabelled 100% of that bucket.
    """
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            _assistant("a1", stop_reason="end_turn"),
            _assistant("a2", stop_reason=None),
            _assistant("a3"),  # key absent entirely
        ],
    )
    ms = _report(tmp_path)["message_shape"]
    assert ms["assistant_lines"] == 3
    assert ms["stop_reason_presence"] == {
        "present_non_null": 1,
        "present_null": 1,
        "absent": 1,
    }


def test_unrecognized_stop_reason_folds_and_is_never_emitted(tmp_path):
    """An undocumented value folds to `<other>` rather than being echoed.

    This is the whole of why `stop_reason` can sit on EMITTABLE_VALUE_FIELDS at
    all: scan.py's whitelist bar is a CLOSED vocabulary, while the field is an
    OPEN enum (data-dictionary.md:99). The fold is what reconciles them, and a
    fold is not a drop — the count still surfaces as drift.
    """
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            _assistant("a1", stop_reason="a_value_nobody_has_documented"),
            _assistant("a2", stop_reason="refusal"),
        ],
    )
    report = _report(tmp_path)
    row = report["message_shape"]["stop_reason_by_model_bucket"]["absent"]
    assert row[scan_mod.OTHER_BUCKET] == 1, "undocumented value must fold"
    assert row["refusal"] == 1, "a documented value is emitted verbatim"
    assert "a_value_nobody_has_documented" not in str(report)


def test_every_documented_stop_reason_survives_the_fold(tmp_path):
    """All seven documented values pass through verbatim.

    Guards the fold against over-reach: a constant that drifts out of sync with
    data-dictionary.md:99 would silently bucket a real value as `<other>`, which
    reads as drift that is not there.
    """
    values = sorted(scan_mod.STOP_REASON_VALUES)
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[_assistant(f"a{i}", stop_reason=v) for i, v in enumerate(values)],
    )
    row = _report(tmp_path)["message_shape"]["stop_reason_by_model_bucket"]["absent"]
    assert {v: row.get(v) for v in values} == {v: 1 for v in values}
    assert scan_mod.OTHER_BUCKET not in row


def test_model_buckets_are_fixed_labels_and_never_the_model_string(tmp_path):
    """`absent` is its own bucket, not folded into `real`.

    A missing or null model is ambiguous about whether the line is real traffic.
    Defaulting it to `real` would overstate the real-traffic denominator, which
    is the number reference/ ends up citing.
    """
    secret_model = "claude-UNIQUEmodelSTRING-7"
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            _assistant("a1", model=secret_model, stop_reason="end_turn"),
            _assistant("a2", model=scan_mod.SYNTHETIC_MODEL_MARKER, stop_reason="end_turn"),
            _assistant("a3", model=None, stop_reason="end_turn"),
            _assistant("a4", stop_reason="end_turn"),
        ],
    )
    report = _report(tmp_path)
    buckets = report["message_shape"]["stop_reason_by_model_bucket"]
    assert buckets["real"]["end_turn"] == 1
    assert buckets["synthetic"]["end_turn"] == 1
    assert buckets["absent"]["end_turn"] == 2, "missing and null both land in absent"
    assert secret_model not in str(report)


# --- family 1b: the stop_sequence FIELD, not the stop_reason value ------------


def test_stop_sequence_state_is_four_way_and_value_free(tmp_path):
    """Classifies the field by shape, never by value.

    data-dictionary.md:100 stakes its claim on the FIELD — "normally present
    with a literal `null`", the only non-null instance being an empty string on
    a `<synthetic>` line. A `stop_reason` histogram cannot check that; this can,
    without emitting the value, which is why `stop_sequence` stays off the
    whitelist (it carries the caller-supplied matched sequence).
    """
    caller_sequence = "END-OF-CALLER-SEQUENCE-XYZ"
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            _assistant("a1", stop_reason="end_turn"),  # key absent
            _assistant("a2", stop_reason="end_turn", stop_sequence=None),
            _assistant("a3", stop_reason="stop_sequence", stop_sequence=""),
            _assistant("a4", stop_reason="stop_sequence", stop_sequence=caller_sequence),
        ],
    )
    report = _report(tmp_path)
    states = report["message_shape"]["stop_sequence_state_by_model_bucket"]["absent"]
    assert states == {
        "absent": 1,
        "null": 1,
        "empty_string": 1,
        "non_empty_string": 1,
    }
    assert caller_sequence not in str(report)


# --- family 2: user message.content shape ------------------------------------


def test_user_content_shape_split(tmp_path):
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            {"type": "user", "uuid": "u1", "message": {"content": [{"type": "text"}]}},
            {"type": "user", "uuid": "u2", "message": {"content": "a plain prompt"}},
            {"type": "user", "uuid": "u3", "message": {"content": {"odd": True}}},
            {"type": "user", "uuid": "u4", "message": {}},
        ],
    )
    ms = _report(tmp_path)["message_shape"]
    assert ms["user_lines"] == 4
    assert ms["user_content_shape"] == {"list": 1, "str": 1, "other": 1, "absent": 1}


# --- families 3-5: the per-file tool_use -> tool_result join ------------------


def _cycle(tool_name: str, tuid: str, tool_use_result, *, sidechain: bool = False) -> list[dict]:
    """One complete tool cycle: the ask, then the answer."""
    ask = {
        "type": "assistant",
        "uuid": "ask-" + tuid,
        "message": {"content": [{"type": "tool_use", "id": tuid, "name": tool_name}]},
    }
    answer = {
        "type": "user",
        "uuid": "ans-" + tuid,
        "isSidechain": sidechain,
        "message": {"content": [{"type": "tool_result", "tool_use_id": tuid}]},
    }
    if tool_use_result is not None:
        answer["toolUseResult"] = tool_use_result
    return [ask, answer]


def test_edit_denominator_is_the_join_not_the_key(tmp_path):
    """`structuredPatch` is NOT Edit-exclusive, so counting the key over-counts.

    This is a regression test for a real finding: a 60-file corpus sample showed
    `structuredPatch` on 146 results against only 138 `Edit` tool_uses.
    reference/tool-invocation.md documents it under both the Write envelope
    (:236) and the Edit envelope (:247). A denominator defined by the join gets
    this right; one defined by the key does not.
    """
    lines = []
    lines += _cycle("Edit", "t1", {"structuredPatch": [{"lines": []}]})
    lines += _cycle("Edit", "t2", {"filePath": "/x"})  # Edit, no patch
    lines += _cycle("Write", "t3", {"structuredPatch": [{"lines": []}]})  # patch, not Edit
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    by_tool = _report(tmp_path)["tool_cycle"]["by_tool"]
    assert by_tool["Edit"]["results"] == 2
    assert by_tool["Edit"]["structuredPatch"] == 1
    # The third patch is real, but it belongs to another tool and must not be
    # absorbed into the Edit numerator.
    assert by_tool[scan_mod.OTHER_BUCKET]["structuredPatch"] == 1


def test_bare_string_tool_use_result_is_counted_not_dropped(tmp_path):
    """tool-invocation.md:195 — `toolUseResult` is a bare string on a minority
    of results (240 on `Edit` alone). A dict-only denominator drops them
    silently, which is the same defect as a denominator that renormalizes."""
    lines = []
    lines += _cycle("Edit", "t1", {"structuredPatch": []})
    lines += _cycle("Edit", "t2", "raw output text with no envelope")
    lines += _cycle("Edit", "t3", None)  # key absent
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    row = _report(tmp_path)["tool_cycle"]["by_tool"]["Edit"]
    assert row["results"] == 3
    assert row["toolUseResult_dict"] == 1
    assert row["toolUseResult_non_dict"] == 1
    assert row["toolUseResult_absent"] == 1


def test_agent_conditional_keys_are_presence_counts(tmp_path):
    lines = []
    lines += _cycle("Agent", "t1", {"prompt": "go", "toolStats": {"readCount": 2}})
    lines += _cycle("Agent", "t2", {"prompt": "go"})
    lines += _cycle("Agent", "t3", {})
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    row = _report(tmp_path)["tool_cycle"]["by_tool"]["Agent"]
    assert row["results"] == 3
    assert row["prompt"] == 2
    assert row["toolStats"] == 1


def test_orphan_tool_results_split_on_sidechain(tmp_path):
    """An orphan is a tool_result whose id matches no tool_use IN ITS OWN FILE."""
    lines = _cycle("Edit", "matched", {"structuredPatch": []})
    lines.append(
        {
            "type": "user",
            "uuid": "o1",
            "isSidechain": False,
            "message": {"content": [{"type": "tool_result", "tool_use_id": "nope-1"}]},
        }
    )
    lines.append(
        {
            "type": "user",
            "uuid": "o2",
            "isSidechain": True,
            "message": {"content": [{"type": "tool_result", "tool_use_id": "nope-2"}]},
        }
    )
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    tc = _report(tmp_path)["tool_cycle"]
    assert tc["orphaned"] == {"parent": 1, "sidechain": 1}
    assert tc["resolved"] == 1


def test_the_join_does_not_reach_across_files(tmp_path):
    """Per-file is the correct scope, not merely the convenient one.

    reference/tool-invocation.md:83 documents that subagent traces carry their
    own `tool_use_id` space. A cross-file join would resolve an id that a real
    parser — which only ever has one file open — cannot, turning a genuine
    orphan into a false match. Here the same id is a tool_use in one session and
    a bare tool_result in another; it must stay orphaned.
    """
    make_session(
        tmp_path,
        slug="proj",
        session_id="s1",
        lines=_cycle("Edit", "shared-id", {"structuredPatch": []}),
    )
    make_session(
        tmp_path,
        slug="proj",
        session_id="s2",
        lines=[
            {
                "type": "user",
                "uuid": "u9",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "shared-id"}]},
            }
        ],
    )
    tc = _report(tmp_path)["tool_cycle"]
    assert tc["resolved"] == 1
    assert tc["orphaned"] == {"parent": 1}


def test_tool_result_block_identity_holds(tmp_path):
    """`tool_result_blocks == resolved + orphaned`, by construction.

    The count is taken off the per-file buffer rather than at capture time
    precisely so this holds even when a file dies mid-read and its buffer is
    dropped.
    """
    lines = _cycle("Edit", "t1", {"structuredPatch": []}) + _cycle("Agent", "t2", {"prompt": "x"})
    lines.append(
        {
            "type": "user",
            "uuid": "o1",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "unmatched"}]},
        }
    )
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    tc = _report(tmp_path)["tool_cycle"]
    assert tc["tool_result_blocks"] == tc["resolved"] + sum(tc["orphaned"].values())
    assert tc["tool_result_blocks"] == 3


def test_unallowlisted_tool_name_folds_and_is_never_emitted(tmp_path):
    """Tool names are not a closed vocabulary.

    MCP tools carry server-derived names and plugin/user tools carry
    author-chosen ones — the same disqualifier scan.py:100-102 already applies to
    `agentType`. So an unallowlisted name folds to `<other>` and never appears.
    """
    mcp_name = "mcp__PRIVATEserverNAME__doThing"
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=_cycle(mcp_name, "t1", {"stdout": ""}),
    )
    report = _report(tmp_path)
    assert report["tool_cycle"]["by_tool"][scan_mod.OTHER_BUCKET]["results"] == 1
    assert mcp_name not in str(report)
    assert "PRIVATEserverNAME" not in str(report)


# --- provenance ---------------------------------------------------------------


def test_max_files_is_recorded_in_the_summary(tmp_path):
    """Part of the corpus fingerprint AC-7 asks for.

    `files_scanned` alone cannot distinguish a full scan of N files from a
    `--max-files N` sample of a much larger corpus, so a retained artifact
    without this is not comparable against a later re-run.
    """
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[_assistant("a1", stop_reason="end_turn")],
    )
    assert _report(tmp_path)["summary"]["max_files"] is None
    assert _report(tmp_path, max_files=1)["summary"]["max_files"] == 1


def test_report_carries_its_own_denominator_definitions(tmp_path):
    """I3: a reader of the retained artifact can check a figure without reading
    scan.py. The 2026-08-25 pass stated none of these, which is the defect."""
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[_assistant("a1", stop_reason="end_turn")],
    )
    report = _report(tmp_path)
    assert set(report["message_shape"]["denominators"]) >= {
        "stop_reason",
        "user_content_shape",
        "model_bucket",
        "stop_reason_values",
    }
    assert set(report["tool_cycle"]["denominators"]) >= {
        "tool_result_blocks",
        "resolution",
        "orphaned",
        "by_tool",
    }
