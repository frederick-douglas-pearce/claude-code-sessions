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

from typing import Iterable, Sequence

from .config import ExtraSecretPattern
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


__all__ = [
    "ResidualSecretError",
    "scan_residual",
]
