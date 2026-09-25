"""Shared side-channel log for the fixture hooks.

The point of the log is the diff. It records every firing, whichever way the
hook exits. The session JSONL records some subset of those firings. Comparing
the two is the measurement: which hook firings reach disk, and which leave
nothing behind.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "hook-firings.log"


def read_event() -> dict:
    """Consume stdin and return the hook payload, tolerating junk."""
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def note(event: dict, script: str, outcome: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    name = event.get("hook_event_name", "?")
    tool = event.get("tool_name", "-")
    with LOG.open("a") as fh:
        fh.write(f"{stamp}\t{name}\t{tool}\t{script}\t{outcome}\n")
