"""Layer 3: secret detection and redaction.

PRD reference: section 9 (Layer 3: secrets). Two-tier pattern library:

    Tier 1 — VENDORED_PATTERNS: copied verbatim from
        `.claude/hooks/detect_secrets_in_output.py` (D-6). A repo-level
        sync-test (I-4) guards drift between this copy and the hook's
        compiled patterns.

    Tier 2 — BATCH_PATTERNS: sanitizer-only additions for credential shapes
        the hook never had to catch (PEM keys, JWTs, bearer tokens, DB
        connection strings with embedded passwords). NOT compared against
        the hook.

YAML config may *add* via `extra_secret_patterns`. The built-in floor
cannot be weakened (D-1).

Implementation lands with issue #23 (Layer 3: secrets + pattern-sync test).
"""

from __future__ import annotations
