#!/usr/bin/env python3
"""Stop hook that fails outright, to separate a genuine error from a block.

Run 2 showed `hookErrors` carrying a deliberate `decision: block` reason. This
hook exits 1 with stderr and no decision, so the same field receives a real
failure. Running both Stop hooks together puts an error and a normal firing on
one `stop_hook_summary` line, which is the comparison the post needs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import note, read_event  # noqa: E402

note(read_event(), "fail_on_stop", "exit-1-error")
sys.stderr.write("fixture hook: deliberate Stop-hook failure, no decision returned\n")
sys.exit(1)
