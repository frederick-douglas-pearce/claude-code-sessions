"""Tests for the SubstitutionTable (issue #20).

Covers:

  - record() registers an entry, returns the canonical replacement, and
    increments occurrences on repeat calls.
  - Conflicting replacements for the same original raise.
  - Iteration yields entries in insertion order — the order the sidecar
    will emit them (PRD section 10).
  - get/len/total_occurrences read views are accurate.
"""

from __future__ import annotations

import pytest

from ccs_sanitize.subtable import (
    Entry,
    SubstitutionConflictError,
    SubstitutionTable,
)


def test_record_first_call_creates_entry() -> None:
    t = SubstitutionTable()
    returned = t.record("/home/fdpearce", "/home/user", label="paths")
    assert returned == "/home/user"
    assert t.get("/home/fdpearce") == "/home/user"
    assert len(t) == 1


def test_record_idempotent_increments_occurrences() -> None:
    t = SubstitutionTable()
    t.record("/home/fdpearce", "/home/user", label="paths")
    t.record("/home/fdpearce", "/home/user", label="paths")
    t.record("/home/fdpearce", "/home/user", label="paths")
    entries = list(t)
    assert len(entries) == 1
    assert entries[0].occurrences == 3


def test_record_conflict_raises() -> None:
    t = SubstitutionTable()
    t.record("/home/fdpearce", "/home/user", label="paths")
    with pytest.raises(SubstitutionConflictError, match="/home/fdpearce"):
        t.record("/home/fdpearce", "/home/someone-else", label="paths")


def test_record_label_conflict_raises() -> None:
    """Two layers cannot independently claim the same original — the sidecar
    can only attribute an entry to one rule category."""
    t = SubstitutionTable()
    t.record("ambiguous", "REPL", label="paths")
    with pytest.raises(SubstitutionConflictError, match="label conflict"):
        t.record("ambiguous", "REPL", label="identifiers")


def test_record_empty_label_raises() -> None:
    """An unlabeled record would leave the sidecar emitter unable to assign
    a rule category. Rejected up front so the failure surfaces at the
    offending call site, not in the sidecar."""
    t = SubstitutionTable()
    with pytest.raises(ValueError, match="label"):
        t.record("x", "y", label="")


def test_get_returns_none_for_unknown() -> None:
    t = SubstitutionTable()
    assert t.get("nope") is None


def test_iteration_preserves_insertion_order() -> None:
    t = SubstitutionTable()
    t.record("first", "1", label="paths")
    t.record("second", "2", label="paths")
    t.record("third", "3", label="paths")
    t.record("second", "2", label="paths")  # repeat — must not reorder
    originals = [e.original for e in t]
    assert originals == ["first", "second", "third"]


def test_iteration_yields_entry_objects() -> None:
    t = SubstitutionTable()
    t.record("x", "y", label="paths")
    entries = list(t)
    assert entries == [
        Entry(original="x", replacement="y", occurrences=1, label="paths")
    ]


def test_entry_label_is_preserved() -> None:
    """Each rule layer tags entries at record time; the Entry view must
    surface the same label for the sidecar to partition by rule category."""
    t = SubstitutionTable()
    t.record("a", "A", label="paths")
    t.record("b", "B", label="identifiers:gitBranch")
    t.record("c", "C", label="identifiers:uuid")
    t.record("d", "D", label="identifiers")
    labels = [e.label for e in t]
    assert labels == ["paths", "identifiers:gitBranch", "identifiers:uuid", "identifiers"]


def test_total_occurrences_sums_across_entries() -> None:
    t = SubstitutionTable()
    t.record("a", "A", label="paths")
    t.record("a", "A", label="paths")
    t.record("b", "B", label="paths")
    assert t.total_occurrences() == 3
    assert len(t) == 2


def test_entry_is_frozen() -> None:
    """Entry rows are immutable so callers can't mutate the table view."""
    e = Entry(original="x", replacement="y", occurrences=1, label="paths")
    with pytest.raises(AttributeError):
        e.occurrences = 2  # type: ignore[misc]


def test_iteration_snapshot_tolerates_concurrent_record() -> None:
    """A natural consumer pattern is to iterate the table while a transform
    keeps calling ``record`` for new originals (e.g., the sidecar writer
    drives further scrubbing). The iterator must not raise
    ``RuntimeError: dictionary changed size during iteration`` in that case;
    instead it yields a stable snapshot of the entries that existed at
    iteration start."""
    t = SubstitutionTable()
    t.record("first", "1", label="paths")
    t.record("second", "2", label="paths")

    seen: list[str] = []
    for entry in t:
        seen.append(entry.original)
        # Mutate mid-iteration — a new original that the snapshot does
        # NOT need to yield, plus an increment on an existing original.
        if entry.original == "first":
            t.record("third", "3", label="paths")
            t.record("second", "2", label="paths")  # increments the existing row

    assert seen == ["first", "second"]
    # The new third entry is visible in a fresh iteration.
    assert [e.original for e in t] == ["first", "second", "third"]
