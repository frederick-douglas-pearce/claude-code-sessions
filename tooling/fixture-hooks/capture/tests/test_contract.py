"""The content-free contract for otlp_sink.py and analyze.py.

Both read sensitive input: the sink receives Claude Code's raw telemetry, with
`user.email`, account and org ids, and, if a detail flag is on, commands and
tool input; analyze.py reads the raw debug log. Plant canaries in every
value-bearing surface either one reads, then assert that no canary byte reaches
the sink's file or analyze.py's stdout.

The canaries are synthetic. The suite is hermetic and offline.

Run: ``python3 -m pytest tooling/fixture-hooks/capture/tests/``
"""

import gzip
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import analyze
import otlp_sink

CANARY = "CANARY7Q"


def sv(value):
    return {"stringValue": value}


def attr(key, value):
    return {"key": key, "value": value}


IDENTITY = [
    attr("user.email", sv(f"{CANARY}@example.com")),
    attr("user.account_uuid", sv(f"{CANARY}-acct")),
    attr("organization.id", sv(f"{CANARY}-org")),
    attr("user.id", sv(f"{CANARY}-uid")),
    attr("vcs.repository.url", sv(f"https://example.com/{CANARY}/repo")),
    attr("host.name", sv(f"{CANARY}-host")),
]


def log_record(name, seq, **extra):
    attrs = [attr("event.name", sv(name.removeprefix("claude_code."))), attr("event.sequence", {"intValue": str(seq)}),
             *IDENTITY]
    attrs += [attr(k, v) for k, v in extra.items()]
    return {"timeUnixNano": "1", "body": sv(name), "attributes": attrs}


def otlp_logs():
    records = [
        log_record("claude_code.hook_registered", 1, hook_event=sv("PreToolUse"), hook_type=sv("command"),
                   hook_source=sv("projectSettings"),
                   hook_definitions=sv(f'[{{"command":"/home/{CANARY}/x.py"}}]')),
        log_record("claude_code.hook_execution_start", 2, hook_event=sv("PreToolUse"), hook_name=sv("PreToolUse:Read")),
        log_record("claude_code.api_request", 3, query_source=sv("hook_prompt"), model=sv("claude-haiku-5-5"),
                   input_tokens={"intValue": "120"}, output_tokens={"intValue": "9"},
                   error=sv(f"{CANARY} error text")),
        log_record("claude_code.hook_execution_complete", 4, hook_event=sv("PreToolUse"),
                   hook_name=sv("PreToolUse:Read"), num_hooks={"intValue": "1"}, num_blocking={"intValue": "1"}),
        log_record("claude_code.tool_decision", 5, tool_name=sv("Read"), tool_use_id=sv("toolu_0001abcd"),
                   decision=sv("reject"), source=sv("hook"),
                   tool_parameters=sv(f'{{"file_path":"/home/{CANARY}/f"}}')),
        log_record("claude_code.user_prompt", 6, prompt=sv(f"{CANARY} prompt text")),
        {"timeUnixNano": "1", "body": sv(f"{CANARY} free text body"), "attributes": IDENTITY},
    ]
    return {"resourceLogs": [{"resource": {"attributes": [attr("service.name", sv("claude-code")), *IDENTITY]},
                              "scopeLogs": [{"logRecords": records}]}]}


def otlp_metrics():
    point = {"timeUnixNano": "5", "asDouble": 0.0012,
             "attributes": [attr("query_source", sv("auxiliary")), attr("model", sv("claude-haiku-5-5")), *IDENTITY]}
    return {"resourceMetrics": [{"resource": {"attributes": IDENTITY}, "scopeMetrics": [{"metrics": [
        {"name": "claude_code.cost.usage", "sum": {"aggregationTemporality": 2, "dataPoints": [point]}},
        {"name": f"{CANARY}.metric", "gauge": {"dataPoints": [point]}},
    ]}]}]}


def start_sink(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), otlp_sink.make_handler(tmp_path / "otel-c.jsonl"))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def post(url, body, gzipped=False):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if gzipped:
        data, headers["Content-Encoding"] = gzip.compress(data), "gzip"
    urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=5).read()


def test_sink_drops_every_canary(tmp_path):
    server, base = start_sink(tmp_path)
    try:
        post(base + "/v1/logs", otlp_logs())
        post(base + "/v1/metrics", otlp_metrics(), gzipped=True)
    finally:
        server.shutdown()
    written = (tmp_path / "otel-c.jsonl").read_text()
    assert CANARY not in written
    records = [json.loads(line) for line in written.splitlines()]
    decision = next(r for r in records if r.get("body") == "claude_code.tool_decision")
    assert decision["attrs"]["source"] == "hook" and decision["attrs"]["tool_use_id"] == "toolu_0001abcd"
    assert decision["attrs"]["user.email"] == {"redacted": True, "type": "string", "len": len(f"{CANARY}@example.com")}
    assert any(r["signal"] == "metric" and r["value"] == 0.0012 for r in records)


DEBUG_LOG = f"""\
2026-10-13T20:00:00.100Z [DEBUG] Hook output does not start with {{, treating as plain text
2026-10-13T20:00:00.101Z [DEBUG] "Hook PostToolUse:Read (PostToolUse) success:\\n{CANARY} hook stdout"
2026-10-13T20:00:00.200Z [DEBUG] Hooks: PreToolUse:Read [python3 "/home/{CANARY}/scratch/dispatcher.py"] finished with status 0 (61ms)
2026-10-13T20:00:00.300Z [DEBUG] Hooks: PreToolUse:Read [/home/{CANARY}/{CANARY}.py] finished with status 2 (12ms)
2026-10-13T20:00:00.400Z [DEBUG] Hooks: PreToolUse:{CANARY}/x [python3 "/home/{CANARY}/dispatcher.py"] timed out after 5000ms
2026-10-13T20:00:00.500Z [DEBUG] Hooks: Stop [weird {CANARY} line without an outcome
2026-10-13T20:00:00.600Z [ERROR] [3P telemetry] export failed: {CANARY} detail
"""


def test_analyze_emits_no_canary(tmp_path, capsys):
    server, base = start_sink(tmp_path)
    try:
        post(base + "/v1/logs", otlp_logs())
        post(base + "/v1/metrics", otlp_metrics())
    finally:
        server.shutdown()
    (tmp_path / "debug-c.log").write_text(DEBUG_LOG)
    t0 = 1_760_385_600_100.0  # 2026-10-13T20:00:00.100Z in ms
    dispatch = [
        {"ts_ms": t0, "phase": "enter", "pid": 1, "session_id": "s", "tool_use_id": "toolu_0001abcd",
         "event": "PreToolUse", "tool": "Read", "route": "deny", "agent_type": f"{CANARY} agent"},
        {"ts_ms": t0 + 50, "phase": "exit", "pid": 1, "event": "PreToolUse", "tool": "Read", "route": "deny",
         "decision": "deny", "duration_ms": 50.0},
    ]
    (tmp_path / "dispatch-c.jsonl").write_text("\n".join(json.dumps(r) for r in dispatch) + "\n{torn")
    (tmp_path / "judge-c.jsonl").write_text(json.dumps(
        {"tool_use_id": "toolu_0002", "decision": "deny", "ok": False, "error": f"{CANARY} message",
         "usage": {"input_tokens": 300, "output_tokens": 40}}) + "\n")
    (tmp_path / "http-guard-c.jsonl").write_text(json.dumps(
        {"recv_ms": 1.0, "sent_ms": 2.0, "mode": "up", "sentinel": f"{CANARY}.txt", "status": 200,
         "decision": "deny", "delivered": True}) + "\n")
    session = tmp_path / "sanitized.jsonl"
    session.write_text("\n".join(json.dumps(r) for r in [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_0001abcd", "name": "Read",
             "input": {"file_path": f"/home/{CANARY}/secret-{CANARY}.txt"}},
            {"type": "text", "text": f"{CANARY} assistant prose"}]}},
        {"type": "user", "toolDenialKind": f"{CANARY} kind", "toolUseResult": {"file": {"filePath": f"/x/{CANARY}"}},
         "permissionDecision": {"decision": "reject", "source": f"{CANARY} source", "reasonType": "hook"},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_0001abcd", "is_error": True,
                                  "content": f"{CANARY} result"}]}},
        {"type": "system", "subtype": "stop_hook_summary", "hookInfos": [{"command": f"/home/{CANARY}/h.py"}]},
    ]) + "\n")

    assert analyze.main(["--dir", str(tmp_path), "--tag", "c", "--session", str(session)]) == 0
    out = capsys.readouterr().out
    assert CANARY not in out
    # And it still reports what it is for.
    assert "| PreToolUse | Read | dispatcher.py | finished | 0 | - | 1 |" in out
    assert "Lines that failed to parse (torn appends): **1**" in out
    assert "**1** unparsed" in out and "**1** `[3P telemetry]` lines" in out
    assert "hook_prompt" in out and "| hook |" in out
    assert "| reject/<other>/hook |" in out


def test_analyze_refuses_raw_session_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    raw = tmp_path / ".claude" / "projects" / "p" / "s.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}\n")
    assert analyze.main(["--session", str(raw)]) == 2
