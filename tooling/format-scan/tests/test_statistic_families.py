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


# --- review-round fixes (PR #239) --------------------------------------------


def test_api_error_lines_are_counted(tmp_path):
    """`isApiErrorMessage` is surfaced in the report and named in the CHANGELOG
    as the candidate explanation for the absent-`stop_reason` bucket, so an
    inverted condition or a misspelled field would ship silently."""
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            {**_assistant("a1", stop_reason=None), "isApiErrorMessage": True},
            {**_assistant("a2", stop_reason=None), "isApiErrorMessage": False},
            _assistant("a3", stop_reason="end_turn"),
        ],
    )
    ms = _report(tmp_path)["message_shape"]
    assert ms["assistant_lines"] == 3
    assert ms["assistant_api_error_lines"] == 1


def test_multiple_tool_results_on_one_line_do_not_share_one_envelope(tmp_path):
    """`toolUseResult` is one key on the LINE, not per block.

    tool-invocation.md:526 records that the results of a parallel turn "may
    arrive in one `user` line or across several". Crediting the line's single
    envelope to each block would both inflate the conditional-key counts and
    hand one tool's keys to another — so a multi-block line is recorded as
    unattributable instead. Not currently observed in the local corpus (every
    line there carries exactly one block), which is what makes it worth pinning:
    nothing else would catch the regression.
    """
    lines = [
        {
            "type": "assistant",
            "uuid": "a1",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Edit"},
                    {"type": "tool_use", "id": "t2", "name": "Agent"},
                ]
            },
        },
        {
            "type": "user",
            "uuid": "u1",
            # ONE envelope, TWO results, and it cannot belong to both.
            "toolUseResult": {"structuredPatch": [], "prompt": "x"},
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1"},
                    {"type": "tool_result", "tool_use_id": "t2"},
                ]
            },
        },
    ]
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    by_tool = _report(tmp_path)["tool_cycle"]["by_tool"]
    assert by_tool["Edit"]["results"] == 1
    assert by_tool["Agent"]["results"] == 1
    # Neither gets a conditional-key credit, and neither is recorded as having
    # had no envelope at all.
    assert by_tool["Edit"]["toolUseResult_ambiguous_multi_block"] == 1
    assert by_tool["Agent"]["toolUseResult_ambiguous_multi_block"] == 1
    assert "structuredPatch" not in by_tool["Edit"]
    assert "prompt" not in by_tool["Agent"]
    assert "toolUseResult_dict" not in by_tool["Edit"]


def test_null_is_distinct_from_absent_in_every_classifier(tmp_path):
    """The `_MISSING` rationale applied consistently.

    A null is a real observation, not an absence — the distinction reference/
    cites separately for `stop_reason`. It must not be collapsed into a
    catch-all on the other families either.
    """
    lines = [
        {"type": "user", "uuid": "u1", "message": {"content": None}},
        {"type": "user", "uuid": "u2", "message": {}},
        {"type": "user", "uuid": "u3", "message": {"content": 42}},
    ]
    lines += [
        {
            "type": "assistant",
            "uuid": "a1",
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Edit"}]},
        },
        {
            "type": "user",
            "uuid": "u4",
            "toolUseResult": None,
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]},
        },
    ]
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    report = _report(tmp_path)
    assert report["message_shape"]["user_content_shape"] == {
        "null": 1,
        "absent": 1,
        "other": 1,
        "list": 1,  # u4 carries the tool_result list
    }
    assert report["tool_cycle"]["by_tool"]["Edit"]["toolUseResult_null"] == 1


def test_non_string_stop_sequence_is_not_reported_as_non_empty_string(tmp_path):
    """`non_empty_string` is the one label that would contradict
    data-dictionary.md:100's claim about this field, so a malformed value
    landing there would read as a substantive format finding."""
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[_assistant("a1", stop_reason="end_turn", stop_sequence=["x"])],
    )
    states = _report(tmp_path)["message_shape"]["stop_sequence_state_by_model_bucket"]
    assert states["absent"] == {"non_string": 1}


def test_sidechain_line_counts_are_reported(tmp_path):
    """message_shape POOLS subagent and parent traffic, so the artifact has to
    say how much of it is which — tool-invocation.md:524 warns that mixing the
    two puts a subagent's parallelism into the parent's numbers."""
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            _assistant("a1", stop_reason="end_turn"),
            {**_assistant("a2", stop_reason="end_turn"), "isSidechain": True},
            {"type": "user", "uuid": "u1", "message": {"content": "hi"}},
            {"type": "user", "uuid": "u2", "isSidechain": True, "message": {"content": "hi"}},
        ],
    )
    ms = _report(tmp_path)["message_shape"]
    assert (ms["assistant_lines"], ms["assistant_lines_sidechain"]) == (2, 1)
    assert (ms["user_lines"], ms["user_lines_sidechain"]) == (2, 1)
    assert "scope" in ms["denominators"], "the pooling must be stated, not implied"


# --- round-3 fixes: the human-report path, previously untested ----------------


def _human_report(root: Path, capsys) -> str:
    obs = scan_mod.Observation()
    scan_mod.scan(root, obs)
    scan_mod.print_human(scan_mod.build_report(obs, None))
    return capsys.readouterr().out


def _populated(tmp_path) -> None:
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[
            _assistant("a1", model="claude-real-1", stop_reason="tool_use"),
            _assistant("a2", model=scan_mod.SYNTHETIC_MODEL_MARKER, stop_reason="stop_sequence",
                       stop_sequence=""),
            _assistant("a3", stop_reason="not_a_documented_value"),
        ]
        + _cycle("Edit", "t1", {"structuredPatch": []}),
    )


def test_human_table_column_count_is_consistent(tmp_path, capsys):
    """The invariant the one-column-list refactor exists to protect.

    The header, the separator and every row must carry the same number of
    cells. Before the refactor the separator width was hand-derived and agreed
    with the header only by coincidence, so adding a label to the fold would
    have produced a malformed table with nothing to catch it.
    """
    _populated(tmp_path)
    out = _human_report(tmp_path, capsys)

    table = [ln for ln in out.splitlines() if ln.startswith("| ")]
    assert table, "the stop_reason table did not render at all"
    widths = {ln.count("|") for ln in table}
    assert len(widths) == 1, f"ragged table: differing pipe counts {widths}"
    # Header cells must match the fold's vocabulary exactly, so a value the
    # JSON can emit can never be missing a column.
    header = [c.strip(" `") for c in table[0].split("|")[2:-1]]
    assert set(header) == set(scan_mod.STOP_REASON_VALUES) | {
        scan_mod.OTHER_BUCKET,
        "<null>",
        "<absent>",
    }


def test_human_table_labels_are_backticked(tmp_path, capsys):
    """`<other>`, `<null>` and `<absent>` are parsed as HTML tags by markdown.

    Unbackticked they render as blank column headers — and `<other>` is the
    drift column a reader most needs to find.
    """
    _populated(tmp_path)
    out = _human_report(tmp_path, capsys)
    header = next(ln for ln in out.splitlines() if ln.startswith("| model bucket"))
    for label in (scan_mod.OTHER_BUCKET, "<null>", "<absent>"):
        assert f"`{label}`" in header
        assert f"| {label} " not in header, f"{label} is unbackticked and will render blank"


def test_unreadable_file_is_counted_and_does_not_break_the_identity(tmp_path):
    """A path that cannot be opened must be counted, not silently swallowed.

    A directory named `*.jsonl` raises IsADirectoryError, an OSError, on the
    same handler a mid-read failure takes. The join buffer is dropped either
    way, so the identity has to survive it.
    """
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=_cycle("Edit", "t1", {"structuredPatch": []}),
    )
    (tmp_path / "proj" / "broken.jsonl").mkdir()

    tc = _report(tmp_path)["tool_cycle"]
    assert tc["files_dropped_mid_read"] == 1
    assert tc["tool_result_blocks"] == tc["resolved"] + sum(tc["orphaned"].values())


def test_multi_block_line_without_an_envelope_is_absent_not_ambiguous(tmp_path):
    """Ambiguity requires something to be ambiguous about.

    A multi-block line carrying no `toolUseResult` has no body to misattribute,
    so labelling it `ambiguous_multi_block` would under-count `absent` and
    over-count a shape that is supposed to mean "an envelope exists but belongs
    to no single result".
    """
    lines = [
        {
            "type": "assistant",
            "uuid": "a1",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Edit"},
                    {"type": "tool_use", "id": "t2", "name": "Edit"},
                ]
            },
        },
        {
            "type": "user",
            "uuid": "u1",  # two blocks, NO toolUseResult key
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1"},
                    {"type": "tool_result", "tool_use_id": "t2"},
                ]
            },
        },
    ]
    make_session(tmp_path, slug="proj", session_id="s", lines=lines)

    row = _report(tmp_path)["tool_cycle"]["by_tool"]["Edit"]
    assert row["toolUseResult_absent"] == 2
    assert "toolUseResult_ambiguous_multi_block" not in row


def test_new_classifier_labels_are_defined_in_the_artifact(tmp_path):
    """"Denominators carried in the artifact, not just in code" has to cover
    the labels too, or a reader meets `non_string` with nothing to read."""
    _populated(tmp_path)
    report = _report(tmp_path)
    ms = report["message_shape"]["denominators"]
    tc = report["tool_cycle"]["denominators"]
    assert "stop_sequence_state" in ms
    assert "non_string" in ms["stop_sequence_state"]
    assert "null" in ms["user_content_shape"] and "absent" in ms["user_content_shape"]
    assert "ambiguous_multi_block" in tc["by_tool_envelope"]
    assert "non_dict" in tc["by_tool_envelope"] and "null" in tc["by_tool_envelope"]
    # D1: the dropped-file clause must not over-claim.
    assert "MAY be lower" in tc["tool_result_blocks"]


# --- tool-results filename prefixes (found by the human PII gate) -------------


def test_tool_result_prefix_folds_everything_outside_the_allowlist(tmp_path):
    """The prefix probe was emitting corpus-derived filename stems.

    Its comment claimed the prefix is "a tool-kind label ... not content". A
    real-corpus run produced 466 distinct prefixes of which only four were
    tool-kind labels; the rest were per-invocation ids, `webfetch-<epoch_ms>`
    stems whose timestamps decode to wall-clock activity times, and a fetched
    document's own filename. The extraction yields a label only when the name
    happens to be `<kind>_<id>.<ext>`; with no underscore it returns whole.
    """
    make_session(
        tmp_path,
        slug="proj",
        session_id="s",
        lines=[_assistant("a1", stop_reason="end_turn")],
        tool_results={
            "toolu_abc123.txt": b"allowlisted kind",
            "b8izep274.txt": b"per-invocation id, no underscore",
            "webfetch-1788165432286-708a3z.txt": b"decodable timestamp",
            "chiafalo.pdf": b"a fetched document's own name",
            "mcp-github-list_toolu_9.txt": b"server name inside the stem",
        },
    )
    prefixes = _report(tmp_path)["tool_results"]["name_prefixes"]
    assert prefixes == {
        "toolu": 1,
        "mcp": 1,          # the family is countable; the server name is not
        scan_mod.OTHER_BUCKET: 3,
    }
    # The specific strings must be gone, not merely reduced in count.
    blob = str(_report(tmp_path))
    for leaked in ("b8izep274", "1788165432286", "708a3z", "chiafalo", "github"):
        assert leaked not in blob, f"{leaked!r} survived the fold"
