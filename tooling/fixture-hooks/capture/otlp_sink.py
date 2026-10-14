#!/usr/bin/env python3
"""A local OTLP/JSON receiver for Claude Code telemetry, for #295.

Point Claude Code's OTLP exporters at it (see env.sh) and it flattens every log
record, metric data point and span into one JSON line in `otel-<tag>.jsonl`.

SECURITY CONTRACT. Claude Code's standard attributes include `user.email`,
`user.account_uuid`, `organization.id` and the repository URL, and detail flags
add commands, tool input and prompt text. This sink keeps a value only when the
attribute name is on ALLOWED. Every other attribute is written as its name, its
OTLP value type and its length, so a new attribute is noticed without its value
ever reaching disk. An allowlist rather than a denylist, because a denylist
fails open, which is the failure #295 studies.

Log bodies and metric/span names are kept only when they start with
`claude_code.`; otherwise they are reduced the same way.

Stdlib only. Binds to 127.0.0.1.
"""

import argparse
import gzip
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOWED = frozenset(
    {
        # correlation
        "event.name", "event.timestamp", "event.sequence", "session.id", "prompt.id",
        "app.version", "service.name", "service.version", "terminal.type",
        # hook events
        "hook_event", "hook_name", "hook_type", "hook_source", "hook_matcher",
        "num_hooks", "num_success", "num_blocking", "num_non_blocking_error",
        "num_cancelled", "total_duration_ms", "stdout_chars",
        "additional_context_chars", "system_message_chars",
        "initial_user_message_chars", "num_outputs_persisted", "managed_only",
        # tool events
        "tool_name", "tool_use_id", "decision", "source", "tool_source", "success",
        "duration_ms", "error_type", "decision_type", "decision_source",
        "tool_input_size_bytes", "tool_result_size_bytes", "mcp_server_scope",
        # api events and metrics
        "model", "cost_usd", "cost_usd_micros", "input_tokens", "output_tokens",
        "cache_read_tokens", "cache_creation_tokens", "query_source", "speed",
        "effort", "type", "agent.name",
        # subagents and spans
        "agent_type", "agent.source", "is_built_in", "is_async", "total_tokens",
        "total_tool_uses", "final_model", "model_swapped", "agent_id",
        "parent_agent_id",
        # permission mode
        "permission_mode", "trigger",
    }
)

_seen_unlisted = set()
_lock = threading.Lock()


def _decode_value(value: dict):
    """Return (python value, OTLP type name) for one AnyValue."""
    for key, kind in (("stringValue", "string"), ("boolValue", "bool"), ("doubleValue", "double")):
        if key in value:
            return value[key], kind
    if "intValue" in value:
        return int(value["intValue"]), "int"
    if "arrayValue" in value:
        return [_decode_value(v)[0] for v in value["arrayValue"].get("values", [])], "array"
    if "kvlistValue" in value:
        return {kv["key"]: _decode_value(kv.get("value", {}))[0] for kv in value["kvlistValue"].get("values", [])}, "kvlist"
    if "bytesValue" in value:
        return value["bytesValue"], "bytes"
    return None, "empty"


def _reduce(value, kind: str) -> dict:
    """The redacted form of a value: its type and size, never its content."""
    size = len(value) if isinstance(value, (str, list, dict)) else None
    return {"redacted": True, "type": kind, "len": size}


def filter_attributes(attributes: list) -> dict:
    out = {}
    for kv in attributes or []:
        name = kv.get("key", "")
        value, kind = _decode_value(kv.get("value", {}))
        if name in ALLOWED:
            out[name] = value
        else:
            out[name] = _reduce(value, kind)
            if name not in _seen_unlisted:
                _seen_unlisted.add(name)
                print(f"sink: new unlisted attribute {name!r} ({kind}), value dropped", file=sys.stderr)
    return out


def _safe_name(name) -> object:
    if isinstance(name, str) and name.startswith("claude_code."):
        return name
    return _reduce(name, "string") if isinstance(name, str) else None


def flatten(path: str, body: dict) -> list:
    """Flatten one OTLP/JSON export request into output records."""
    received = round(time.time() * 1000, 1)
    records = []
    for rl in body.get("resourceLogs", []):
        resource = filter_attributes(rl.get("resource", {}).get("attributes"))
        for sl in rl.get("scopeLogs", []):
            for rec in sl.get("logRecords", []):
                body_value, _ = _decode_value(rec.get("body", {}))
                records.append({
                    "signal": "log", "path": path, "recv_ms": received,
                    "time_unix_nano": rec.get("timeUnixNano"),
                    "body": _safe_name(body_value),
                    "attrs": filter_attributes(rec.get("attributes")),
                    "resource": resource,
                })
    for rm in body.get("resourceMetrics", []):
        resource = filter_attributes(rm.get("resource", {}).get("attributes"))
        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                for kind in ("sum", "gauge", "histogram"):
                    if kind not in metric:
                        continue
                    data = metric[kind]
                    for point in data.get("dataPoints", []):
                        if kind == "histogram":
                            value = {"count": int(point.get("count", 0)), "sum": point.get("sum")}
                        elif "asInt" in point:
                            value = int(point["asInt"])
                        else:
                            value = point.get("asDouble")
                        records.append({
                            "signal": "metric", "path": path, "recv_ms": received,
                            "name": _safe_name(metric.get("name")), "kind": kind,
                            "temporality": data.get("aggregationTemporality"),
                            "time_unix_nano": point.get("timeUnixNano"),
                            "value": value,
                            "attrs": filter_attributes(point.get("attributes")),
                            "resource": resource,
                        })
    for rs in body.get("resourceSpans", []):
        resource = filter_attributes(rs.get("resource", {}).get("attributes"))
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                records.append({
                    "signal": "span", "path": path, "recv_ms": received,
                    "name": _safe_name(span.get("name")),
                    "trace_id": span.get("traceId"), "span_id": span.get("spanId"),
                    "parent_span_id": span.get("parentSpanId"),
                    "start_ns": span.get("startTimeUnixNano"), "end_ns": span.get("endTimeUnixNano"),
                    "attrs": filter_attributes(span.get("attributes")),
                    "resource": resource,
                })
    return records


def make_handler(out_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            if self.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            ctype = self.headers.get("Content-Type", "")
            if "json" not in ctype:
                print(f"sink: {self.path}: non-JSON body ({ctype or 'no content type'}, {len(raw)} bytes) ignored; check OTEL_EXPORTER_OTLP_PROTOCOL", file=sys.stderr)
                records = []
            else:
                try:
                    records = flatten(self.path, json.loads(raw))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    print(f"sink: {self.path}: unparseable JSON ({len(raw)} bytes)", file=sys.stderr)
                    records = []
            if records:
                with _lock, out_path.open("a") as fh:
                    for record in records:
                        fh.write(json.dumps(record, separators=(",", ":")) + "\n")
            print(f"sink: POST {self.path}: {len(records)} records", flush=True)
            reply = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *_args):
            pass

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="session tag, e.g. s1; names the output file")
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args(argv)
    out_path = Path(args.out_dir) / f"otel-{args.tag}.jsonl"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(out_path))
    server.daemon_threads = True
    print(f"sink: listening on 127.0.0.1:{args.port}, writing {out_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
