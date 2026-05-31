"""Shared per-rule application logic for the regex/literal rule layers.

Both Layer 1 (paths, #21) and Layer 2 (identifiers, #22) apply
``config.Rule`` records to every visited string leaf with the same
semantics: ``re.sub`` over the leaf, each non-overlapping match recorded
in the shared ``SubstitutionTable``, regex rules expand backrefs via
``Match.expand`` while literal rules use the YAML ``replace:`` verbatim.

Extracting the per-rule call out of ``paths.py`` keeps the subtle zero-
width handling (see ``apply_rule`` below) in one place so the two layers
cannot drift on it -- a difference in zero-width semantics between paths
and identifiers would produce divergent substitution tables for the same
real input, breaking the determinism contract (PRD section 7).
"""

from __future__ import annotations

import re

from ..config import Rule
from ..subtable import SubstitutionTable


def apply_rule(rule: Rule, leaf: str, table: SubstitutionTable) -> str:
    """Apply a single rule across ``leaf``, recording each match.

    Uses ``re.sub`` with a callback so every non-overlapping match in the
    leaf is replaced and recorded. A leaf that mentions the same matched
    substring twice records two occurrences against the same table entry,
    which is what the sidecar's per-mapping occurrence count surfaces
    (PRD section 10).

    Zero-width matches return ``""`` rather than recording an empty
    original. The config loader rejects anchor-only and unbounded-optional
    patterns up front (``_reject_zero_width_pattern`` in ``config.py``);
    this branch is the backstop for input-dependent zero-width matches the
    static check cannot see -- primarily lookaheads (``(?=foo)``) and
    ``\\b``, which match zero width only when the surrounding string
    supplies the context. Recording an empty original would pollute the
    sidecar with a meaningless ('' -> X) entry.
    """
    is_regex = rule.is_regex
    replace_template = rule.replace

    def repl(match: re.Match[str]) -> str:
        original = match.group(0)
        if not original:
            return ""
        replacement = match.expand(replace_template) if is_regex else replace_template
        table.record(original, replacement)
        return replacement

    return rule.compiled.sub(repl, leaf)


__all__ = ["apply_rule"]
