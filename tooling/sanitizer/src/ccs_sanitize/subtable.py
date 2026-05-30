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
    """One row of the substitution table.

    Frozen so callers can't mutate the table's view of an entry — updates
    go through ``SubstitutionTable.record``, which preserves the conflict
    check.
    """

    original: str
    replacement: str
    occurrences: int


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
        self._entries: dict[str, list[object]] = {}

    def record(self, original: str, replacement: str) -> str:
        """Record one occurrence of ``original → replacement`` and return
        the canonical replacement.

        Raises:
            SubstitutionConflictError: ``original`` is already mapped to a
                different ``replacement``.
        """
        existing = self._entries.get(original)
        if existing is None:
            self._entries[original] = [replacement, 1]
            return replacement
        canonical, count = existing
        if canonical != replacement:
            raise SubstitutionConflictError(
                f"substitution conflict for {original!r}: "
                f"already mapped to {canonical!r}, refused to remap to {replacement!r}"
            )
        existing[1] = count + 1
        return replacement  # type: ignore[return-value]

    def get(self, original: str) -> str | None:
        """Return the recorded replacement for ``original`` without
        incrementing the occurrence count, or ``None`` if not recorded."""
        existing = self._entries.get(original)
        if existing is None:
            return None
        return existing[0]  # type: ignore[return-value]

    def __iter__(self) -> Iterator[Entry]:
        """Yield Entry rows in insertion order — the order the sidecar
        emits them."""
        for original, (replacement, occurrences) in self._entries.items():
            yield Entry(
                original=original,
                replacement=replacement,  # type: ignore[arg-type]
                occurrences=occurrences,  # type: ignore[arg-type]
            )

    def __len__(self) -> int:
        return len(self._entries)

    def total_occurrences(self) -> int:
        return sum(count for _, count in self._entries.values())  # type: ignore[misc]


__all__ = [
    "Entry",
    "SubstitutionConflictError",
    "SubstitutionTable",
]
