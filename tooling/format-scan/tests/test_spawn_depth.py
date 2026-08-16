"""Tests for the per-version manifest bucketing and the nesting probe (issue #169).

Two surfaces, both added to answer "what depth did subagents actually reach, at
which Claude Code version" from observation rather than from the CHANGELOG:

  - ``meta_json_by_version`` in the default report — manifest shape bucketed by
    the CC version that produced it, with a value histogram for the tightly
    whitelisted ``spawnDepth``.
  - ``--probe-nesting`` — nested ``subagents/`` directory counts, the spawnDepth
    histogram, and whether the spawning ``Agent`` tool_result carries a
    ``toolUseResult`` rollup sibling at each depth.

Fixtures are synthetic, per the CLAUDE.md security posture. The leak gate for
these modes lives in ``test_content_free_contract.py``.

Run: ``python3 -m pytest tooling/format-scan/tests/``
"""

from __future__ import annotations

import json
from pathlib import Path

from ._helpers import load_scan, make_session, write_jsonl

scan_mod = load_scan()


def _scan(root: Path):
    obs = scan_mod.Observation()
    scan_mod.scan(root, obs)
    return obs


def _report(root: Path) -> dict:
    return scan_mod.build_report(_scan(root), None)


# --- version_sort_key --------------------------------------------------------


def test_version_sort_key_orders_numerically_not_lexically():
    """"2.1.99" < "2.1.150" — plain string sort gets this backwards."""
    vsk = scan_mod.version_sort_key
    versions = ["2.1.150", "2.1.99", "2.1.9", "2.1.226", "2.2.0"]
    assert sorted(versions, key=vsk) == ["2.1.9", "2.1.99", "2.1.150", "2.1.226", "2.2.0"]
    assert sorted(versions) != sorted(versions, key=vsk)  # the bug being prevented


def test_version_sort_key_totally_orders_unparseable_versions():
    """A junk version must still sort, not raise, and lands after numeric ones."""
    vsk = scan_mod.version_sort_key
    assert sorted(["2.1.5", "<absent>", "2.1.10"], key=vsk) == ["2.1.5", "2.1.10", "<absent>"]


# --- meta_json_by_version ----------------------------------------------------


def _versioned_tree(root: Path) -> None:
    """Three manifests across two CC versions, one of them at spawnDepth 2."""
    make_session(
        root,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.195",
                "message": {"content": [{"type": "text"}]}}],
        subagent_traces={
            "agent-old.jsonl": [
                {"type": "assistant", "uuid": "s1", "version": "2.1.150",
                 "message": {"content": [{"type": "text"}]}},
            ],
            "agent-d1.jsonl": [
                {"type": "assistant", "uuid": "s2", "version": "2.1.195",
                 "message": {"content": [{"type": "text"}]}},
            ],
            "agent-d2.jsonl": [
                {"type": "assistant", "uuid": "s3", "version": "2.1.195",
                 "message": {"content": [{"type": "text"}]}},
            ],
        },
        meta_manifests={
            # Pre-spawnDepth vintage: the key simply isn't there yet.
            "agent-old.meta.json": {"agentType": "pm", "description": "old one"},
            "agent-d1.meta.json": {"agentType": "pm", "spawnDepth": 1,
                                   "toolUseId": "toolu_d1"},
            "agent-d2.meta.json": {"agentType": "pm", "spawnDepth": 2,
                                   "toolUseId": "toolu_d2"},
        },
    )


def test_manifests_bucket_by_their_own_trace_version(tmp_path):
    _versioned_tree(tmp_path)
    mv = _report(tmp_path)["meta_json_by_version"]

    assert mv["manifests_attributed"] == 3
    assert mv["manifests_unattributed"] == 0
    assert set(mv["versions"]) == {"2.1.150", "2.1.195"}
    assert mv["versions"]["2.1.150"]["manifests"] == 1
    assert mv["versions"]["2.1.195"]["manifests"] == 2


def test_spawn_depth_values_are_emitted_as_a_per_version_histogram(tmp_path):
    """spawnDepth is on EMITTABLE_META_VALUE_FIELDS, so its VALUES are reported —
    that histogram is the whole point of the probe."""
    _versioned_tree(tmp_path)
    mv = _report(tmp_path)["meta_json_by_version"]

    assert mv["versions"]["2.1.195"]["values"]["spawnDepth"] == {"1": 1, "2": 1}
    # The pre-spawnDepth bucket shows the key's ABSENCE, which is the drift signal.
    assert "spawnDepth" not in mv["versions"]["2.1.150"]["keys"]
    assert mv["versions"]["2.1.150"]["values"] == {}


def test_non_whitelisted_manifest_values_never_reach_the_buckets(tmp_path):
    """Only EMITTABLE_META_VALUE_FIELDS contribute values. Everything else
    contributes a key name and a count, and nothing more."""
    _versioned_tree(tmp_path)
    mv = _report(tmp_path)["meta_json_by_version"]

    assert mv["versions"]["2.1.150"]["keys"] == {"agentType": 1, "description": 1}
    for bucket in mv["versions"].values():
        assert set(bucket["values"]) <= scan_mod.EMITTABLE_META_VALUE_FIELDS


def test_versions_are_ordered_numerically_in_the_report(tmp_path):
    """Report order is the reading order for a drift table, so it must be the
    real version order, not "2.1.150" < "2.1.99"."""
    make_session(
        tmp_path,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.99"}],
        subagent_traces={
            "a.jsonl": [{"type": "assistant", "version": "2.1.99"}],
            "b.jsonl": [{"type": "assistant", "version": "2.1.150"}],
            "c.jsonl": [{"type": "assistant", "version": "2.1.9"}],
        },
        meta_manifests={
            "a.meta.json": {"agentType": "pm"},
            "b.meta.json": {"agentType": "pm"},
            "c.meta.json": {"agentType": "pm"},
        },
    )
    versions = list(_report(tmp_path)["meta_json_by_version"]["versions"])
    assert versions == ["2.1.9", "2.1.99", "2.1.150"]


def test_multi_version_trace_attributes_to_the_spawn_time_version(tmp_path):
    """A trace spanning a CC upgrade buckets at its EARLIEST version (the manifest
    is written at spawn time), and the span is counted so the caveat stays visible."""
    make_session(
        tmp_path,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.195"}],
        subagent_traces={
            "agent-span.jsonl": [
                {"type": "assistant", "uuid": "s1", "version": "2.1.195"},
                {"type": "assistant", "uuid": "s2", "version": "2.1.196"},
            ],
        },
        meta_manifests={"agent-span.meta.json": {"agentType": "pm", "spawnDepth": 1}},
    )
    mv = _report(tmp_path)["meta_json_by_version"]

    assert list(mv["versions"]) == ["2.1.195"]
    assert mv["traces_spanning_multiple_versions"] == 1


def test_manifest_without_a_versioned_trace_is_counted_unattributed(tmp_path):
    """A manifest whose trace is missing or carries no version must not be
    silently dropped — an invisible shortfall would understate every bucket."""
    make_session(
        tmp_path,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.195"}],
        subagent_traces={"agent-nov.jsonl": [{"type": "assistant", "uuid": "s1"}]},
        meta_manifests={
            "agent-nov.meta.json": {"agentType": "pm"},   # trace has no version
            "agent-gone.meta.json": {"agentType": "pm"},  # no trace file at all
        },
    )
    mv = _report(tmp_path)["meta_json_by_version"]

    assert mv["manifests_attributed"] == 0
    assert mv["manifests_unattributed"] == 2
    # The unbucketed probe still sees both, so the two counts reconcile.
    assert _report(tmp_path)["meta_json_keys"]["files"] == 2


def test_parent_session_version_does_not_leak_into_the_buckets(tmp_path):
    """Attribution is by the subagent's OWN trace. Falling back to the parent
    session's version would misdate every manifest in a long-running session."""
    _versioned_tree(tmp_path)
    mv = _report(tmp_path)["meta_json_by_version"]

    # The parent transcript is at 2.1.195, but agent-old's trace is at 2.1.150.
    assert mv["versions"]["2.1.150"]["manifests"] == 1


# --- --probe-nesting ---------------------------------------------------------


def _nesting_tree(root: Path, *, nested_dir: bool = False) -> None:
    """A depth-1 and a depth-2 subagent, with their spawning tool_result lines.

    The depth-1 spawn site sits in the parent transcript; the depth-2 spawn site
    sits inside the depth-1 subagent's own trace, which is what "flat directory,
    by-data linkage" looks like on disk. The depth-2 line deliberately omits the
    ``toolUseResult`` sibling and carries the inline trailer instead, so the probe
    has a real contrast to measure.
    """
    make_session(
        root,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[
            {"type": "user", "uuid": "u1", "version": "2.1.226", "toolUseResult": {"x": 1},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_d1",
                                      "content": "done"}]}},
        ],
        subagent_traces={
            "agent-d1.jsonl": [
                {"type": "user", "uuid": "s1", "version": "2.1.226",
                 "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_d2",
                                          "content": "done (subagent_tokens: 1234)"}]}},
            ],
            "agent-d2.jsonl": [
                {"type": "assistant", "uuid": "s2", "version": "2.1.226"},
            ],
        },
        meta_manifests={
            "agent-d1.meta.json": {"agentType": "pm", "spawnDepth": 1,
                                   "toolUseId": "toolu_d1"},
            "agent-d2.meta.json": {"agentType": "pm", "spawnDepth": 2,
                                   "toolUseId": "toolu_d2"},
        },
    )
    if nested_dir:
        nested = root / "-home-user-proj" / "sess-1" / "subagents" / "agent-d1" / "subagents"
        write_jsonl(nested / "agent-d3.jsonl", [{"type": "assistant", "version": "2.1.226"}])


def test_probe_nesting_reports_zero_nested_dirs_for_a_flat_layout(tmp_path):
    _nesting_tree(tmp_path)
    result = scan_mod.probe_nesting(tmp_path)

    assert result["session_dirs"] == 1
    assert result["nested_subagent_dirs"] == 0
    assert result["manifests"] == 2


def test_probe_nesting_detects_a_nested_subagents_directory(tmp_path):
    """Guards against a vacuous "layout is flat" conclusion: if the runtime ever
    does nest, the counter has to move."""
    _nesting_tree(tmp_path, nested_dir=True)
    assert scan_mod.probe_nesting(tmp_path)["nested_subagent_dirs"] == 1


def test_probe_nesting_histograms_spawn_depth_including_absence(tmp_path):
    _nesting_tree(tmp_path)
    make_session(
        tmp_path,
        slug="-home-user-other",
        session_id="sess-2",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.150"}],
        subagent_traces={"agent-old.jsonl": [{"type": "assistant", "version": "2.1.150"}]},
        meta_manifests={"agent-old.meta.json": {"agentType": "pm"}},
    )
    hist = scan_mod.probe_nesting(tmp_path)["spawn_depth_histogram"]

    assert hist == {"1": 1, "2": 1, "<absent>": 1}


def test_probe_nesting_contrasts_rollup_shape_across_depths(tmp_path):
    """The load-bearing measurement: does the depth-2 spawn site still carry a
    toolUseResult rollup, or only the inline subagent_tokens trailer?"""
    _nesting_tree(tmp_path)
    by_depth = scan_mod.probe_nesting(tmp_path)["by_spawn_depth"]

    assert by_depth["1"]["has_toolUseResult_sibling"] == 1
    assert "no_toolUseResult_sibling" not in by_depth["1"]
    assert by_depth["2"]["no_toolUseResult_sibling"] == 1
    assert by_depth["2"]["has_subagent_tokens_trailer"] == 1
    assert "has_toolUseResult_sibling" not in by_depth["2"]


def test_probe_nesting_reports_which_file_holds_each_spawn_site(tmp_path):
    """Where the spawning tool_result lives is what a parser has to walk: the
    depth-1 site is in the parent transcript, the depth-2 site in a trace file."""
    _nesting_tree(tmp_path)
    by_depth = scan_mod.probe_nesting(tmp_path)["by_spawn_depth"]

    assert by_depth["1"]["container:parent-session"] == 1
    assert by_depth["2"]["container:subagent-trace"] == 1


def test_probe_nesting_counts_manifests_whose_spawn_site_is_missing(tmp_path):
    """An unlocatable spawn site must be reported, not quietly excluded — the
    denominator is how you tell "no rollup" from "never looked"."""
    make_session(
        tmp_path,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.226"}],
        subagent_traces={"agent-d2.jsonl": [{"type": "assistant", "version": "2.1.226"}]},
        meta_manifests={"agent-d2.meta.json": {"agentType": "pm", "spawnDepth": 2,
                                               "toolUseId": "toolu_orphan"}},
    )
    result = scan_mod.probe_nesting(tmp_path)

    assert result["joinable_manifests"] == 1
    assert result["spawn_sites_located"] == 0
    assert result["spawn_sites_not_located"] == 1


def test_probe_nesting_skips_manifests_that_cannot_be_joined(tmp_path):
    """No spawnDepth or no toolUseId means no join key, so the manifest is counted
    but contributes no depth row."""
    make_session(
        tmp_path,
        slug="-home-user-proj",
        session_id="sess-1",
        lines=[{"type": "user", "uuid": "u1", "version": "2.1.150"}],
        subagent_traces={"agent-a.jsonl": [{"type": "assistant", "version": "2.1.150"}]},
        meta_manifests={"agent-a.meta.json": {"agentType": "pm", "description": "d"}},
    )
    result = scan_mod.probe_nesting(tmp_path)

    assert result["manifests"] == 1
    assert result["joinable_manifests"] == 0
    assert result["by_spawn_depth"] == {}


def test_probe_nesting_tolerates_a_malformed_manifest(tmp_path):
    _nesting_tree(tmp_path)
    bad = tmp_path / "-home-user-proj" / "sess-1" / "subagents" / "agent-bad.meta.json"
    bad.write_text("{not json", encoding="utf-8")

    result = scan_mod.probe_nesting(tmp_path)
    assert result["manifests"] == 2  # the malformed one is skipped, not fatal


def test_probe_nesting_json_mode_runs_from_the_cli(tmp_path, capsys):
    _nesting_tree(tmp_path)
    assert scan_mod.main([str(tmp_path), "--probe-nesting", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["nested_subagent_dirs"] == 0
    assert payload["by_spawn_depth"]["2"]["no_toolUseResult_sibling"] == 1
