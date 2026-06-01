"""`.scrubbed` sidecar emission.

PRD reference: section 10 (the `.scrubbed` sidecar -- redacted-by-design
format, D-2). The sidecar is the auditable record of what changed in a
sanitizer run; it must surface category-level detail without itself
echoing any original sensitive token.

This module is **pure data assembly**: ``build_sidecar`` consumes the
4-tuple from ``sanitize_session`` plus a small ``SidecarMetadata`` record
and returns a YAML string. It performs no file I/O. The CLI (#26) is
responsible for reading the raw input (to compute the SHA-256), choosing
the output path, writing the temp file, and performing the atomic rename
ordering documented in PRD section 11 (sidecar-first-then-output) -- all
of which would force a refactor here if this module also did I/O.

**I-3 emit-time leak guard.** The config loader's ``_check_replacement_leak``
already guarantees that no user ``replace`` value matches any other rule
or any built-in / extra secret pattern (PRD section 10, I-3). The sidecar
re-runs that check at emit time against the *rendered YAML string* as
defense-in-depth: a configured original token should never appear in the
output, and no built-in or extra secret pattern should match. If either
condition fires, ``SidecarLeakError`` is raised and the CLI declines to
write the sidecar (mapping to exit 2). The two checks together pin the
PRD section 14 "sidecar-never-leaks" test (I-3) structurally rather than
disciplinarily.

**Placeholder synthesis (Option A per architect review on #25).** The
PRD section 10 example uses human-friendly placeholders like
``<home-dir>`` and ``<email>``. The YAML rule schema carries no category
field, so we synthesize placeholders from each entry's ``label``:

  - ``"identifiers:gitBranch"`` -> ``"<git-branch>"``
  - ``"identifiers:uuid"``      -> ``"<uuid>"``
  - ``"paths"``                 -> ``"<path-N>"``       (1-based)
  - ``"identifiers"``           -> ``"<identifier-N>"`` (1-based)

Numbering restarts per layer and follows insertion order, so a config
diff that adds a single new rule produces a one-line sidecar diff -- the
existing entries keep their indices.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import yaml

from . import __version__
from .config import Config
from .pipeline import PipelineCounts
from .rules.secrets import SecretCounts, iter_all_secret_patterns
from .subtable import SubstitutionTable

_FIXED_PLACEHOLDERS: dict[str, str] = {
    "identifiers:gitBranch": "<git-branch>",
    "identifiers:uuid": "<uuid>",
}
_INDEXED_PLACEHOLDER_PREFIXES: dict[str, str] = {
    "paths": "<path-",
    "identifiers": "<identifier-",
}
_RULE_LAYER_OF_LABEL: dict[str, str] = {
    "paths": "paths",
    "identifiers": "identifiers",
    "identifiers:gitBranch": "identifiers",
    "identifiers:uuid": "identifiers",
}


class SidecarLeakError(Exception):
    """Raised when the I-3 emit-time guard finds a sensitive token in the
    rendered sidecar.

    Carries the offending category (``"original"`` or a secret pattern
    ``kind`` label) so the CLI (#26) can map to exit 2 with a tailored
    diagnostic. The matched bytes are not stored on the exception (D-2
    invariant): the sidecar leak guard exists *because* originals must
    never propagate; surfacing the matched bytes in the exception would
    defeat its own purpose.
    """

    def __init__(self, category: str) -> None:
        super().__init__(
            f"sidecar emit-time leak guard fired (category={category!r}); "
            f"sidecar was not produced"
        )
        self.category = category


@dataclass(frozen=True)
class SidecarMetadata:
    """Per-run context the sidecar embeds that does not come from the
    pipeline result.

    The CLI assembles this from its arguments and the raw input file (read
    once for the SHA-256). Keeping the metadata as a typed record rather
    than loose kwargs makes the contract explicit: the sidecar emitter
    does not know the input path, only its basename; does not read the
    file, only its hash; and does not invent the timestamp, so a test can
    pin a known value for byte-stability assertions.

    Field constraints:

      - ``input_filename``: basename only (PRD section 10 -- "never the
        full path"). The CLI must apply ``Path(input).name`` before
        constructing this record.
      - ``input_sha256``: lowercase hex SHA-256 of the raw input bytes.
      - ``config_source``: basename only, for the same reason.
      - ``scrubbed_at``: ISO 8601 UTC ending in ``Z``, e.g.
        ``"2026-05-31T18:30:00Z"``. The CLI typically computes this via
        ``utc_now_iso8601()`` immediately before calling ``build_sidecar``.
    """

    input_filename: str
    input_sha256: str
    config_source: str
    scrubbed_at: str


def utc_now_iso8601() -> str:
    """Return the current UTC time as an ISO 8601 string ending in ``Z``.

    Helper for the CLI; not used by ``build_sidecar`` (which takes the
    timestamp as a parameter so tests can pin it).
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data: bytes) -> str:
    """Compute lowercase hex SHA-256 of ``data``.

    Helper for the CLI to fill ``SidecarMetadata.input_sha256``. The
    sanitizer reads the raw input bytes once for this hash; the hash
    itself is a one-way digest, safe to embed in the sidecar (PRD
    section 10).
    """
    return hashlib.sha256(data).hexdigest()


def build_sidecar(
    *,
    metadata: SidecarMetadata,
    config: Config,
    serialized_lines: Sequence[str],
    counts: PipelineCounts,
    subtable: SubstitutionTable,
    secret_counts: SecretCounts,
) -> str:
    """Build the `.scrubbed` sidecar YAML string for a successful run.

    Callers MUST only invoke this after ``sanitize_session`` returns --
    if that function returns, the residual scan passed and the sidecar
    can unconditionally record ``residual_scan: clean`` (PRD section 10).
    A failed run produces no sidecar.

    Args:
        metadata: per-run context (filename, hash, config source,
            timestamp). The CLI assembles this.
        config: the loaded config -- ``config.version`` becomes
            ``config_version``, and ``config.extra_secret_patterns`` is
            scanned by the I-3 emit-time leak guard.
        serialized_lines: post-scrub output lines, used only to compute
            ``lines_processed = len(out) + sum(stripped)``.
        counts: ``PipelineCounts`` from ``run_pipeline``.
        subtable: the substitution table populated by paths/identifiers.
        secret_counts: ``SecretCounts`` populated by the secrets layer.

    Returns:
        A YAML document as a string, ready to be written to
        ``<output>.scrubbed`` by the CLI.

    Raises:
        SidecarLeakError: the rendered YAML contains a configured
            original token or matches a built-in/extra secret pattern
            (I-3). The exception's ``category`` field names what fired;
            the matched bytes are intentionally not stored.
    """
    paths_subs, paths_distinct = _rule_layer_totals(subtable, "paths")
    identifiers_subs, identifiers_distinct = _identifiers_totals(subtable)

    stripped_lines: dict[str, int] = {
        kind: count for kind, count in counts.stripped_lines.items()
    }
    lines_processed = len(serialized_lines) + sum(stripped_lines.values())

    substitutions = _build_substitutions(subtable)

    # Ordered dict so the rendered YAML matches PRD section 10's field order
    # one-for-one. ``sort_keys=False`` in ``yaml.safe_dump`` preserves it.
    payload: dict[str, Any] = {
        "sanitizer_version": __version__,
        "scrubbed_at": metadata.scrubbed_at,
        "input_filename": metadata.input_filename,
        "input_sha256": metadata.input_sha256,
        "config_version": config.version,
        "config_source": metadata.config_source,
        "lines_processed": lines_processed,
        "stripped_lines": stripped_lines,
        "rules_applied": {
            "paths": {"substitutions": paths_subs, "distinct": paths_distinct},
            "identifiers": {
                "substitutions": identifiers_subs,
                "distinct": identifiers_distinct,
            },
            "secrets": {"matches": secret_counts.total()},
            "jitter": "disabled",
        },
        "substitutions": substitutions,
        "residual_scan": "clean",
    }

    rendered = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    _check_emit_time_leak(rendered, subtable, config)
    return rendered


def _build_substitutions(subtable: SubstitutionTable) -> list[dict[str, Any]]:
    """Emit one row per subtable entry, in insertion order, with the
    synthesized ``rule`` and ``placeholder`` columns the sidecar contract
    requires (PRD section 10).

    Per-layer indices restart at 1 for ``paths`` and for the catch-all
    ``identifiers`` label so the placeholder strings are stable across runs
    over the same input: ``<path-1>`` is always the first paths entry
    inserted, regardless of how many identifier rules ran first.
    """
    paths_index = 0
    identifiers_index = 0
    out: list[dict[str, Any]] = []
    for entry in subtable:
        label = entry.label
        rule_layer = _RULE_LAYER_OF_LABEL.get(label, label)
        if label in _FIXED_PLACEHOLDERS:
            placeholder = _FIXED_PLACEHOLDERS[label]
        elif label == "paths":
            paths_index += 1
            placeholder = f"{_INDEXED_PLACEHOLDER_PREFIXES[label]}{paths_index}>"
        elif label == "identifiers":
            identifiers_index += 1
            placeholder = (
                f"{_INDEXED_PLACEHOLDER_PREFIXES[label]}{identifiers_index}>"
            )
        else:
            # Unknown label: emit a generic placeholder rather than leaking
            # the label itself, and tag the rule column with the raw label
            # so a reviewer can locate the producing layer. A future layer
            # that forgets to register here surfaces as a literal
            # ``<unknown-N>`` in the sidecar rather than crashing the run
            # (preserves the determinism contract under refactor).
            placeholder = f"<unknown-{len(out) + 1}>"
        out.append(
            {
                "rule": rule_layer,
                "placeholder": placeholder,
                "replacement": entry.replacement,
                "occurrences": entry.occurrences,
            }
        )
    return out


def _rule_layer_totals(
    subtable: SubstitutionTable, label: str
) -> tuple[int, int]:
    """Return ``(total_occurrences, distinct_entries)`` for a single label."""
    distinct = 0
    total = 0
    for entry in subtable:
        if entry.label == label:
            distinct += 1
            total += entry.occurrences
    return total, distinct


def _identifiers_totals(subtable: SubstitutionTable) -> tuple[int, int]:
    """Sum across all ``identifiers`` label variants (the catch-all rule
    layer plus the field-anchored ``gitBranch`` and ``uuid`` transforms).

    PRD section 10's ``rules_applied.identifiers`` reports the identifiers
    *layer* as a whole, not each sub-transform separately; per-entry
    differentiation lives in the ``substitutions`` list's placeholder
    column.
    """
    distinct = 0
    total = 0
    for entry in subtable:
        if _RULE_LAYER_OF_LABEL.get(entry.label) == "identifiers":
            distinct += 1
            total += entry.occurrences
    return total, distinct


def _check_emit_time_leak(
    rendered: str, subtable: SubstitutionTable, config: Config
) -> None:
    """I-3 defense-in-depth at sidecar emit time.

    The config loader (``_check_replacement_leak``) already rejects
    configurations where a replacement matches another rule or any
    secret pattern, so in normal operation neither check below should
    fire. We re-run them over the rendered YAML to pin the invariant
    structurally: a future change that puts an original into the sidecar
    by mistake (e.g., a refactor of ``_build_substitutions`` that
    accidentally emits ``entry.original``) raises here rather than
    landing as a quietly broken sidecar.
    """
    for entry in subtable:
        if entry.original and entry.original in rendered:
            raise SidecarLeakError("original")
    for pattern, kind in iter_all_secret_patterns(config.extra_secret_patterns):
        if pattern.search(rendered):
            raise SidecarLeakError(kind)


__all__ = [
    "SidecarLeakError",
    "SidecarMetadata",
    "build_sidecar",
    "sha256_hex",
    "utc_now_iso8601",
]
