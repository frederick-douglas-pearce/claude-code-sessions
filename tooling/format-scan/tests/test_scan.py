"""Functional tests for tooling/format-scan/scan.py (issues #96, #97).

Covers the taxonomy/diff output, the #96 ``meta.json`` manifest probe, and the
``--probe-tool-results`` markers. The content-free security contract lives in
``test_content_free_contract.py`` — that's the high-value gate; this file pins
that the scanner reports the right *shapes*.

Run: ``python3 -m pytest tooling/format-scan/tests/``
"""

from __future__ import annotations

from pathlib import Path

from ._helpers import BASELINE, load_scan, make_session

scan_mod = load_scan()


def _scan(root: Path):
    obs = scan_mod.Observation()
    scan_mod.scan(root, obs)
    return obs


def _build_full_tree(root: Path) -> None:
    """A two-session tree exercising every probe surface."""
    make_session(
        root,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[
            {"type": "user", "uuid": "u1", "version": "2.1.150",
             "message": {"content": [{"type": "text"}]}},
            {"type": "assistant", "uuid": "a1", "version": "2.1.150",
             "message": {"content": [{"type": "tool_use"}, {"type": "thinking"}]}},
            {"type": "user", "uuid": "u2", "version": "2.1.150", "toolUseResult": {},
             "message": {"content": [{"type": "tool_result"}]}},
        ],
        subagent_traces={
            "agent-abc.jsonl": [
                {"type": "assistant", "uuid": "s1", "isSidechain": True,
                 "attributionAgent": "general-purpose",
                 "message": {"content": [{"type": "text"}]}},
            ],
        },
        meta_manifests={
            "agent-abc.meta.json": {
                "agentType": "general-purpose",
                "description": "look at the thing",
                "toolUseId": "toolu_01abc",
            },
            "agent-def.meta.json": {
                "agentType": "pm",
                "worktreePath": "/tmp/wt/x",
            },
        },
        tool_results={
            "toolu_01abc_0.txt": b"some externalized output",
            "mcp-github-list_0.json": b"{}",
        },
    )


# --- functional: taxonomy ----------------------------------------------------


def test_top_level_types_and_keys(tmp_path):
    _build_full_tree(tmp_path)
    obs = _scan(tmp_path)
    report = scan_mod.build_report(obs, None)

    assert report["top_level_types"]["user"] == 2
    assert report["top_level_types"]["assistant"] == 2  # 1 parent + 1 subagent
    # keys_by_type mirrors per-type envelope keys.
    assert "toolUseResult" in report["keys_by_type"]["user"]
    assert report["content_block_types"]["tool_result"] == 1
    assert report["content_block_types"]["thinking"] == 1
    # tool_result-bearing user line key hunt picked up the externalization key.
    assert "toolUseResult" in report["tool_result_line_keys"]


def test_session_subdirs_and_tool_results_shape(tmp_path):
    _build_full_tree(tmp_path)
    obs = _scan(tmp_path)
    report = scan_mod.build_report(obs, None)

    assert report["session_subdirs"]["subagents"] == 1
    assert report["session_subdirs"]["tool-results"] == 1
    tr = report["tool_results"]
    assert tr["extensions"] == {"txt": 1, "json": 1}
    assert "toolu" in tr["name_prefixes"]
    assert tr["size_bytes"]["count"] == 2


# --- functional: #96 meta.json probe -----------------------------------------


def test_meta_json_key_names_and_counts(tmp_path):
    _build_full_tree(tmp_path)
    obs = _scan(tmp_path)
    report = scan_mod.build_report(obs, None)

    mj = report["meta_json_keys"]
    assert mj["files"] == 2
    assert mj["parse_errors"] == 0
    assert mj["keys"] == {
        "agentType": 2,
        "description": 1,
        "toolUseId": 1,
        "worktreePath": 1,
    }


def test_meta_json_records_value_json_types_not_values(tmp_path):
    _build_full_tree(tmp_path)
    obs = _scan(tmp_path)
    report = scan_mod.build_report(obs, None)

    key_types = report["meta_json_keys"]["key_types"]
    assert key_types["agentType"] == {"str": 2}
    assert key_types["toolUseId"] == {"str": 1}
    assert key_types["worktreePath"] == {"str": 1}


def test_meta_json_json_type_helper():
    jt = scan_mod.json_type
    assert jt(None) == "null"
    assert jt(True) == "bool"  # bool before int
    assert jt(3) == "int"
    assert jt(3.5) == "float"
    assert jt("x") == "str"
    assert jt([1]) == "list"
    assert jt({"a": 1}) == "dict"


def test_meta_json_malformed_counts_as_parse_error(tmp_path):
    make_session(
        tmp_path, slug="-s", session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1"}],
        meta_manifests={"agent-ok.meta.json": {"agentType": "pm"}},
    )
    # Plant a non-JSON manifest beside the good one.
    bad = tmp_path / "-s" / "sess-1" / "subagents" / "agent-bad.meta.json"
    bad.write_text("{not valid json", encoding="utf-8")

    obs = _scan(tmp_path)
    report = scan_mod.build_report(obs, None)
    mj = report["meta_json_keys"]
    assert mj["files"] == 2
    assert mj["parse_errors"] == 1
    assert mj["keys"] == {"agentType": 1}


# --- functional: baseline diff -----------------------------------------------


def test_baseline_diff_no_drift_for_documented_keys(tmp_path):
    """All meta.json keys in the baseline -> no meta.json drift."""
    make_session(
        tmp_path, slug="-s", session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.150"}],
        meta_manifests={
            "agent-a.meta.json": {
                "agentType": "pm", "description": "d",
                "toolUseId": "t", "worktreePath": "/w",
            },
        },
    )
    obs = _scan(tmp_path)
    baseline = scan_mod.load_baseline(BASELINE)
    diff = scan_mod.diff_against_baseline(obs, baseline)
    assert diff["new_meta_json_keys"] == []


def test_baseline_diff_surfaces_new_meta_json_key(tmp_path):
    """The toolUseId/toolUseID casing split: a manifest spelling the id with the
    session-line casing (toolUseID) shows up as undocumented drift."""
    make_session(
        tmp_path, slug="-s", session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.150"}],
        meta_manifests={
            "agent-a.meta.json": {"agentType": "pm", "toolUseID": "t", "newKey": 1},
        },
    )
    obs = _scan(tmp_path)
    baseline = scan_mod.load_baseline(BASELINE)
    diff = scan_mod.diff_against_baseline(obs, baseline)
    assert diff["new_meta_json_keys"] == ["newKey", "toolUseID"]


# --- functional: tool-results probe ------------------------------------------


def test_probe_tool_results_counts_markers(tmp_path):
    make_session(
        tmp_path, slug="-s", session_id="sess-1",
        lines=[
            {"type": "user", "uuid": "u1",
             "message": {"content": [
                 {"type": "tool_result",
                  "content": "Preview (first 100 chars) ... truncated"},
             ]}},
            {"type": "user", "uuid": "u2",
             "message": {"content": [
                 {"type": "tool_result",
                  "content": [{"type": "text", "text": "saved to tool-results/"}]},
             ]}},
        ],
    )
    result = scan_mod.probe_tool_results(tmp_path)
    assert result["tool_result_string_contents"] == 2
    assert result["marker_counts"].get("Preview (first") == 1
    assert result["marker_counts"].get("truncated") == 1
    assert result["marker_counts"].get("tool-results/") == 1
