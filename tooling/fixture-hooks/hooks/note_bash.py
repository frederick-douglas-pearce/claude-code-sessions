#!/usr/bin/env python3
"""PostToolUse hook that prints one fixed line.

Sets `hasOutput` on a record that did not block, if a non-blocking PostToolUse
firing reaches disk at all. Run 1 suggests it may not, which is why this hook
now logs its own firing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import note, read_event  # noqa: E402

note(read_event(), "note_bash", "printed-output")
print("fixture hook: PostToolUse observed a Bash call")
