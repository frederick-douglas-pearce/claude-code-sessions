#!/usr/bin/env python3
"""Stop hook that walks the three Stop outcomes once each, then gets out of the way.

Stage 0: decision=block, which feeds `reason` back and should set
         `preventedContinuation` / `stopReason`.
Stage 1: hookSpecificOutput.additionalContext, the non-error path that should
         land in `hookAdditionalContext`.
Stage 2+: allow the turn to end.

The counter file bounds it. Seeded to 2 so every Stop allows until the counter
is deleted, which the last prompt of the run does. Run 1 confirmed the allow
path: `preventedContinuation: false`, `stopReason: ""`, `hookAdditionalContext: []`.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _log import note, read_event  # noqa: E402

event = read_event()
counter = Path(__file__).resolve().parent.parent / ".stop-stage"
stage = int(counter.read_text().strip()) if counter.exists() else 0
counter.write_text(f"{stage + 1}\n")

if stage == 0:
    note(event, "stop_three_ways", "stage0-block")
    json.dump(
        {
            "decision": "block",
            "reason": "fixture hook: one-time block. Reply with the single word CONTINUING and nothing else.",
        },
        sys.stdout,
    )
elif stage == 1:
    note(event, "stop_three_ways", "stage1-additionalContext")
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": "fixture hook: one-time Stop feedback, no action required. Reply with the single word NOTED and nothing else.",
            }
        },
        sys.stdout,
    )
else:
    note(event, "stop_three_ways", "allow")
