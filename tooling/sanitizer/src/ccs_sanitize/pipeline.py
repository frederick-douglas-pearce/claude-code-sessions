"""Line-oriented sanitization pipeline.

PRD reference: section 6 (architecture overview), section 6b (line-type
stripping and structural traversal with skip-list), section 5 (residual
secret scan as the post-scrub backstop).

Implementation lands with issue #20 (pipeline core) and #24 (residual
scan + fail-closed orchestration).
"""

from __future__ import annotations
