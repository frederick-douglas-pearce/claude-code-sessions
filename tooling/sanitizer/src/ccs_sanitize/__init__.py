"""ccs_sanitize — scrub Claude Code session JSONL for safe publication.

Design: see `.claude/specs/prd-sanitizer.md` in the repository.

Bumping `__version__` is required for any change that alters the produced
output bytes (new rule semantics, new secret patterns, changed serialization),
because the value is recorded in every `.scrubbed` sidecar (PRD section 10) and
downstream consumers gate on it. See CHANGELOG.md for the bump policy.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
