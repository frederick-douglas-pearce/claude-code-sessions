"""Layer 3: secret detection and redaction.

PRD reference: section 9 (Layer 3: secrets). Two-tier pattern library:

    Tier 1 — VENDORED_PATTERNS: copied verbatim from
        ``.claude/hooks/detect_secrets_in_output.py`` (D-6). A repo-level
        sync-test (I-4) guards drift between this copy and the hook's
        compiled patterns. Order must match the hook's SECRET_PATTERNS
        element-wise.

    Tier 2 — BATCH_PATTERNS: sanitizer-only additions for credential shapes
        the hook never had to catch (PEM keys, JWTs, bearer tokens, DB
        connection strings with embedded passwords, Slack tokens). NOT
        compared against the hook.

YAML config may *add* via ``extra_secret_patterns`` (loaded by ``config.py``).
The built-in floor in this module cannot be weakened from config (D-1).

This story (#19) lands the pattern constants only so the config loader's
I-3 replacement-leak guard has something to check against. The structural
scrub layer and the hook sync-test land with #23.
"""

from __future__ import annotations

VENDORED_PATTERNS: list[tuple[str, str]] = [
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "anthropic-key"),
    (r"sk-proj-[A-Za-z0-9_-]{20,}", "openai-project-key"),
    (r"sk-[A-Za-z0-9]{40,}", "openai-key-legacy"),
    (r"ghp_[A-Za-z0-9]{30,}", "github-pat-classic"),
    (r"github_pat_[A-Za-z0-9_]{40,}", "github-pat-fine"),
    (r"AKIA[A-Z0-9]{16}", "aws-access-key-id"),
    (r"AIza[A-Za-z0-9_-]{35}", "gcp-api-key"),
]

BATCH_PATTERNS: list[tuple[str, str]] = [
    # PEM private-key armor. Includes ENCRYPTED PRIVATE KEY (PKCS#8 encrypted,
    # what ``openssl pkcs8`` and ``ssh-keygen`` with a passphrase produce) so
    # encrypted keys do not slip past as if they were not key material.
    (
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----",
        "pem-private-key",
    ),
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

__all__ = ["VENDORED_PATTERNS", "BATCH_PATTERNS", "SECRET_PATTERNS"]
