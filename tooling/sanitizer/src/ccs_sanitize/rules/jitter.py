"""Layer 4: jitter — DESIGNED but not implemented in v0 (D-3).

PRD reference: section 9b (Layer 4: jitter deferred to v1, but designed).

v1 design, recorded here so the seam exists:

  - Granularity: per-session offset. A single random offset (~±N days plus a
    within-day shift) is applied to all `timestamp` fields in a session,
    preserving relative timing between lines while destroying absolute
    wall-clock (which leaks working hours and dates). Per-field or
    per-message jitter was rejected — it corrupts the analytically valuable
    relative-timing signal.

  - Token-count jitter: off by default; bounded (±small %) when enabled.

  - Shared seed → bundle mode. Because jitter is randomized, a parent
    session and its subagent traces must be jittered with the same seed and
    offset or their timestamps desynchronize. v1 introduces `--session-dir`
    mode that processes a parent plus its `subagents/*.jsonl` with one
    shared substitution table and one jitter seed.

v0 sidecars record `jitter: disabled` so the format is forward-compatible.
"""

from __future__ import annotations

JITTER_DISABLED = True
