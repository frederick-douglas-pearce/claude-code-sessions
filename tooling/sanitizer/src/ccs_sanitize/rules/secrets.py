"""Layer 3: secret detection and redaction.

PRD reference: section 9 (Layer 3: secrets). Two-tier pattern library:

    Tier 1 -- VENDORED_PATTERNS: copied verbatim from
        ``.claude/hooks/detect_secrets_in_output.py`` (D-6). The repo-level
        sync-test (I-4) at ``tests/test_secret_patterns_in_sync.py`` guards
        drift between this copy and the hook's compiled patterns. Order must
        match the hook's SECRET_PATTERNS element-wise.

    Tier 2 -- BATCH_PATTERNS: sanitizer-only additions for credential shapes
        the hook does not currently catch (bearer tokens, JWTs, DB
        connection strings with embedded passwords, Slack tokens). NOT
        compared against the hook. Tracked for future evaluation per the
        option-2 backlog issue.

YAML config may *add* via ``extra_secret_patterns`` (loaded by ``config.py``).
The built-in floor in this module cannot be weakened from config (D-1):
``build_secret_transform`` always applies the built-ins first and only then
runs extras, so an extra can never shadow a built-in match -- by the time
extras run, any built-in hit has already become ``<REDACTED:kind>`` and no
longer looks like a credential.

**Secrets are redacted, never remapped** (PRD section 10, D-2). The matched
bytes are replaced with ``<REDACTED:kind>`` and only a per-kind count is
surfaced to the sidecar. The matched value is never stored anywhere -- not
in a ``SubstitutionTable``, not in any per-kind sample, nothing. That is
why this layer has its own ``SecretCounts`` data structure rather than
reusing ``SubstitutionTable``: the table stores originals (which is the
right shape for paths/identifiers, where the sidecar lists each
substitution by category), and reusing it would make the no-originals
invariant disciplinary rather than structural.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Sequence

from ..pipeline import JsonPath, TransformCallback

if TYPE_CHECKING:
    # config.py imports COMPILED_SECRET_PATTERNS from this module at import
    # time; a runtime ExtraSecretPattern import here would close that loop.
    # The runtime ``build_secret_transform`` only reads ``.compiled`` and
    # ``.kind`` off each extra (duck-typed), so the symbol is needed only
    # for the type annotation.
    from ..config import ExtraSecretPattern

SECRET_PLACEHOLDER_TEMPLATE = "<REDACTED:{kind}>"

VENDORED_PATTERNS: list[tuple[str, str]] = [
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "anthropic-key"),
    (r"sk-proj-[A-Za-z0-9_-]{20,}", "openai-project-key"),
    (r"sk-[A-Za-z0-9]{40,}", "openai-key-legacy"),
    (r"ghp_[A-Za-z0-9]{30,}", "github-pat-classic"),
    (r"github_pat_[A-Za-z0-9_]{40,}", "github-pat-fine"),
    (r"AKIA[A-Z0-9]{16}", "aws-access-key-id"),
    (r"AIza[A-Za-z0-9_-]{35}", "gcp-api-key"),
    # PEM private-key armor. Covers unencrypted variants and PKCS#8 encrypted
    # (what ``openssl pkcs8``, passphrase-protected ``ssh-keygen``, and many
    # cloud APIs produce). Promoted from BATCH_PATTERNS to Tier 1 because the
    # hook also needs this coverage: ``cat ~/.ssh/id_rsa`` in a live tool
    # output is exactly the catastrophic case the hook exists to block.
    # Mirrored verbatim in the hook's SECRET_PATTERNS at the same position;
    # the I-4 sync test gates the duplication.
    (
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----",
        "pem-private-key",
    ),
]

BATCH_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]+", "bearer-token"),
    (
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "jwt",
    ),
    (
        r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://[^:\s/]+:[^@\s]+@",
        "conn-string-pw",
    ),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "slack-token"),
]

SECRET_PATTERNS: list[tuple[str, str]] = VENDORED_PATTERNS + BATCH_PATTERNS

# Compile-once snapshot of the built-in patterns. Public so other modules
# that need to scan with the same set (the config loader's I-3 leak guard,
# the residual scan in #24) import this instead of recompiling -- a single
# compile site is the canonical truth for compilation flags. A typo in any
# raw pattern surfaces here at import time rather than on first call.
COMPILED_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern), kind) for pattern, kind in SECRET_PATTERNS
]


@dataclass
class SecretCounts:
    """Per-kind match counter for Layer 3 -- the sidecar input (PRD section 10).

    Distinct from ``SubstitutionTable`` because D-2 forbids storing any
    matched bytes for secrets: only the count survives. A separate type
    makes that invariant structural (the class has no API to record an
    original) rather than disciplinary.

    Insertion order is preserved (CPython dict semantics) so the sidecar
    can emit kinds in first-seen order, matching the substitution table's
    convention.
    """

    _counts: dict[str, int] = field(default_factory=dict)

    def record(self, kind: str) -> None:
        """Increment the match counter for ``kind`` by one."""
        self._counts[kind] = self._counts.get(kind, 0) + 1

    def as_mapping(self) -> Mapping[str, int]:
        """Return a snapshot copy of the per-kind counts.

        A copy (rather than a live view) so the sidecar can serialize a
        stable picture even if a future caller keeps recording after the
        snapshot is taken.
        """
        return dict(self._counts)

    def total(self) -> int:
        """Return the total number of secret matches across all kinds.

        Feeds the sidecar's ``rules_applied.secrets.matches: N`` summary
        line (PRD section 10). Parallels ``SubstitutionTable.total_occurrences``.
        """
        return sum(self._counts.values())

    def __len__(self) -> int:
        """Number of distinct kinds with at least one match."""
        return len(self._counts)


def build_secret_transform(
    extras: Sequence[ExtraSecretPattern],
    counts: SecretCounts,
) -> TransformCallback:
    """Build a transform that redacts every secret match in a string leaf.

    Built-ins always apply first; extras append last. Extras cannot shadow
    a built-in: by the time an extra's regex runs, any built-in match has
    already become ``<REDACTED:kind>``, which does not look like a
    credential pattern. This is the D-1 floor expressed in the pipeline
    structure, not just in the loader.

    Args:
        extras: caller-supplied additive patterns from
            ``Config.extra_secret_patterns``. Typed as ``Sequence`` so the
            closure can iterate the snapshot freely; an iterable would
            forbid the per-leaf re-scan that ``re.sub`` performs internally.
        counts: shared ``SecretCounts`` the transform records into. The
            pipeline driver constructs one per run and hands the same
            instance to the sidecar.

    Returns:
        A ``TransformCallback`` suitable for ``run_pipeline(transform=...)``.
        The callback closes over a tuple snapshot of the combined pattern
        list (built-ins + extras at build time) so a caller-side mutation
        of ``extras`` after build cannot smuggle a pattern in or out
        mid-run.
    """
    snapshot: tuple[tuple[re.Pattern[str], str], ...] = (
        tuple(COMPILED_SECRET_PATTERNS)
        + tuple((extra.compiled, extra.kind) for extra in extras)
    )

    def transform(leaf: str, path: JsonPath) -> str:
        result = leaf
        for pattern, kind in snapshot:
            placeholder = SECRET_PLACEHOLDER_TEMPLATE.format(kind=kind)

            def repl(match: re.Match[str], _kind: str = kind, _ph: str = placeholder) -> str:
                # Zero-width matches would otherwise be recorded as "found a
                # secret of length 0" -- meaningless for the sidecar count
                # and indicative of a misconfigured extra pattern. The
                # config loader's _reject_zero_width_pattern catches the
                # static case; this is the runtime backstop for lookaheads
                # and \b. Note: built-in patterns are all consuming, so this
                # branch only ever fires for misbuilt extras.
                if not match.group(0):
                    return ""
                counts.record(_kind)
                return _ph

            result = pattern.sub(repl, result)
        return result

    return transform


__all__ = [
    "BATCH_PATTERNS",
    "COMPILED_SECRET_PATTERNS",
    "SECRET_PATTERNS",
    "SECRET_PLACEHOLDER_TEMPLATE",
    "SecretCounts",
    "VENDORED_PATTERNS",
    "build_secret_transform",
]
