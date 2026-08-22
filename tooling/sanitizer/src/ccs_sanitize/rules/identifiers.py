"""Layer 2: identifier scrubbing (emails, gitBranch, optional UUID remap).

PRD reference: section 8 (Layer 2: identifiers). UUID remapping is off by
default -- ``uuid``/``parentUuid``/``sessionId``/``agentId`` are
high-entropy random values that leak nothing on their own; remapping
requires preserving graph links.

This module ships ``build_identifier_transform`` -- a factory that returns
a :data:`ccs_sanitize.pipeline.TransformCallback` ready to plug into
``run_pipeline`` after the Layer 1 paths transform.

**Per-leaf decision order.** The transform makes one routing decision per
visited leaf, then returns. Layers within a layer do not compose -- the
field-anchored replacements (gitBranch, UUID remap) are whole-value
substitutions, and running identifier regex rules on top of them would
double-record or produce nonsense (e.g., a UUID-shaped placeholder being
partially re-substituted by an unrelated catch-all regex).

  1. ``gitBranch`` -- when ``scrub_git_branch`` is on AND the rooted path
     is in :data:`GIT_BRANCH_PATHS`, the whole leaf becomes
     ``"feature/example"`` (PRD section 8 example).

     This was a bare-name match at any depth, justified as defensive
     ("a nested ``gitBranch`` would still be a branch name shape").
     Issue #199: it is not defensive, it is destructive. ``tool_use.input``
     is arbitrary tool-defined JSON, so a tool parameter named ``gitBranch``
     was silently overwritten -- and because ``scrub_git_branch`` defaults
     to True, that happened under a DEFAULT config. Anchoring costs nothing:
     ``gitBranch`` occurs at exactly one path in the corpus.

  2. UUID-graph fields -- when ``remap_uuids`` is on AND the rooted path is
     in :data:`UUID_PATHS`, the leaf is remapped via
     SHA-256(``uuid_seed`` + original) → first 16 bytes formatted as a
     UUID. Empty-string UUIDs pass through unchanged so they don't become
     phantom graph nodes; the pipeline skip-predicate already filters out
     ``null``.

     Anchored by path as of #194, for the same reason as (1): a bare
     ``sessionId`` match rewrote a colliding tool parameter into a
     synthesized UUID. Note ``toolUseResult.agentId`` is IN the set -- the
     PRD calls it the parent-side link to a subagent's top-level
     ``agentId``, and the two must remap to the same value for the link to
     survive, so anchoring to the line level alone would have broken the
     graph this layer exists to keep coherent. That link is cross-FILE, which
     is why a shared ``uuid_seed`` matters and why the two do not co-occur
     within one file.

  3. Default -- apply each ``config.identifiers`` rule via ``apply_rule``
     in declaration order. Same first-match-wins semantic the paths layer
     documents.

**Determinism.** Same as Layer 1: no randomness, no time-dependent state.
The UUID remap is a pure function of ``(uuid_seed, original)``; cross-file
consistency falls out of running multiple files with the same
``ConfigOptions.uuid_seed``. The PRD calls out that a *random* seed would
force bundle mode; the fixed seed in ``ConfigOptions`` keeps per-file runs
safe.

**Pipeline coupling.** ``remap_uuids: true`` only takes effect if the
pipeline's skip-predicate was built with ``make_skip_predicate(remap_uuids=True)``
so UUID fields are actually visited. The CLI (#26) is responsible for
constructing the predicate from ``config.options.remap_uuids``; this
module's transform is correct under both predicates and silently no-ops on
UUID fields it never sees.
"""

from __future__ import annotations

import hashlib
import uuid as _uuid
from typing import Sequence

from ..config import Rule
from ..pipeline import JsonPath, TransformCallback
from ..subtable import SubstitutionTable
from ._engine import apply_rule

GIT_BRANCH_PLACEHOLDER = "feature/example"

# Both sets below are keyed on ROOT-ANCHORED paths, matching the pipeline's
# allow-list (#194). They were bare leaf names, and a bare name matches at any
# depth: ``tool_use.input`` is arbitrary tool-defined JSON, so a tool
# parameter that happened to be called ``gitBranch`` or ``sessionId`` was
# silently rewritten. That is CORRUPTION rather than leakage -- the mirror
# image of the skip-side bug, in the other half of the pipeline.

# UUID-graph paths (PRD section 8). Kept identical to the pipeline's
# ``_UUID_PATHS`` intentionally: that set governs visit-or-not under
# ``remap_uuids``; this one governs what the transform remaps *when* it sees
# them. Drift between the two silently breaks the contract in one of two
# directions -- visited but never remapped (a UUID ships unscrubbed), or
# remapped but never visited (the flag is a no-op). The duplication is small,
# and ``test_uuid_transform_positions_match_pipeline_allow_list`` pins the
# equality.
#
# That test replaced ``test_uuid_fields_match_pipeline_skip_list``, which
# asserted equality of the two *name* sets. Once the pipeline moved to paths
# and this stayed on names, that assertion would have kept passing while the
# invariant it guarded was broken -- a green check over a live corruption path
# (``input.sessionId`` under ``remap_uuids: true``). Pinning the paths is what
# makes the guard mean something again.
UUID_PATHS: frozenset[JsonPath] = frozenset({
    ("uuid",),
    ("parentUuid",),
    ("sessionId",),
    ("agentId",),
    # The parent side of a CROSS-FILE link: this names a subagent whose own
    # top-level ``agentId`` is in another file, so the two must remap
    # identically or the graph breaks. Expect zero same-file overlap in the
    # corpus -- that is the shape, not a counterexample. See ``_UUID_PATHS``
    # in pipeline.py for the counts.
    ("toolUseResult", "agentId"),
})

# Issue #199. ``gitBranch`` occurs at exactly one position across the whole
# fixture corpus (line level, 1045 records), so the anchor loses no coverage.
# Unlike the UUID remap this is not gated behind an opt-in flag --
# ``scrub_git_branch`` defaults to True -- so the any-depth version corrupted
# a colliding tool parameter under a DEFAULT config.
GIT_BRANCH_PATHS: frozenset[JsonPath] = frozenset({
    ("gitBranch",),
})


def build_identifier_transform(
    rules: Sequence[Rule],
    table: SubstitutionTable,
    *,
    scrub_git_branch: bool = True,
    remap_uuids: bool = False,
    uuid_seed: str = "ccs-sanitize/v1",
) -> TransformCallback:
    """Build a transform that scrubs identifiers on each visited string leaf.

    Args:
        rules: ordered identifier rules (typically ``Config.identifiers``).
            Typed ``Sequence[Rule]`` to forbid single-pass generators --
            declaration order is part of the first-match-wins semantic and
            the closure must be able to re-iterate.
        table: shared substitution table the transform records into.
            Cross-line consistency falls out of reusing one table across
            every leaf in the pipeline run.
        scrub_git_branch: when True, ``gitBranch`` field values are
            replaced with ``GIT_BRANCH_PLACEHOLDER``. Matches
            ``ConfigOptions.scrub_git_branch`` (default True).
        remap_uuids: when True, UUID-graph fields get deterministically
            remapped. Requires the pipeline to use
            ``make_skip_predicate(remap_uuids=True)``; otherwise the
            fields are never visited and the flag is a no-op (correct but
            silent). Matches ``ConfigOptions.remap_uuids`` (default False).
        uuid_seed: deterministic input to the UUID hash. Same seed across
            files keeps the parent↔subagent graph coherent under per-file
            runs. Defaults match ``ConfigOptions.uuid_seed``.

    Returns:
        A ``TransformCallback`` suitable for ``run_pipeline(transform=...)``.
        The callback closes over a tuple snapshot of ``rules`` (a mutable
        caller container cannot mutate the rule set mid-run) and the
        identifier-specific options.

    Raises:
        ValueError: ``uuid_seed`` is empty. Mirrors the loader's check at
            ``config._build_options`` so a programmatic caller cannot
            bypass the determinism guard the loader enforces.
    """
    if not uuid_seed:
        raise ValueError("uuid_seed must be a non-empty string")
    snapshot: tuple[Rule, ...] = tuple(rules)
    # Pre-encode the seed once; per-leaf encoding is wasted work on the
    # UUID-remap hot path.
    seed_bytes = uuid_seed.encode("utf-8")

    def transform(leaf: str, path: JsonPath) -> str:
        if path:
            # Empty-string passthrough for field-anchored substitutions:
            # gitBranch="" is the not-in-a-git-repo signal; uuid="" is
            # malformed but harmless. Either way, don't fabricate a value
            # and don't record a ('' -> placeholder) row the sidecar
            # cannot interpret.
            if scrub_git_branch and path in GIT_BRANCH_PATHS:
                if not leaf:
                    return leaf
                return table.record(
                    leaf, GIT_BRANCH_PLACEHOLDER, label="identifiers:gitBranch"
                )
            if remap_uuids and path in UUID_PATHS:
                if not leaf:
                    return leaf
                # Skip the SHA-256 if the table already maps this UUID;
                # for a 10k-line file sharing one sessionId that's a 10k×
                # reduction in hash work. record() still increments the
                # occurrence counter for the sidecar.
                cached = table.get(leaf)
                if cached is not None:
                    return table.record(leaf, cached, label="identifiers:uuid")
                return table.record(
                    leaf, _remap_uuid(seed_bytes, leaf), label="identifiers:uuid"
                )
        result = leaf
        for rule in snapshot:
            result = apply_rule(rule, result, table, label="identifiers")
        return result

    return transform


def _remap_uuid(seed_bytes: bytes, original: str) -> str:
    """Deterministically remap a UUID-graph value via SHA-256.

    Produces a 36-char dash-formatted UUID string from the first 16 bytes
    of ``sha256(seed_bytes + b'\\x00' + original_bytes)``. The null-byte
    delimiter makes the function injective over ``(seed, original)`` pairs
    rather than over their concatenation -- without it, ``("ab", "cd")``
    and ``("abc", "d")`` would hash identically.

    Bytes 6 and 8 are NOT masked to RFC 4122 version/variant -- downstream
    consumers parse these fields as opaque strings, and forcing the bits
    would only narrow the output range without buying anything.

    Raises:
        ValueError: ``original`` is empty. The caller already short-
            circuits on empty leaves to avoid creating phantom graph
            nodes; the function-level guard is defense-in-depth so any
            future direct caller (sidecar tooling, refactors) cannot
            silently re-introduce the bug.
    """
    if not original:
        raise ValueError("_remap_uuid: original must be a non-empty string")
    digest = hashlib.sha256(seed_bytes + b"\x00" + original.encode("utf-8")).digest()
    return str(_uuid.UUID(bytes=digest[:16]))


__all__ = [
    "GIT_BRANCH_PLACEHOLDER",
    "GIT_BRANCH_PATHS",
    "UUID_PATHS",
    "build_identifier_transform",
]
