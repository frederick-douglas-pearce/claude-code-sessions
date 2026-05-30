"""Layer 2: identifier scrubbing (emails, gitBranch, optional UUID remap).

PRD reference: section 8 (Layer 2: identifiers). UUID remapping is off by
default — uuid/parentUuid/sessionId/agentId are high-entropy random values
that leak nothing on their own; remapping requires preserving graph links.

Implementation lands with issue #22 (Layer 2: identifiers).
"""

from __future__ import annotations
