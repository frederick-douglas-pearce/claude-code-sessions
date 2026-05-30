"""Layer 1: path scrubbing (home directory, project slug, configured paths).

PRD reference: section 7 (Layer 1: paths). Runs first because path
normalization is the broadest structural transform; later layers see
already-normalized text and the residual scan is the backstop for
interaction effects.

Implementation lands with issue #21 (Layer 1: paths).
"""

from __future__ import annotations
