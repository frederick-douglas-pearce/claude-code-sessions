"""Session-level orchestration: wire all transform layers + the residual gate.

PRD reference:

  - section 5 -- the residual scan is the single most important safety
    mechanism; it must run after every successful pipeline pass.
  - section 6 -- architecture overview shows the three-layer ordering
    (paths -> identifiers -> secrets) feeding into the residual scan.
  - section 11 -- fail-closed posture: any failure (pipeline parse error,
    rule error, residual match) aborts the run and writes nothing. The
    CLI (#26) maps exceptions to exit codes; this module just raises
    them so the call site has a single chokepoint to catch.

This module sits one level above ``pipeline.py``. ``pipeline.py``'s
docstring deliberately carves out orchestration so the line loop has a
single narrow role; ``orchestrator.py`` is where the three rule layers
get composed into one transform, plugged into ``run_pipeline``, and
followed by the residual scan.

The four-tuple return (``serialized_lines``, ``PipelineCounts``,
``SubstitutionTable``, ``SecretCounts``) carries everything the sidecar
emission (#25) and CLI (#26) need without re-running the pipeline.

**Layer ordering rationale (PRD section 6).** Paths run first because path
normalization is the broadest structural transform; identifiers second
because they consume already-normalized paths (an email in a tool-output
quoted path is unaffected by path scrub, but if it ever were, paths
having run first means identifier rules see a stable canonical form);
secrets last because secret redaction produces ``<REDACTED:kind>``
placeholders that must not be re-scrubbed by anything downstream.

**Forward compatibility for the v1 jitter layer (PRD section 9b).** The
composed transform chains layers in order; adding jitter is a one-line
insertion before the secret layer (jitter operates on user-content text,
not on secret placeholders).
"""

from __future__ import annotations

from typing import Iterable

from .config import Config
from .pipeline import (
    DEFAULT_STRIP_TYPES,
    JsonPath,
    PipelineCounts,
    make_skip_predicate,
    run_pipeline,
)
from .residual import scan_residual
from .rules.identifiers import build_identifier_transform
from .rules.paths import build_path_transform
from .rules.secrets import SecretCounts, build_secret_transform
from .subtable import SubstitutionTable


def sanitize_session(
    lines: Iterable[str],
    config: Config,
    *,
    strip_types: frozenset[str] = DEFAULT_STRIP_TYPES,
) -> tuple[list[str], PipelineCounts, SubstitutionTable, SecretCounts]:
    """Run the full sanitizer pipeline + residual gate on ``lines``.

    Builds the three transform layers from ``config``, composes them in the
    PRD-mandated order (paths -> identifiers -> secrets), feeds them through
    ``run_pipeline``, and runs the residual secret scan over the joined
    output. If this function returns, the residual scan passed -- the
    sidecar (#25) can unconditionally record ``residual_scan: clean`` on
    every result it consumes from here.

    Args:
        lines: input JSONL records. Iterated exactly once.
        config: validated config tree from ``load_config``. The skip
            predicate is built with ``remap_uuids=config.options.remap_uuids``
            so identifier-layer UUID remapping sees the fields it needs.
        strip_types: line ``type`` values to drop wholesale (PRD section 6b A).
            Defaults to ``DEFAULT_STRIP_TYPES``. The CLI (#26) will accept
            ``--strip-types`` and pass through here.

    Returns:
        ``(serialized_lines, pipeline_counts, subtable, secret_counts)``.
        Callers should treat the four objects as a single atomic result --
        partial assembly is impossible because ``run_pipeline`` accumulates
        eagerly and ``scan_residual`` runs after the full list exists; any
        failure raises before this tuple is constructed.

    Raises:
        PipelineError: malformed JSONL, non-object record, missing/non-string
            ``type``, or a non-finite number in the parsed tree. Maps to
            CLI exit 2 (PRD section 11).
        ResidualSecretError: a secret pattern matched the serialized output.
            Maps to CLI exit 2. The exception's ``kind`` field names the
            matching pattern label; the matched bytes are never recorded
            (D-2 invariant).
    """
    subtable = SubstitutionTable()
    secret_counts = SecretCounts()
    skip_predicate = make_skip_predicate(remap_uuids=config.options.remap_uuids)

    path_transform = build_path_transform(config.paths, subtable)
    # ``ConfigOptions`` is destructured at the call site so ``identifiers.py``
    # stays decoupled from ``config.py``'s types -- the rule layer never
    # imports ``ConfigOptions`` and depends only on the three scalar options
    # it actually consumes. Coupling those would invert the current clean
    # dependency direction (config depends on rules, not vice versa).
    identifier_transform = build_identifier_transform(
        config.identifiers,
        subtable,
        scrub_git_branch=config.options.scrub_git_branch,
        remap_uuids=config.options.remap_uuids,
        uuid_seed=config.options.uuid_seed,
    )
    secret_transform = build_secret_transform(
        config.extra_secret_patterns, secret_counts
    )

    def composed(leaf: str, path: JsonPath) -> str:
        return secret_transform(
            identifier_transform(path_transform(leaf, path), path),
            path,
        )

    out, counts = run_pipeline(
        lines,
        strip_types=strip_types,
        transform=composed,
        skip_predicate=skip_predicate,
    )
    # PRD section 5: re-run the secret-pattern detector over the output.
    # scan_residual takes the line list directly -- per-line scanning keeps
    # the same semantics ``build_secret_transform`` applies per leaf and
    # avoids any cross-line spillover from join-separator interaction with
    # patterns that match across whitespace.
    scan_residual(out, config.extra_secret_patterns)
    return out, counts, subtable, secret_counts


__all__ = ["sanitize_session"]
