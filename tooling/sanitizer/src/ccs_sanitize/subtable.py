"""Substitution table — consistent within-file replacements.

PRD reference: section 6 (architecture overview), section 7 (paths;
"consistency = determinism is the safety property").

Implementation lands with issue #20 (pipeline core).
"""

from __future__ import annotations
