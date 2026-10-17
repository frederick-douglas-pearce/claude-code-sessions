#!/usr/bin/env python3
"""The dispatcher under test in #295: one command hook for every tool event.

Registered with a "*" matcher on PreToolUse and PostToolUse in a scratch
project, it routes on the hook payload and appends one JSON line per phase to
`dispatch-<HOOKCAP_TAG>.jsonl` in the project directory:

  enter   written as soon as the payload is parsed
  exit    written in `finally`, after the decision is printed
  killed  written from a signal handler, if Claude Code terminates the hook

A firing with `enter` and no `exit` or `killed` line was killed by a signal that
cannot be caught, or crashed on purpose (the `crash` route).

Routing happens on PreToolUse `Read` calls only, by the basename of
`tool_input.file_path`. Every other firing, PostToolUse included, logs and
decides nothing. The log carries ids, routes and decisions, never `tool_input`.
"""

import time

T0 = time.time()
T0_MONO = time.monotonic()

import json  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402
import sys  # noqa: E402

DENY_REASON = (
    "Denied by the dispatcher. Do not retry by any other means; "
    "stop and report the denial."
)

ROUTES = {
    "allow.txt": "allow",
    "ask.txt": "ask",
    "rewrite.txt": "rewrite",
    "forbidden.txt": "deny",
    "slow.txt": "sleep",
    "crash.txt": "crash",
}

SLEEP_SECONDS = 20
REWRITE_TARGET = "rewrite-target.txt"

_fd = None
_base = {}


def _log_path() -> str:
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    tag = os.environ.get("HOOKCAP_TAG") or "untagged"
    return os.path.join(project, f"dispatch-{tag}.jsonl")


def _write(phase: str, **fields) -> None:
    """Append one line with a single write() on an O_APPEND descriptor."""
    global _fd
    if _fd is None:
        _fd = os.open(_log_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    record = {
        "ts_ms": round(T0 * 1000, 1) if phase == "enter" else round(time.time() * 1000, 1),
        "phase": phase,
        "pid": os.getpid(),
        **_base,
        **fields,
        "duration_ms": round((time.monotonic() - T0_MONO) * 1000, 1),
    }
    os.write(_fd, (json.dumps(record, separators=(",", ":")) + "\n").encode())


def _on_signal(signum, _frame):
    _write("killed", signal=signal.Signals(signum).name)
    os._exit(128 + signum)


def route_for(payload: dict) -> str:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != "Read":
        return "no-decision"
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    return ROUTES.get(os.path.basename(path), "no-decision")


def decide(route: str, payload: dict):
    """Return (decision label, hook output dict or None)."""
    if route in ("allow", "ask", "deny"):
        reasons = {
            "allow": "Allowed by the dispatcher (allow route).",
            "ask": "The dispatcher asks for confirmation (ask route).",
            "deny": DENY_REASON,
        }
        return route, {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": route,
                "permissionDecisionReason": reasons[route],
            }
        }
    if route == "rewrite":
        tool_input = dict(payload.get("tool_input") or {})
        tool_input["file_path"] = os.path.join(
            os.path.dirname(tool_input.get("file_path", "")), REWRITE_TARGET
        )
        return "allow+updatedInput", {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "Rewritten by the dispatcher (rewrite route).",
                "updatedInput": tool_input,
            }
        }
    if route == "sleep":
        time.sleep(SLEEP_SECONDS)
    return "no-decision", None


def main() -> int:
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _on_signal)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    route = route_for(payload)
    _base.update(
        session_id=payload.get("session_id"),
        tool_use_id=payload.get("tool_use_id"),
        agent_id=payload.get("agent_id"),
        agent_type=payload.get("agent_type"),
        event=payload.get("hook_event_name"),
        tool=payload.get("tool_name"),
        route=route,
    )
    # PostToolUse reports how long the tool itself ran. A number, not content.
    if "duration_ms" in payload:
        _base["tool_duration_ms"] = payload["duration_ms"]
    _write("enter")

    if route == "crash":
        sys.stderr.write("dispatcher: deliberate crash, no decision returned\n")
        os._exit(1)

    decision, exit_code = "error", 1
    try:
        decision, output = decide(route, payload)
        if output is not None:
            sys.stdout.write(json.dumps(output))
            sys.stdout.flush()
        exit_code = 0
    except Exception as exc:  # log failures too, or they become a new silent gap
        sys.stderr.write(f"dispatcher: {type(exc).__name__}\n")
    finally:
        _write("exit", decision=decision, exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
