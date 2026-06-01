"""Substitution table — consistent within-file replacements.

PRD reference: section 6 (architecture overview), section 7 ("consistency =
determinism is the safety property"). The same real value maps to the same
placeholder everywhere it appears in a file: line 1's ``/home/fdpearce`` and
line 5,000's ``/home/fdpearce`` both become ``/home/user``, so a sanitized
parent session and its subagent traces (sanitized separately per file)
still line up.

This is a deterministic data structure — no randomness, no time-dependent
state. Insertion order is preserved for the sidecar emission contract
(PRD section 10): the ``substitutions:`` list reports entries in the order
they were first encountered.

Conflict semantics: if a rule layer ever calls ``record`` with a different
replacement for an original that's already mapped, that's a programming
error — two scrubs cannot disagree on the same input — so the table raises.
A sanitizer that quietly resolved such a conflict would either lose the
within-file consistency property or silently overwrite a substitution that
something else already depends on. Both break the determinism contract.

Implementation lands with issue #20. The rule layers (#21, #22) and the
sidecar emission (#25) consume this surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


class SubstitutionConflictError(ValueError):
    """Raised when ``record`` is called with a different replacement for an
    original that's already mapped. See module docstring for the rationale."""


@dataclass(frozen=True)
class Entry:
    """One row of the substitution table, as observed by external callers.

    Frozen so callers can't mutate the table's view of an entry — updates
    go through ``SubstitutionTable.record``, which preserves the conflict
    check.

    ``label`` identifies which layer produced the entry (``"paths"``,
    ``"identifiers"``, ``"identifiers:gitBranch"``, ``"identifiers:uuid"``)
    so the sidecar emitter (#25) can partition entries and synthesize
    per-layer placeholder names without re-matching every original against
    every rule. Carrying the label structurally on the entry, rather than
    inferring it from insertion order, means a future layer (e.g. the v1
    jitter pass) that interleaves entries cannot break the sidecar's
    ``rule:`` / ``placeholder:`` columns.
    """

    original: str
    replacement: str
    occurrences: int
    label: str


@dataclass
class _Row:
    """Internal mutable backing row.

    Storing the replacement and counter as a typed dataclass (rather than a
    ``list[object]`` with positional slots) keeps mypy honest, names the
    fields, and means future fields (e.g. first-seen line index) attach
    additively rather than via magic indices.
    """

    replacement: str
    occurrences: int
    label: str


class SubstitutionTable:
    """Records original→replacement pairs and the count of times each pair
    was applied, in insertion order.

    Designed for the rule-layer call pattern: when a rule replaces a value,
    it calls ``record(original, replacement)`` once per occurrence. First
    call registers the entry; subsequent calls with the same args increment
    ``occurrences``; calls with a *different* replacement for the same
    original raise ``SubstitutionConflictError``.
    """

    def __init__(self) -> None:
        # dict preserves insertion order (CPython 3.7+ / PEP 468).
        self._entries: dict[str, _Row] = {}

    def record(self, original: str, replacement: str, *, label: str) -> str:
        """Record one occurrence of ``original → replacement`` and return
        the canonical replacement.

        ``label`` is required and identifies the producing layer. Repeat
        ``record`` calls for the same ``original`` must agree on both
        ``replacement`` AND ``label``; a label conflict means two layers
        independently scrubbed the same value, which the sidecar cannot
        coherently attribute to a single rule category.

        Raises:
            SubstitutionConflictError: ``original`` is already mapped to a
                different ``replacement``, or recorded under a different
                ``label``.
        """
        if not label:
            raise ValueError("SubstitutionTable.record: label must be a non-empty string")
        existing = self._entries.get(original)
        if existing is None:
            self._entries[original] = _Row(
                replacement=replacement, occurrences=1, label=label
            )
            return replacement
        if existing.replacement != replacement:
            raise SubstitutionConflictError(
                f"substitution conflict for {original!r}: "
                f"already mapped to {existing.replacement!r}, refused to remap to {replacement!r}"
            )
        if existing.label != label:
            raise SubstitutionConflictError(
                f"label conflict for {original!r}: "
                f"already recorded under {existing.label!r}, refused to relabel as {label!r}"
            )
        existing.occurrences += 1
        return replacement

    def get(self, original: str) -> str | None:
        """Return the recorded replacement for ``original`` without
        incrementing the occurrence count, or ``None`` if not recorded."""
        existing = self._entries.get(original)
        if existing is None:
            return None
        return existing.replacement

    def __iter__(self) -> Iterator[Entry]:
        """Yield Entry rows in insertion order — the order the sidecar
        emits them.

        Iteration takes a snapshot of the table's current entries via
        ``list(...)`` so that a concurrent ``record`` call (a natural
        pattern when the sidecar emission step also drives rule application)
        does not raise ``RuntimeError`` from "dictionary changed size during
        iteration".
        """
        for original, row in list(self._entries.items()):
            yield Entry(
                original=original,
                replacement=row.replacement,
                occurrences=row.occurrences,
                label=row.label,
            )

    def __len__(self) -> int:
        return len(self._entries)

    def total_occurrences(self) -> int:
        return sum(row.occurrences for row in self._entries.values())


__all__ = [
    "Entry",
    "SubstitutionConflictError",
    "SubstitutionTable",
]
