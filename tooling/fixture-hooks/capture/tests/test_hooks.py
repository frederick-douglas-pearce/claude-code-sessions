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

import dispatcher
import http_guard
import judge_client


def run_dispatcher(tmp_path, payload, timeout=10, args=()):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOOKCAP_TAG": "t", "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([sys.executable, str(KIT / "dispatcher.py"), *args], input=json.dumps(payload),
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


# --- #303 fail-closed routes -------------------------------------------------

S4 = ("--set", "s4")


def decision_of(proc):
    return json.loads(proc.stdout)["hookSpecificOutput"]


@pytest.mark.parametrize("name,label,phrase", [
    ("raise-closed.txt", "deny-on-exception", "the check raised"),
    ("deadline-closed.txt", "deny-on-deadline", "missed its internal deadline"),
])
def test_fail_closed_routes_deny(tmp_path, name, label, phrase):
    start = time.monotonic()
    proc, lines = run_dispatcher(tmp_path, read_payload(name), args=S4)
    elapsed = time.monotonic() - start
    out = decision_of(proc)
    assert proc.returncode == 0
    assert out["permissionDecision"] == "deny" and phrase in out["permissionDecisionReason"]
    assert lines[1]["decision"] == label and lines[0]["route_set"] == "s4"
    # The deadline route must answer well inside the 5 s hook timeout.
    assert elapsed < 4.5


def test_exit2_blocks_with_stderr_and_no_json(tmp_path):
    proc, lines = run_dispatcher(tmp_path, read_payload("exit2.txt"), args=S4)
    assert proc.returncode == 2 and proc.stdout == ""
    assert "exit code 2" in proc.stderr
    assert [line["phase"] for line in lines] == ["enter", "exit"] and lines[1]["exit_code"] == 2


def test_badschema_is_json_with_an_invalid_decision(tmp_path):
    proc, _ = run_dispatcher(tmp_path, read_payload("badschema.txt"), args=S4)
    assert proc.returncode == 0 and decision_of(proc)["permissionDecision"] == "maybe"


def test_rewrite_unknown_key_swaps_the_path_and_adds_a_key(tmp_path):
    proc, _ = run_dispatcher(tmp_path, read_payload("rewrite-unknown-key.txt"), args=S4)
    updated = decision_of(proc)["updatedInput"]
    assert updated == {"file_path": "/scratch/rewrite-target.txt", "hookcap_extra": "unknown key"}


def test_rewrite_invalid_sets_a_limit_read_rejects(tmp_path):
    proc, _ = run_dispatcher(tmp_path, read_payload("rewrite-invalid.txt"), args=S4)
    assert decision_of(proc)["updatedInput"] == {"file_path": "/scratch/rewrite-invalid.txt", "limit": "ten"}


@pytest.mark.parametrize("args,name,route", [
    ((), "crash-open.txt", "no-decision"),            # s1 does not route it
    (("--set", "s4-open"), "crash-open.txt", "crash"),
    (("--set", "s4-open"), "crash.txt", "no-decision"),
    (S4, "crash-open.txt", "no-decision"),            # the block-on-failure handler ignores the control's file
    (S4, "allow.txt", "no-decision"),                 # s4 drops the s1-only routes
    (("--set", "bogus"), "allow.txt", "allow"),       # an unknown set falls back to s1
])
def test_route_sets_are_disjoint_where_they_must_be(tmp_path, args, name, route):
    _, lines = run_dispatcher(tmp_path, read_payload(name), args=args)
    assert lines[0]["route"] == route


def test_killswitch_allows_even_a_deny_route_and_logs_why(tmp_path):
    (tmp_path / ".hookcap-off").write_text("")
    proc, lines = run_dispatcher(tmp_path, read_payload("forbidden.txt"), args=S4)
    assert proc.returncode == 0 and proc.stdout == ""
    assert lines[0]["route"] == "killswitch" and lines[1]["decision"] == "no-decision"


def test_s4_settings_wire_the_cases():
    settings = json.loads((KIT / "settings-s4.json").read_text())
    pre = settings["hooks"]["PreToolUse"][0]["hooks"]
    main = pre[0]
    assert "--set s4" in main["command"] and main["onFailure"] == "block" and "if" not in main
    by_if = {h["if"]: h for h in pre[1:]}
    assert set(by_if) == {"Read(./crash-open.txt)", "Read(./missing-script.txt)",
                          "Read(./missing-exe.txt)", "Read(./missing-exe-block.txt)"}
    assert "onFailure" not in by_if["Read(./crash-open.txt)"]
    assert "onFailure" not in by_if["Read(./missing-script.txt)"]
    assert "onFailure" not in by_if["Read(./missing-exe.txt)"]
    assert by_if["Read(./missing-exe-block.txt)"]["onFailure"] == "block"
    # The missing scripts must stay missing.
    assert not (KIT / "no-such-hook.py").exists() and not (KIT / "no-such-hook.sh").exists()


def test_s5_settings_wire_the_cases():
    settings = json.loads((KIT / "settings-s5.json").read_text())
    pre = {h["if"]: h for h in settings["hooks"]["PreToolUse"][0]["hooks"]}
    assert pre["Read(./svc-*.txt)"]["type"] == "http" and pre["Read(./svc-*.txt)"]["onFailure"] == "block"
    assert pre["Read(./prompt-control.txt)"]["timeout"] == 30
    assert pre["Read(./prompt-timeout.txt)"]["timeout"] == 1
    assert pre["Read(./prompt-control.txt)"]["prompt"] == pre["Read(./prompt-timeout.txt)"]["prompt"]


def test_every_routed_file_has_a_sentinel():
    script = (KIT / "make-sentinels.sh").read_text()
    for routes in dispatcher.ROUTE_SETS.values():
        for name in routes:
            assert name in script, name


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
