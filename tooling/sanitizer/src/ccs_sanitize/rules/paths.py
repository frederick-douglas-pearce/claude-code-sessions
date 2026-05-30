"""Layer 1: path scrubbing (home directory, project slug, configured paths).

PRD reference: section 7 (Layer 1: paths). Runs first because path
normalization is the broadest structural transform; later layers see
already-normalized text and the residual scan is the backstop for
interaction effects.

This module ships ``build_path_transform`` -- a factory that returns a
:data:`ccs_sanitize.pipeline.TransformCallback` ready to plug into
``run_pipeline``.

**Application strategy.** Rules from ``config.paths`` are applied in declared
order, each via ``re.sub`` over the leaf. The PRD specifies "first match
wins"; sequential application is declaration-order, which equals the
position-by-position interpretation for the patterns paths.py rules
realistically use (prefixes, suffixes, full-leaf shapes -- nothing where two
rules' match *ranges* partially overlap in the same string). For overlapping
*patterns* with prefix/subset relationships (rule 1 =
``/home/fdpearce/secret``, rule 2 = ``/home/fdpearce``), the earlier rule's
``re.sub`` consumes the match first, leaving nothing for the later rule --
declaration-order wins, matching the PRD intent.

**Two known limitations of sequential application:**

1. *Leftmost-position divergence.* If rule 1's match starts to the *right*
   of rule 2's match in the same leaf, sequential application still fires
   rule 1 first (declaration order beats position order). A position-order
   scanner would pick rule 2. Path configs in the wild don't hit this --
   ``cwd`` and project-slug rules are prefix-bound -- so the simpler
   implementation is acceptable for v0.
2. *Backref cascades the I-3 guard cannot see.* The config loader's I-3
   replacement-leak guard (``_check_replacement_leak`` in ``config.py``)
   refuses any config where the *literal* ``replace`` template matches
   another rule's pattern. For regex rules with backrefs, the runtime-
   expanded replacement can be a substring the template was not -- so a
   config like rule 1 = ``re:foo-(.+)`` → ``bar-\\1``, rule 2 = literal
   ``bar-x`` → ``Z`` passes I-3 (the literal ``bar-\\1`` template doesn't
   contain ``bar-x``) but cascades at runtime: rule 1 turns ``foo-x`` into
   ``bar-x``, then rule 2 turns ``bar-x`` into ``Z``. The output is still
   scrubbed and deterministic; the sidecar honestly reports both hops. But
   the result is harder to read than a single-mapping audit trail.

Either limitation can be fixed later by swapping the per-rule loop for a
single alternation regex with named groups (each position decided once),
without changing the public ``build_path_transform`` signature.

**Determinism.** PRD section 7 names consistency as the safety property:
sanitizing a parent session and a subagent trace in two separate runs must
yield coherent output (the same ``/home/fdpearce`` maps to ``/home/user``
in both). Each substring match is recorded in the supplied
``SubstitutionTable``; cross-file consistency falls out of the rules being
declared in one shared config plus the table's append-only semantics within
a file.

**Backreferences.** For regex rules (``re:`` prefix), the matched substring's
capture groups expand into the replacement via ``Match.expand``. For literal
rules, the YAML ``replace:`` value is used verbatim -- ``re.escape`` of a
literal pattern produces no groups, and a ``\\1`` inside a literal
replacement string is almost certainly a config mistake rather than a
backref intent. An invalid backref (``\\3`` against a 2-group pattern) raises
``re.error`` from inside ``re.sub`` on the first match; v0 surfaces that at
runtime rather than at transform-build time.
"""

from __future__ import annotations

import re
from typing import Sequence

from ..config import Rule
from ..pipeline import JsonPath, TransformCallback
from ..subtable import SubstitutionTable


def build_path_transform(
    rules: Sequence[Rule],
    table: SubstitutionTable,
) -> TransformCallback:
    """Build a transform that applies path rules to each visited string leaf.

    Args:
        rules: ordered path rules (typically ``Config.paths``). The
            parameter is typed ``Sequence[Rule]`` -- not ``Iterable`` --
            because declaration order is part of the semantic (first-match-
            wins; see module docstring), and ``Iterable`` would accept
            single-pass generators that the closure cannot re-iterate.
        table: shared substitution table the transform records into. Cross-
            line consistency comes from this table being reused across every
            leaf in the pipeline run; the pipeline driver is responsible for
            constructing one table per file.

    Returns:
        A ``TransformCallback`` suitable for ``run_pipeline(transform=...)``.
        The callback is a closure over a tuple snapshot of ``rules`` (so a
        mutable caller container cannot mutate the rule set mid-run) and
        ``table``. The JSON-path argument is unused: path rules apply
        uniformly to every string leaf the skip-list lets through.
    """
    snapshot: tuple[Rule, ...] = tuple(rules)

    def transform(leaf: str, path: JsonPath) -> str:
        result = leaf
        for rule in snapshot:
            result = _apply_rule(rule, result, table)
        return result

    return transform


def _apply_rule(rule: Rule, leaf: str, table: SubstitutionTable) -> str:
    """Apply a single rule across ``leaf``, recording each match.

    Uses ``re.sub`` with a callback so every non-overlapping match in the
    leaf is replaced and recorded. A Bash command that mentions
    ``/home/fdpearce`` twice records two occurrences against the same table
    entry, which is what the sidecar's per-mapping occurrence count surfaces
    (PRD section 10).
    """
    is_regex = rule.is_regex
    replace_template = rule.replace

    def repl(match: re.Match[str]) -> str:
        original = match.group(0)
        if not original:
            # Zero-width match (lookahead-only pattern, ``\b``, ``^``, ...).
            # Recording an empty original would pollute the sidecar with a
            # meaningless ('' -> X) entry the audit log can't interpret.
            # Return the empty string so ``re.sub`` inserts nothing at the
            # zero-width position (effective no-op for this match).
            return ""
        replacement = match.expand(replace_template) if is_regex else replace_template
        table.record(original, replacement)
        return replacement

    return rule.compiled.sub(repl, leaf)


__all__ = ["build_path_transform"]
