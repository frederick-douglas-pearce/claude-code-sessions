"""Tests for the release driver's decision logic (issue #181).

Scope is deliberate: the **pure predicates** in `release.py`, not the
subprocess-driven subcommands. Those predicates are where a subtle bug produces
a false green, which for release machinery in front of a published sanitizer is
the failure mode that matters. The side-effecting parts (`git push`,
`gh workflow run`) are covered by `--dry-run` and by the workflow's own gates.

`release.py` lives at the package root, which is NOT in the sdist `include`
allowlist, while `tests/` is. So this module skips rather than errors when run
from an unpacked sdist, where the suite is expected to be runnable end to end.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

RELEASE_PY = Path(__file__).resolve().parent.parent / "release.py"

if not RELEASE_PY.exists():  # pragma: no cover - only true inside an sdist
    pytest.skip("release.py is not shipped in the sdist", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("ccs_release", RELEASE_PY)
release = importlib.util.module_from_spec(_spec)
sys.modules["ccs_release"] = release
_spec.loader.exec_module(release)


# ---------------------------------------------------------------- version


def test_parse_version_reads_the_assignment():
    assert release.parse_version('__version__ = "0.3.0"\n') == "0.3.0"


def test_parse_version_ignores_lookalikes_elsewhere_in_the_file():
    source = '"""Docstring mentioning __version__ = "9.9.9" in prose."""\n__version__ = "0.3.0"\n'
    assert release.parse_version(source) == "0.3.0"


def test_parse_version_fails_closed_when_absent():
    with pytest.raises(release.ReleaseError):
        release.parse_version("VERSION = '0.3.0'\n")


def test_tag_is_component_scoped():
    # A bare v0.3.0 would fire the publish job on unrelated repo-level tags.
    assert release.tag_for("0.3.0") == "sanitizer-v0.3.0"


# -------------------------------------------------------------- changelog


def test_changelog_entry_found():
    assert release.changelog_has_entry("## [0.3.0] - 2026-08-17\n", "0.3.0")


def test_changelog_unreleased_heading_does_not_satisfy_a_version():
    assert not release.changelog_has_entry("## [Unreleased]\n", "0.3.0")


def test_changelog_dots_are_escaped():
    # Without re.escape, `0.3.0` matches `0x3y0`.
    assert not release.changelog_has_entry("## [0x3y0] - 2026-08-17\n", "0.3.0")


def test_changelog_heading_must_be_at_line_start():
    assert not release.changelog_has_entry("see ## [0.3.0] below\n", "0.3.0")


# ------------------------------------------------------------- check runs


def _check(name="sanitizer-ci", status="completed", conclusion="success", started="2026-08-18T00:00:00Z", id_=1):
    return {"name": name, "status": status, "conclusion": conclusion, "started_at": started, "id": id_}


def test_check_runs_green_passes():
    green, detail = release.evaluate_check_runs([_check()])
    assert green, detail


def test_absent_check_run_is_failure_not_pass():
    """The single most important assertion in this file.

    A commit with no `sanitizer-ci` check run has not been verified. Reading
    that as "nothing red, therefore fine" is exactly the inherited-status
    fallacy the release design rejects.
    """
    green, detail = release.evaluate_check_runs([])
    assert not green
    assert "no 'sanitizer-ci' check run" in detail


def test_other_checks_do_not_stand_in_for_the_gate():
    green, _ = release.evaluate_check_runs([_check(name="prettier"), _check(name="pytest (py3.11)")])
    assert not green


def test_failed_check_run_is_failure():
    green, detail = release.evaluate_check_runs([_check(conclusion="failure")])
    assert not green
    assert "failure" in detail


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "timed_out", "neutral", "action_required", None])
def test_only_success_counts(conclusion):
    green, _ = release.evaluate_check_runs([_check(conclusion=conclusion)])
    assert not green


def test_in_progress_check_run_is_not_yet_green():
    green, detail = release.evaluate_check_runs([_check(status="in_progress", conclusion=None)])
    assert not green
    assert "not completed" in detail


def test_most_recent_attempt_wins_over_an_earlier_failure():
    runs = [
        _check(conclusion="failure", started="2026-08-18T00:00:00Z", id_=1),
        _check(conclusion="success", started="2026-08-18T01:00:00Z", id_=2),
    ]
    assert release.evaluate_check_runs(runs)[0]


def test_a_later_failure_supersedes_an_earlier_success():
    runs = [
        _check(conclusion="success", started="2026-08-18T00:00:00Z", id_=1),
        _check(conclusion="failure", started="2026-08-18T01:00:00Z", id_=2),
    ]
    assert not release.evaluate_check_runs(runs)[0]


def test_missing_timestamps_do_not_crash_the_sort():
    runs = [{"name": "sanitizer-ci", "status": "completed", "conclusion": "success"}]
    assert release.evaluate_check_runs(runs)[0]


# ------------------------------------------------------- dispatched run id


SHA = "3f1f3a656bc8b843c32094d035df35090a85c93b"


def _run(id_, sha=SHA, event="workflow_dispatch"):
    return {"databaseId": id_, "headSha": sha, "event": event}


def test_picks_the_run_that_was_not_there_before():
    assert release.pick_dispatched_run([_run(1), _run(2)], SHA, {1})["databaseId"] == 2


def test_returns_none_before_the_run_appears():
    assert release.pick_dispatched_run([_run(1)], SHA, {1}) is None


def test_never_latches_onto_the_parked_tag_push_run():
    """The parked publish run shares the SHA and is not ours to watch.

    Watching it would block until someone approved the very upload the
    rehearsal is supposed to gate.
    """
    runs = [_run(7, event="push")]
    assert release.pick_dispatched_run(runs, SHA, set()) is None


def test_ignores_dispatch_runs_on_a_different_commit():
    assert release.pick_dispatched_run([_run(9, sha="deadbeef" * 5)], SHA, set()) is None


def test_ambiguity_raises_rather_than_guessing():
    """Two candidates must fail closed, not resolve to one of them.

    Picking either risks watching a run that already concluded `success`,
    which would report a rehearsal that never gated these bytes. That is the
    false-green the driver exists to prevent, so guessing is not an option
    however tempting the heuristic.
    """
    with pytest.raises(release.ReleaseError) as excinfo:
        release.pick_dispatched_run([_run(5), _run(3), _run(4)], SHA, {3})
    assert "refusing to guess" in str(excinfo.value)


def test_carries_the_run_url_through():
    run = dict(_run(2), url="https://github.com/o/r/actions/runs/2")
    assert release.pick_dispatched_run([run], SHA, {1})["url"].endswith("/2")


# ------------------------------------------------------ paginated responses


def test_merge_paginated_flattens_pages():
    pages = [{"check_runs": [{"name": "a"}]}, {"check_runs": [{"name": "b"}]}]
    assert [r["name"] for r in release.merge_paginated(pages, "check_runs")] == ["a", "b"]


def test_merge_paginated_tolerates_an_empty_page():
    assert release.merge_paginated([{}, {"check_runs": None}], "check_runs") == []


def test_merge_paginated_rejects_an_unslurped_object():
    """Without --slurp, gh emits one object per page and this is what arrives.

    Catching it here beats a JSONDecodeError halfway through a release.
    """
    with pytest.raises(release.ReleaseError):
        release.merge_paginated({"check_runs": []}, "check_runs")


# ----------------------------------------------------------- index lookup


def test_missing_project_means_version_is_free():
    # The expected state before a first release: both indexes 404.
    assert not release.index_has_version(None, "0.3.0")


def test_version_present_in_releases_is_burned():
    assert release.index_has_version({"releases": {"0.3.0": []}}, "0.3.0")


def test_yanked_version_still_counts_as_burned():
    """Yank is not delete. The number stays spent and the index refuses it."""
    payload = {"releases": {"0.3.0": [{"yanked": True, "yanked_reason": "under-scrubs"}]}}
    assert release.index_has_version(payload, "0.3.0")


def test_other_versions_do_not_burn_this_one():
    assert not release.index_has_version({"releases": {"0.2.0": [], "0.3.1": []}}, "0.3.0")


def test_unrecognized_payload_fails_closed():
    """A guard against spending a version must not read "I do not understand"
    as "the version is free"."""
    for payload in ({}, {"info": {"version": "0.3.0"}}, {"releases": None}, {"releases": []}):
        with pytest.raises(release.ReleaseError):
            release.index_has_version(payload, "0.3.0")
