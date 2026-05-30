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
    returned = t.record("/home/fdpearce", "/home/user")
    assert returned == "/home/user"
    assert t.get("/home/fdpearce") == "/home/user"
    assert len(t) == 1


def test_record_idempotent_increments_occurrences() -> None:
    t = SubstitutionTable()
    t.record("/home/fdpearce", "/home/user")
    t.record("/home/fdpearce", "/home/user")
    t.record("/home/fdpearce", "/home/user")
    entries = list(t)
    assert len(entries) == 1
    assert entries[0].occurrences == 3


def test_record_conflict_raises() -> None:
    t = SubstitutionTable()
    t.record("/home/fdpearce", "/home/user")
    with pytest.raises(SubstitutionConflictError, match="/home/fdpearce"):
        t.record("/home/fdpearce", "/home/someone-else")


def test_get_returns_none_for_unknown() -> None:
    t = SubstitutionTable()
    assert t.get("nope") is None


def test_iteration_preserves_insertion_order() -> None:
    t = SubstitutionTable()
    t.record("first", "1")
    t.record("second", "2")
    t.record("third", "3")
    t.record("second", "2")  # repeat — must not reorder
    originals = [e.original for e in t]
    assert originals == ["first", "second", "third"]


def test_iteration_yields_entry_objects() -> None:
    t = SubstitutionTable()
    t.record("x", "y")
    entries = list(t)
    assert entries == [Entry(original="x", replacement="y", occurrences=1)]


def test_total_occurrences_sums_across_entries() -> None:
    t = SubstitutionTable()
    t.record("a", "A")
    t.record("a", "A")
    t.record("b", "B")
    assert t.total_occurrences() == 3
    assert len(t) == 2


def test_entry_is_frozen() -> None:
    """Entry rows are immutable so callers can't mutate the table view."""
    e = Entry(original="x", replacement="y", occurrences=1)
    with pytest.raises(AttributeError):
        e.occurrences = 2  # type: ignore[misc]
