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

from typing import Sequence

from .config import ExtraSecretPattern
from .rules.secrets import COMPILED_SECRET_PATTERNS


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


def scan_residual(text: str, extras: Sequence[ExtraSecretPattern]) -> None:
    """Scan the serialized sanitizer output for surviving secret patterns.

    Returns ``None`` on a clean scan; raises ``ResidualSecretError`` on the
    first match. The orchestrator's contract piggybacks on this: if
    ``sanitize_session`` returns at all, the residual scan passed, and the
    sidecar can record ``residual_scan: clean`` (PRD section 10).

    Args:
        text: the full serialized output buffer. The orchestrator joins
            output lines with ``"\\n"`` before calling. **Invariant:** the
            join separator must not be a byte that can appear inside a
            credential pattern -- a separator that splits a match would
            silently weaken the gate. ``\\n`` is safe for the current
            ``COMPILED_SECRET_PATTERNS`` (all credential patterns match
            within contiguous non-whitespace runs); the PEM-armor pattern
            matches only the single-line ``-----BEGIN ... PRIVATE KEY-----``
            header, not the multi-line body. Any future pattern that could
            legitimately span a newline must revisit this choice.
        extras: ``Config.extra_secret_patterns``. Scanned after built-ins
            so the failure label prefers the more general (built-in) kind
            when a string matches both, matching the redaction order in
            ``build_secret_transform``.

    Raises:
        ResidualSecretError: a pattern (built-in or extra) matched ``text``.
            The exception carries only the pattern's ``kind`` label; the
            matched bytes are never recorded (D-2).
    """
    for pattern, kind in COMPILED_SECRET_PATTERNS:
        if pattern.search(text):
            raise ResidualSecretError(kind)
    for extra in extras:
        if extra.compiled.search(text):
            raise ResidualSecretError(extra.kind)


__all__ = [
    "ResidualSecretError",
    "scan_residual",
]
