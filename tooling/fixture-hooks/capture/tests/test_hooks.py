"""The capture kit's hooks, driven with synthetic payloads. Hermetic and offline.

Run: ``python3 -m pytest tooling/fixture-hooks/capture/tests/``
"""

import json
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import KIT

import http_guard
import judge_client


def run_dispatcher(tmp_path, payload, timeout=10):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOOKCAP_TAG": "t", "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([sys.executable, str(KIT / "dispatcher.py")], input=json.dumps(payload),
                          text=True, env=env, capture_output=True, timeout=timeout)
    lines = (tmp_path / "dispatch-t.jsonl").read_text().splitlines()
    return proc, [json.loads(line) for line in lines]


def read_payload(name, event="PreToolUse", tool="Read"):
    return {"hook_event_name": event, "tool_name": tool, "session_id": "sess-1",
            "tool_use_id": "toolu_abc", "tool_input": {"file_path": f"/scratch/{name}"}}


@pytest.mark.parametrize("name,decision", [("allow.txt", "allow"), ("ask.txt", "ask"), ("forbidden.txt", "deny")])
def test_decision_routes(tmp_path, name, decision):
    proc, lines = run_dispatcher(tmp_path, read_payload(name))
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == decision
    assert [line["phase"] for line in lines] == ["enter", "exit"]
    assert lines[1]["decision"] == decision


def test_rewrite_keeps_the_other_inputs(tmp_path):
    payload = read_payload("rewrite.txt")
    payload["tool_input"]["limit"] = 5
    proc, _ = run_dispatcher(tmp_path, payload)
    updated = json.loads(proc.stdout)["hookSpecificOutput"]["updatedInput"]
    assert updated == {"file_path": "/scratch/rewrite-target.txt", "limit": 5}


def test_plain_read_decides_nothing(tmp_path):
    proc, lines = run_dispatcher(tmp_path, read_payload("plain-1.txt"))
    assert proc.returncode == 0 and proc.stdout == ""
    assert lines[1]["decision"] == "no-decision"


def test_post_tool_use_never_routes(tmp_path):
    """B1 from the architect review: slow.txt must not stall PostToolUse."""
    payload = read_payload("slow.txt", event="PostToolUse")
    payload["duration_ms"] = 12
    start = time.monotonic()
    proc, lines = run_dispatcher(tmp_path, payload)
    assert time.monotonic() - start < 5
    assert proc.stdout == "" and lines[0]["route"] == "no-decision"
    assert lines[0]["tool_duration_ms"] == 12


def test_crash_leaves_enter_only(tmp_path):
    proc, lines = run_dispatcher(tmp_path, read_payload("crash.txt"))
    assert proc.returncode == 1
    assert [line["phase"] for line in lines] == ["enter"]


def test_sigterm_during_sleep_logs_killed(tmp_path):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOOKCAP_TAG": "t", "PATH": "/usr/bin:/bin"}
    proc = subprocess.Popen([sys.executable, str(KIT / "dispatcher.py")], stdin=subprocess.PIPE, text=True, env=env)
    proc.stdin.write(json.dumps(read_payload("slow.txt")))
    proc.stdin.close()
    log = tmp_path / "dispatch-t.jsonl"
    deadline = time.monotonic() + 5
    while not (log.exists() and log.read_text()) and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)
    phases = [json.loads(line) for line in log.read_text().splitlines()]
    assert [p["phase"] for p in phases] == ["enter", "killed"]
    assert phases[1]["signal"] == "SIGTERM"


def test_log_never_carries_tool_input(tmp_path):
    payload = read_payload("forbidden.txt")
    payload["tool_input"]["file_path"] = "/home/CANARYUSER/forbidden.txt"
    _, lines = run_dispatcher(tmp_path, payload)
    assert "CANARY" not in (tmp_path / "dispatch-t.jsonl").read_text()
    assert all("tool_input" not in line for line in lines)


def test_parallel_appends_are_whole_lines(tmp_path):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOOKCAP_TAG": "t", "PATH": "/usr/bin:/bin"}
    procs = [subprocess.Popen([sys.executable, str(KIT / "dispatcher.py")], stdin=subprocess.PIPE, text=True, env=env)
             for _ in range(16)]
    for p in procs:
        p.stdin.write(json.dumps(read_payload("plain-1.txt")))
        p.stdin.close()
    for p in procs:
        p.wait(timeout=10)
    lines = (tmp_path / "dispatch-t.jsonl").read_text().splitlines()
    assert len(lines) == 32
    assert all(json.loads(line) for line in lines)


# --- http guard --------------------------------------------------------------


@pytest.fixture
def guard(tmp_path, request):
    mode = request.param
    server = ThreadingHTTPServer(("127.0.0.1", 0), http_guard.make_handler(mode, tmp_path / "g.jsonl"))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/pre", tmp_path / "g.jsonl"
    server.shutdown()


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.read()


@pytest.mark.parametrize("guard", ["up"], indirect=True)
def test_guard_denies_only_the_http_sentinels(guard):
    url, log = guard
    status, body = post(url, read_payload("forbidden-http-3.txt"))
    assert status == 200 and json.loads(body)["hookSpecificOutput"]["permissionDecision"] == "deny"
    status, body = post(url, read_payload("plain-1.txt"))
    assert status == 200 and body == b""
    # The guard logs after it answers, so the second line can trail the response.
    deadline = time.monotonic() + 5
    while len(log.read_text().splitlines()) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["sentinel"] for r in records] == ["forbidden-http-3.txt", None]


@pytest.mark.parametrize("guard", ["500"], indirect=True)
def test_guard_500_mode(guard):
    url, _ = guard
    with pytest.raises(urllib.error.HTTPError) as err:
        post(url, read_payload("forbidden-http-3.txt"))
    assert err.value.code == 500


# --- judge -------------------------------------------------------------------


def test_judge_prompt_matches_the_prompt_hook():
    settings = json.loads((KIT / "settings-s3.json").read_text())
    hooks = settings["hooks"]["PreToolUse"][0]["hooks"]
    prompt_hook = next(h for h in hooks if h["type"] == "prompt")
    assert prompt_hook["prompt"] == judge_client.PROMPT
    assert prompt_hook["model"] == judge_client.MODEL


def test_judge_ignores_other_tools(tmp_path):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOOKCAP_TAG": "t", "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([sys.executable, str(KIT / "judge_client.py")], input=json.dumps(read_payload("x.txt")),
                          text=True, env=env, capture_output=True, timeout=10)
    assert proc.returncode == 0 and proc.stdout == ""
    assert not (tmp_path / "judge-t.jsonl").exists()


def test_settings_timeouts_cover_both_dispatcher_entries():
    settings = json.loads((KIT / "settings-s1.json").read_text())
    for event in ("PreToolUse", "PostToolUse"):
        assert settings["hooks"][event][0]["hooks"][0]["timeout"] == 5
