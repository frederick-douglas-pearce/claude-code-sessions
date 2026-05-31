"""Shared test helpers for the sanitizer test suite.

Test files import these via ``from ._helpers import ...`` to avoid
duplicating tiny but contract-bearing utilities across files. The
helpers exercise the same load path the CLI will use (``load_config``)
so a test config that violates the I-3 replacement-leak guard fails to
load -- which is the right signal.
"""

from __future__ import annotations

from pathlib import Path

from ccs_sanitize.config import Config, load_config
from ccs_sanitize.subtable import SubstitutionTable


def write_config(tmp_path: Path, body: str) -> Config:
    """Write ``body`` to ``tmp_path/config.yaml`` and load it."""
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return load_config(p)


def table_snapshot(table: SubstitutionTable) -> list[tuple[str, str, int]]:
    """Flatten a ``SubstitutionTable`` into a comparable list of tuples.

    Used by determinism tests: equal snapshots imply equal table contents
    AND equal insertion order, both of which the sidecar contract
    (PRD section 10) depends on.
    """
    return [(e.original, e.replacement, e.occurrences) for e in table]


__all__ = ["write_config", "table_snapshot"]
