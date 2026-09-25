#!/usr/bin/env python3
"""PreToolUse hook that always fails, without blocking the call.

Exits 1, which is a non-blocking error: Claude Code records the failure and
lets the tool call proceed. Populates `hookErrors` if such a firing reaches
disk at all.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import note, read_event  # noqa: E402

note(read_event(), "fail_on_glob", "exit-1-nonblocking")
sys.stderr.write("fixture hook: deliberate non-blocking failure\n")
sys.exit(1)
