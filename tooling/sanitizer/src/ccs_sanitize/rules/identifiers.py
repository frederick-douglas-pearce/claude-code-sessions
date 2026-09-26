"""Layer 2: identifier scrubbing (emails, gitBranch, optional UUID remap).

PRD reference: section 8 (Layer 2: identifiers). UUID remapping is off by
default -- ``uuid``/``parentUuid``/``sessionId``/``agentId`` and
``toolUseResult.agentId`` (see :data:`UUID_PATHS`) are high-entropy random
values that leak nothing on their own; remapping requires preserving graph
links.

**This set is not a claim of graph completeness, and must not be read as one.**
It enumerates the positions the two sides agree to remap. The corpus carries at
least two further UUID-graph edges that are on NEITHER side --
``sourceToolAssistantUUID`` and ``leafUuid``, both top-level, both resolving to
record ``uuid`` values -- so under ``remap_uuids: true`` they ship verbatim
while their referents are remapped, leaving references that no longer resolve.
That is a real defect, it predates the path-anchoring work, and it affects only
the opt-in remap mode (``remap_uuids`` defaults to False), which is why it is
not fixed here. It is tracked in #202, which also carries the reason the fix
belongs in THIS set alone: both fields are already visited in both modes, so
adding them here changes nothing under the default config, whereas adding them
to ``pipeline._UUID_PATHS`` too would make them skipped by default and widen
the exempt surface. Nothing here should be read as asserting that every graph
edge remaps.

This module ships ``build_identifier_transform`` -- a factory that returns
a :data:`ccs_sanitize.pipeline.TransformCallback` ready to plug into
``run_pipeline`` after the Layer 1 paths transform.

**Per-leaf decision order.** The transform makes one routing decision per
visited leaf, then returns. Layers within a layer do not compose -- the
field-anchored replacements (gitBranch, UUID remap) are whole-value
substitutions, and running identifier regex rules on top of them would
double-record or produce nonsense (e.g., a UUID-shaped placeholder being
partially re-substituted by an unrelated catch-all regex).

  1. Branch names -- when ``scrub_git_branch`` is on AND the rooted path
     is in :data:`GIT_BRANCH_PATHS`, the whole leaf becomes
     ``"feature/example"`` (PRD section 8 example). Two positions: the
     line-level ``gitBranch``, and ``branch`` under
     ``serverClassifierContext.context.git_state`` (#251). A leaf already
     holding the placeholder is returned untouched, so a second pass records
     no substitution.

     This was a bare-name match at any depth, justified as defensive
     ("a nested ``gitBranch`` would still be a branch name shape").
     Issue #199: it is not defensive, it is destructive. ``tool_use.input``
     is arbitrary tool-defined JSON, so a tool parameter named ``gitBranch``
     was silently overwritten -- and because ``scrub_git_branch`` defaults
     to True, that happened under a DEFAULT config. Anchoring costs nothing:
     ``gitBranch`` occurs at exactly one path in the corpus. The #251
     positions were added as rooted paths for the same reason, more
     urgently -- ``branch`` is a likelier tool parameter than ``gitBranch``
     ever was.

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
    # identically or the graph breaks. The authority is the format contract
    # (reference/data-dictionary.md + subagent-traces.md), not the corpus,
    # whose only cross-file match is the synthetic fixture pair this repo
    # authored. Expect zero same-file overlap -- that is the shape, not a
    # counterexample. See ``_UUID_PATHS`` in pipeline.py.
    ("toolUseResult", "agentId"),
})

# Issue #199. ``gitBranch`` occurs at exactly one position across the whole
# fixture corpus (line level, 1045 records), so the anchor loses no coverage.
# Unlike the UUID remap this is not gated behind an opt-in flag --
# ``scrub_git_branch`` defaults to True -- so the any-depth version corrupted
# a colliding tool parameter under a DEFAULT config.
#
# Issue #251. The branch name also rides a SECOND structure the camelCase
# anchor never reached: ``serverClassifierContext.context.git_state``, whose
# leaf is spelled ``branch``. The pre-#199 any-depth rule missed it too, for
# the same reason -- it matched the NAME ``gitBranch``, and this key is not
# called that. So the leak predates #199 rather than being caused by it.
#
# It shipped in 0.3.0 and was found because the paths rule, which is
# value-based, rewrote the SIBLING leaves ``git_state.root`` and
# ``git_state.cwd`` while the branch survived beside them -- with the sidecar
# reporting ``residual_scan: clean``. That combination is the whole severity:
# a user is told the file is safe.
#
# ``default_branch`` is NOT anchored, and the first draft of this fix had it
# wrong. The argument for covering it was "a branch name by its key name, same
# placeholder, costs nothing". It costs something, and the cost is an ABORT.
#
# ``SubstitutionTable.record`` keys on the ORIGINAL value and raises when a
# second call supplies a different replacement for it. Anchoring
# ``default_branch`` makes the built-in claim the trunk name -- ``main`` or
# ``master`` -- in the table on every session that has one. Any configured rule
# whose match resolves to that same string anywhere else in the file then
# raises ``SubstitutionConflictError`` and the run exits with nothing written.
#
# That failure already exists for a session sitting ON its trunk, where
# ``gitBranch`` itself is ``main``. Anchoring ``default_branch`` widens it from
# that minority to nearly every session, because ``default_branch`` is ``main``
# whatever branch the work is on. Trading a real abort for coverage of a leaf
# that was null in all four records it has ever been seen at is the wrong way
# round.
#
# Unanchored does not mean unscrubbed: the leaf falls through to the configured
# ``identifiers`` rules like any other value, which is the correct treatment
# for a position whose value shape has never been observed. #267 adds the
# nested-key scan that would settle the shape; anchoring can be revisited then,
# and would need an answer to the conflict class first.
#
# Listed as EXACT ROOTED PATHS, never as a subtree or a bare name, for #199's
# reason: a tool parameter called ``branch`` is common, and corrupting one
# under a default config is the failure that anchoring exists to prevent.
#
# NOT covered here, deliberately. The first two are UNOBSERVED rather than
# judged harmless: both were null in all four records, so anything said about
# their value shape would be invention. #267 adds the nested-key scan that
# would settle them over the corpus instead of over four records.
#
# * The whole ``git_state.visibility`` object. Observed as
#   ``{"origin": null, "push_remote": "origin", "remotes": [],
#   "visibility_cache": []}``, so three of its four leaves are unobserved:
#   ``origin``, ``remotes`` and ``visibility_cache``. ``origin`` is the one
#   worth naming, because an earlier draft of this comment called it "a remote
#   URL" on zero non-null observations -- the parent key is ``visibility`` and
#   the other sibling is a remote NAME, so a public/private classification of
#   that remote reads at least as well. Covering any of the three means
#   choosing a placeholder for a shape nobody here has seen populated, which is
#   the #257 mistake.
# * ``git_state.status.porcelain``. ``git status --porcelain`` emits
#   repo-RELATIVE paths and the paths rule matches configured ABSOLUTE roots,
#   so the paths rule does NOT reach it. If it is ever populated, directory and
#   file names ship verbatim under ``residual_scan: clean`` -- #251's shape at
#   a different key.
#
# The third is not unobserved. It is populated and it already leaks:
#
# * The branch name in FREE TEXT. Claude Code injects a ``gitStatus`` block
#   into the first user message, where ``Current branch: <name>`` is prose, not
#   a leaf at a path. ``fixtures/sanitized/sanitizer-development.jsonl``
#   publishes one that way, under a clean sidecar, today. No field anchor can
#   reach it by construction; closing it needs a value-based rule seeded from
#   the anchored leaves, which is a different design and a separate change.
GIT_BRANCH_PATHS: frozenset[JsonPath] = frozenset({
    ("gitBranch",),
    ("serverClassifierContext", "context", "git_state", "branch"),
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
        scrub_git_branch: when True, every leaf at a path in
            :data:`GIT_BRANCH_PATHS` is replaced with
            ``GIT_BRANCH_PLACEHOLDER``. That is the line-level ``gitBranch``
            field and ``serverClassifierContext.context.git_state.branch``
            (#251), not ``gitBranch`` alone. Matches
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
                # Already-scrubbed passthrough. Without it a second pass over
                # clean output records ``feature/example -> feature/example``,
                # so the re-scrub's sidecar claims substitutions on input that
                # needed none -- at exactly the positions a re-scrub is run to
                # prove clean. The bytes were always stable; the sidecar was
                # not. PRD section 14 and the planned fixture-validator, which
                # re-derives rather than trusting the field, both read it.
                if leaf == GIT_BRANCH_PLACEHOLDER:
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
