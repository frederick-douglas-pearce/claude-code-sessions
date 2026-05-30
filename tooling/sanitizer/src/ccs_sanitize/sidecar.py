"""`.scrubbed` sidecar emission.

PRD reference: section 10 (the `.scrubbed` sidecar — redacted-by-design
format, D-2). Enforces I-3 replacement-leak guard so the sidecar never
echoes a configured replacement that itself matches any path/identifier/
secret rule.

Implementation lands with issue #25 (sidecar emission).
"""

from __future__ import annotations
