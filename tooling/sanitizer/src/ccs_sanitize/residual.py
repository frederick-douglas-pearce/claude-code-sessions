"""Post-scrub residual secret scan -- the sanitizer's last safety gate.

PRD reference: section 5 (the residual-scan philosophy) and section 11
(fail-closed posture / exit codes). The same ``COMPILED_SECRET_PATTERNS``
that ``rules/secrets.py`` uses to *redact during scrub* is re-applied here
to *verify* the serialized output. A match at this stage means a secret
survived redaction -- a sanitizer bug, a secret split across a transform
boundary, or a planted-in-a-skip-listed-field shape -- and the only safe
response is to refuse to write the output file at all.

The PRD calls out the conceptual split (section 5):

  1. **Detection during scrub** (expected): patterns match in the *input*
     and are redacted-and-counted into the sidecar.
  2. **Residual verification after scrub** (must be clean): the *same*
     patterns run over the *output*; a match is a failure condition.

This module owns step 2. It deliberately re-imports ``COMPILED_SECRET_PATTERNS``
rather than accepting a pattern list from the caller: the D-1 floor (built-in
patterns cannot be weakened from config, PRD section 12) is then structural,
not disciplinary -- there is no API to pass a pruned subset of built-ins.

D-2 invariant ("secrets are redacted, never stored", PRD section 10) extends
to ``ResidualSecretError``: only the matched pattern's ``kind`` label survives
in the error -- never the matched bytes -- so the invariant holds even in
exception messages, tracebacks, and any log output that captures them.

Exit-code mapping (CLI exit 2, PRD section 11) lives in cli.py (#26); this
module raises a distinct exception type so the CLI can emit a tailored
diagnostic distinguishing "input was malformed" (``PipelineError``) from
"a secret slipped past scrub" (``ResidualSecretError``).
"""

from __future__ import annotations

from typing import AbstractSet, Iterable, Sequence

from .config import ExtraSecretPattern, Rule
from .rules.secrets import iter_all_secret_patterns


class ResidualSecretError(Exception):
    """Raised when the residual scan finds a secret in the serialized output.

    ``kind`` is the pattern label that matched (e.g. ``"anthropic-key"``);
    the matched bytes are intentionally **not** recorded on the exception
    so the D-2 "no stored originals" invariant survives propagation through
    logs and tracebacks. The CLI (#26) maps this to exit code 2.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(
            f"residual secret scan matched pattern kind={kind!r}; "
            f"output was not written"
        )
        self.kind = kind


def scan_residual(
    lines: Iterable[str], extras: Sequence[ExtraSecretPattern]
) -> None:
    """Scan the serialized sanitizer output lines for surviving secret patterns.

    Returns ``None`` on a clean scan; raises ``ResidualSecretError`` on the
    first match. The orchestrator's contract piggybacks on this: if
    ``sanitize_session`` returns at all, the residual scan passed, and the
    sidecar can record ``residual_scan: clean`` (PRD section 10).

    Scans **per line** rather than over a joined buffer. JSONL guarantees
    one record per line, ``serialize_line`` escapes embedded newlines, and
    every built-in credential pattern matches within a single line --
    including the PEM-armor header, which is one-line by construction. A
    per-line scan keeps the *semantics* of ``re.search`` aligned with what
    ``build_secret_transform`` applies per leaf (so anchored extras like
    ``re:^CORP-...$`` behave consistently between detect-during-scrub and
    verify-after-scrub), and avoids any cross-line spillover from patterns
    using ``\\s+`` (bearer-token, conn-string-pw).

    Pattern ordering reuses ``iter_all_secret_patterns(extras)`` so the
    "built-ins first, extras last" invariant is shared structurally with
    ``build_secret_transform`` -- a single definition of the iteration
    order across detect and verify sites.

    Args:
        lines: serialized output records (one per element). Iterated once.
        extras: ``Config.extra_secret_patterns``. Scanned after built-ins
            (see ``iter_all_secret_patterns``) so the failure label prefers
            the more general built-in kind on overlap. Intra-built-in
            tiebreak follows VENDORED_PATTERNS + BATCH_PATTERNS declaration
            order; reordering those lists silently changes the reported
            ``kind`` on overlapping matches, so the lists themselves are
            the contract.

    Raises:
        ResidualSecretError: a pattern (built-in or extra) matched some
            line. The exception carries only the pattern's ``kind`` label;
            the matched bytes are never recorded (D-2).
    """
    patterns = tuple(iter_all_secret_patterns(extras))
    for line in lines:
        for pattern, kind in patterns:
            if pattern.search(line):
                raise ResidualSecretError(kind)


class ResidualRuleError(Exception):
    """Raised when the residual rule scan finds a configured path/identifier
    value in the serialized output.

    Carries only ``section`` (``"paths"`` / ``"identifiers"``) and the rule's
    zero-based ``index`` within that section -- never ``Rule.pattern`` and
    never the matched span. This is stricter than ``ResidualSecretError``
    needs to be, and deliberately so: a secret pattern's ``kind`` is a
    generic label, but a path/identifier rule's ``match`` value **is** the
    literal PII the config exists to scrub (real home dir, real name, real
    email). That is why the config file itself is gitignored (PRD section 12b).

    This gate fires on runs that otherwise look successful -- the ones that
    execute in CI and inside Claude Code sessions -- so a diagnostic carrying
    the match value would write real PII into exactly the artifact class this
    repo exists to sanitize. ``section[index]`` is enough to find the rule in
    a config the operator already has open.

    The CLI (#26) maps this to exit code 2.
    """

    def __init__(self, section: str, index: int) -> None:
        super().__init__(
            f"residual rule scan matched {section}[{index}]; "
            f"output was not written"
        )
        self.section = section
        self.index = index


def scan_residual_rules(
    lines: Iterable[str],
    paths: Sequence[Rule],
    identifiers: Sequence[Rule],
    allowed_replacements: AbstractSet[str],
) -> None:
    """Scan serialized output for surviving ``paths``/``identifiers`` values.

    The output-side oracle for the config rule family (#195). ``scan_residual``
    above gives the *secret* layer a total, position-agnostic guarantee: it
    reads the serialized output, so a value the structural walk never reached
    is still in those bytes and still aborts the run. Paths and identifiers
    had no such pass, so any traversal gap leaked **silently** -- exit 0,
    output written, sidecar reporting ``residual_scan: clean``. Two such gaps
    are known (#190 dict keys are never visited, #194 the skip-list exempts
    user data at any depth), and the position space is not ours to enumerate:
    tool inputs are tool-defined and MCP servers define their own schemas.
    This function closes the class rather than the instances.

    Scans exactly the bytes that will be written. ``run_pipeline`` drops
    strip-types lines before returning, so a configured value on a dropped
    line is correctly **not** an abort -- it never reaches the output file.

    Matching uses ``rule.compiled``, so literal and regex rules are covered on
    identical footing (``_compile_rule`` stores literals ``re.escape``d).
    Per-line, for the reasons ``scan_residual`` documents; the argument is
    stronger here, since a path/identifier match is within-leaf and never
    spans a JSONL record boundary.

    **The allow-set, and why it is exact membership rather than masking.**
    Load-time I-3 (``config.py`` ``_check_replacement_leak``) already forbids
    any rule from matching any *configured* replacement, so on clean output
    the configured replacements cannot trip this scan. It cannot cover values
    **synthesized at runtime**: with ``remap_uuids: true`` the identifier layer
    early-returns on a ``UUID_FIELDS`` leaf and substitutes a SHA-256-derived
    UUID that no load-time check has ever seen, so a broad rule (say
    ``re:[0-9a-f-]{36}``) would never fire during scrub yet would match that
    UUID here -- a false abort on every run.

    The fix is to consult an allow-set of the replacements the run actually
    recorded, and to test **exact span membership** rather than deleting those
    strings from the line first. Deletion would be unsafe in the one direction
    a security tool cannot tolerate: rule ``match: abc123`` / ``replace: abc``
    passes I-3, so stripping every ``abc`` from a line where ``abc123``
    genuinely leaked leaves ``123``, the rule no longer matches, and the leak
    ships with a clean sidecar. Exact membership cannot produce that false
    negative -- a genuine leak is an *original*, and I-3's full cross-product
    guarantees transitively that no replacement equals any original, so a real
    leak's span is never in the allow-set.

    Args:
        lines: serialized output records (one per element). Iterated once.
        paths: ``Config.paths``, scanned first.
        identifiers: ``Config.identifiers``, scanned second. The order and the
            ascending index within each section are part of the contract --
            they determine which ``section[index]`` a multi-rule match
            reports, so tests can assert on it.
        allowed_replacements: every ``replacement`` the run's
            ``SubstitutionTable`` recorded, including ``identifiers:uuid``
            rows. A match whose span is exactly one of these is the
            sanitizer's own output and is not a survivor.

    Raises:
        ResidualRuleError: a configured rule matched a span that is not a
            recorded replacement. Carries the section and index only; the
            matched bytes are never recorded (D-2).
    """
    rules = tuple(
        (section, index, rule)
        for section, section_rules in (("paths", paths), ("identifiers", identifiers))
        for index, rule in enumerate(section_rules)
    )
    for line in lines:
        for section, index, rule in rules:
            # ``finditer`` rather than ``search``: the first match may be the
            # sanitizer's own replacement while a later one on the same line
            # is a genuine survivor. Zero-width patterns cannot stall this
            # loop -- ``_reject_zero_width_pattern`` rejects them at config
            # load, so every match advances.
            for match in rule.compiled.finditer(line):
                if match.group(0) in allowed_replacements:
                    continue
                raise ResidualRuleError(section, index)


__all__ = [
    "ResidualRuleError",
    "ResidualSecretError",
    "scan_residual",
    "scan_residual_rules",
]
