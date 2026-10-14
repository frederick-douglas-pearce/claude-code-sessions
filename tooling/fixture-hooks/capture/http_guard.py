#!/usr/bin/env python3
"""A PreToolUse guard served over HTTP, for the #295 fail-open test.

Registered as an `http` hook, Claude Code POSTs each hook payload here. In
`--mode up` it denies a `Read` whose basename starts with `forbidden-http-`
(2xx with a JSON `permissionDecision: "deny"`) and returns an empty 2xx for
everything else. `--mode 500` answers every request with HTTP 500. `--mode slow`
sleeps past the hook's timeout before answering. Stopping the process is the
fourth mode: connection refused.

The log, `http-guard-<tag>.jsonl`, records the timestamp, mode, ids, event,
tool, the sentinel basename and the response. Never the request body.

Stdlib only. Binds to 127.0.0.1.
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DENY_PREFIX = "forbidden-http-"
DENY_REASON = (
    "Denied by the HTTP guard. Do not retry by any other means; "
    "stop and report the denial."
)
SLOW_SECONDS = 20

_lock = threading.Lock()


def respond_to(payload: dict, mode: str):
    """Return (status, body bytes, decision label) for one hook payload."""
    if mode == "500":
        return 500, b"guard: deliberate 500", "http-500"
    if mode == "slow":
        time.sleep(SLOW_SECONDS)
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if (
        payload.get("hook_event_name") == "PreToolUse"
        and payload.get("tool_name") == "Read"
        and os.path.basename(path).startswith(DENY_PREFIX)
    ):
        body = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": DENY_REASON,
            }
        }
        return 200, json.dumps(body).encode(), "deny"
    return 200, b"", "no-decision"


def make_handler(mode: str, out_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received = round(time.time() * 1000, 1)
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                payload = {}
            status, body, decision = respond_to(payload, mode)
            basename = os.path.basename((payload.get("tool_input") or {}).get("file_path") or "")
            record = {
                "recv_ms": received, "mode": mode, "path": self.path,
                "session_id": payload.get("session_id"),
                "tool_use_id": payload.get("tool_use_id"),
                "event": payload.get("hook_event_name"), "tool": payload.get("tool_name"),
                # Only sentinel names, which are fixed strings of this experiment.
                "sentinel": basename if basename.startswith(DENY_PREFIX) else None,
                "status": status, "decision": decision,
            }
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if body.startswith(b"{") else "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                record["delivered"] = True
            except (BrokenPipeError, ConnectionResetError):
                record["delivered"] = False  # Claude Code gave up first
            record["sent_ms"] = round(time.time() * 1000, 1)
            with _lock, out_path.open("a") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
            print(f"guard[{mode}]: {record['event']} {record['tool']} -> {status} {decision}"
                  f"{'' if record['delivered'] else ' (client gone)'}", flush=True)

        def log_message(self, *_args):
            pass

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("up", "500", "slow"), default="up")
    parser.add_argument("--tag", default=os.environ.get("HOOKCAP_TAG") or "untagged")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args(argv)
    out_path = Path(args.out_dir) / f"http-guard-{args.tag}.jsonl"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.mode, out_path))
    server.daemon_threads = True
    print(f"guard: mode {args.mode}, listening on 127.0.0.1:{args.port}, writing {out_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
