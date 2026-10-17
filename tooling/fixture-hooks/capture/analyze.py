#!/usr/bin/env python3
"""Content-free report over one #295 capture session.

Reads, from the scratch project directory, whatever exists for one tag:

  dispatch-<tag>.jsonl     dispatcher.py's enter/exit/killed lines
  otel-<tag>.jsonl         otlp_sink.py's allowlisted telemetry
  http-guard-<tag>.jsonl   http_guard.py's request log
  judge-<tag>.jsonl        judge_client.py's usage log
  debug-<tag>.log          Claude Code's --debug-file output (RAW)

and optionally one or more SANITIZED session files (--session). It joins them
and prints markdown tables.

SECURITY CONTRACT. The debug log is raw: hook command lines carry the home
directory, and hook stdout is logged verbatim. This script reads only the
`Hooks:` lines and the `[3P telemetry]` tag from it, and emits from those only
the event, a tool name, a script name from a closed list, the outcome and the
duration. Every string this script prints is an id, a number, or a value from a
closed vocabulary; anything else is printed as `<other>`. Planted-canary tests
in tests/test_contract.py hold it to that.

It refuses a --session path under ~/.claude/projects: raw session JSONL goes
through ccs-sanitize first.
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

KNOWN_SCRIPTS = frozenset(
    {"dispatcher.py", "judge_client.py", "block_secret_reads.py", "detect_secrets_in_output.py",
     "no-such-hook.py", "no-such-hook.sh"}
)
SENTINELS = frozenset(
    {
        "plain-1.txt", "p1.txt", "p2.txt", "p3.txt", "p4.txt", "explore.txt",
        "allow.txt", "ask.txt", "rewrite.txt", "rewrite-target.txt", "forbidden.txt",
        "denied-by-rule.txt", "slow.txt", "crash.txt",
        *(f"forbidden-http-{i}.txt" for i in range(1, 6)),
        # #303
        "forbidden-2.txt", "crash-open.txt", "badschema.txt", "raise-closed.txt", "deadline-closed.txt", "exit2.txt",
        "rewrite-unknown-key.txt", "rewrite-invalid.txt",
        "missing-script.txt", "missing-exe.txt", "missing-exe-block.txt",
        *(f"svc-{i}.txt" for i in range(1, 5)),
        "prompt-control.txt", "prompt-timeout.txt",
    }
)
WORD = re.compile(r"^[A-Za-z*][A-Za-z0-9_.:*\-]*$")

DEBUG_LINE = re.compile(r"^(?P<ts>\d{4}-\d\d-\d\dT[\d:.]+Z)\s+\[\w+\]\s+(?P<msg>.*)$")
HOOKS_MSG = re.compile(
    r"Hooks: (?P<event>[A-Za-z]+)(?::(?P<target>[^\s\[]*))? \[(?P<cmd>.*?)\](?P<rest>.*)$"
)
OUTCOME = re.compile(
    r"(?P<outcome>finished with status (?P<status>-?\d+)|completed with status (?P<cstatus>-?\d+)"
    r"|timed out after (?P<timeout>\d+)ms|cancelled|moved to the background|failed to start)"
)
DURATION = re.compile(r"\((?P<ms>\d+)ms\)\s*$")
SCRIPT = re.compile(r"([\w.-]+\.(?:py|sh|js|ts))")


# --- helpers -----------------------------------------------------------------


def word(value) -> str:
    """A value from a closed vocabulary, or <other>."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    return value if isinstance(value, str) and WORD.match(value) and len(value) <= 64 else "<other>"


def tail(identifier) -> str:
    """The last 8 characters of an opaque id."""
    if not isinstance(identifier, str) or not re.match(r"^[A-Za-z0-9_\-]+$", identifier):
        return "-"
    return "…" + identifier[-8:]


def num(value) -> str:
    if isinstance(value, bool) or value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:g}" if isinstance(value, float) else str(value)
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "-"


def stats(values) -> str:
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return "n=0"
    p90 = values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]
    return (
        f"n={len(values)} median={statistics.median(values):.1f} p90={p90:.1f} "
        f"min={values[0]:.1f} max={values[-1]:.1f} (ms)"
    )


def table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def load_jsonl(path: Path):
    records, bad = [], 0
    if not path.exists():
        return None, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return records, bad


def iso_ms(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000


# --- debug log ---------------------------------------------------------------


def parse_debug(path: Path):
    """Return (hook lines, unparsed Hooks: line count, [3P telemetry] count)."""
    if not path.exists():
        return None, 0, 0
    hooks, unparsed, telemetry_errors = [], 0, 0
    with path.open(errors="replace") as fh:
        for line in fh:
            if "[3P telemetry]" in line:
                telemetry_errors += 1
            if "Hooks: " not in line:
                continue
            outer = DEBUG_LINE.match(line.rstrip("\n"))
            inner = HOOKS_MSG.search(outer.group("msg")) if outer else None
            outcome = OUTCOME.search(inner.group("rest")) if inner else None
            if not outcome:
                unparsed += 1
                continue
            scripts = [s for s in SCRIPT.findall(inner.group("cmd")) if s in KNOWN_SCRIPTS]
            text = outcome.group("outcome")
            if outcome.group("status") is not None:
                kind, status = "finished", int(outcome.group("status"))
            elif outcome.group("cstatus") is not None:
                kind, status = "completed", int(outcome.group("cstatus"))
            elif outcome.group("timeout") is not None:
                kind, status = "timed-out", None
            else:
                kind, status = text.replace(" ", "-"), None
            duration = DURATION.search(inner.group("rest"))
            hooks.append(
                {
                    "ts_ms": iso_ms(outer.group("ts")),
                    "event": word(inner.group("event")),
                    "target": word(inner.group("target")) if inner.group("target") else "-",
                    "script": scripts[-1] if scripts else "<other>",
                    "outcome": kind,
                    "status": status,
                    "timeout_ms": int(outcome.group("timeout")) if outcome.group("timeout") else None,
                    "ms": int(duration.group("ms")) if duration else None,
                }
            )
    return hooks, unparsed, telemetry_errors


# --- dispatcher --------------------------------------------------------------


def firings_from(records):
    """Group dispatcher lines by pid into one firing each."""
    by_pid = {}
    for rec in records:
        firing = by_pid.setdefault(rec.get("pid"), {"phases": []})
        firing["phases"].append(rec.get("phase"))
        for key in ("session_id", "tool_use_id", "agent_id", "agent_type", "event", "tool", "route"):
            firing.setdefault(key, rec.get(key))
        if rec.get("phase") == "enter":
            firing["start_ms"] = rec.get("ts_ms")
        else:
            firing["end_ms"] = rec.get("ts_ms")
            firing["duration_ms"] = rec.get("duration_ms")
            firing["decision"] = rec.get("decision", firing.get("decision"))
            firing["exit_code"] = rec.get("exit_code")
            firing["signal"] = rec.get("signal")
    firings = sorted(by_pid.values(), key=lambda f: f.get("start_ms") or 0)
    for f in firings:
        f["overlaps"] = False
    for i, a in enumerate(firings):
        for b in firings[i + 1:]:
            a_end = a.get("end_ms") or a.get("start_ms")
            if b.get("start_ms") is not None and a_end is not None and b["start_ms"] <= a_end:
                a["overlaps"] = b["overlaps"] = True
    return firings


def match_debug(firings, hooks):
    """Attach each non-overlapping firing to the debug line that closed it."""
    if not hooks:
        return
    used = set()
    for f in firings:
        end = f.get("end_ms") or f.get("start_ms")
        if f["overlaps"] or end is None:
            continue
        best = None
        for i, h in enumerate(hooks):
            if i in used or h["script"] != "dispatcher.py" or h["event"] != f.get("event"):
                continue
            if h["target"] not in ("-", f.get("tool")):
                continue
            delta = h["ts_ms"] - end
            # The debug line is written after the process exits, a little after
            # the dispatcher's own last line; a killed hook may log first.
            if -200 <= delta <= 6000 and (best is None or abs(delta) < abs(best[1])):
                best = (i, delta)
        if best:
            used.add(best[0])
            f["debug"] = hooks[best[0]]


def report_dispatcher(firings, bad, hooks) -> list:
    out = ["## Dispatcher", ""]
    out.append(f"Lines that failed to parse (torn appends): **{bad}**")
    pre = [f for f in firings if f.get("event") == "PreToolUse"]
    post = [f for f in firings if f.get("event") == "PostToolUse"]
    post_ids = {f.get("tool_use_id") for f in post if "exit" in f["phases"]}
    silent = [
        f for f in pre
        if f.get("route") == "no-decision" and f.get("decision") == "no-decision"
        and f.get("tool_use_id") in post_ids
    ]
    out.append(
        f"PreToolUse firings: **{len(pre)}**; explicit decisions: "
        f"**{sum(1 for f in pre if f.get('decision') not in (None, 'no-decision', 'error'))}**; "
        f"silent allows (no-decision exit whose tool_use_id reached a PostToolUse exit): **{len(silent)}**"
    )
    out.append(
        f"Firings overlapping another firing: PreToolUse **{sum(f['overlaps'] for f in pre)}**, "
        f"PostToolUse **{sum(f['overlaps'] for f in post)}**"
    )
    out.append(f"Firings carrying agent_id: **{sum(1 for f in firings if f.get('agent_id'))}**")
    out.append("")

    counts = {}
    for f in firings:
        key = (word(f.get("event")), word(f.get("tool")), word(f.get("route")),
               "+".join(f["phases"]), word(f.get("decision")), word(f.get("signal")))
        counts[key] = counts.get(key, 0) + 1
    out.append(table(["event", "tool", "route", "phases", "decision", "signal", "count"],
                     [(*k, v) for k, v in sorted(counts.items())]))
    out.append("")

    if hooks is not None:
        overhead = [f["debug"]["ms"] - f["duration_ms"] for f in firings
                    if f.get("debug") and f["debug"]["ms"] is not None and f.get("duration_ms") is not None]
        inside = [f["duration_ms"] for f in firings if f.get("debug") and f.get("duration_ms") is not None]
        outside = [f["debug"]["ms"] for f in firings if f.get("debug") and f["debug"]["ms"] is not None]
        out.append("### Overhead (non-overlapping firings matched to a debug `Hooks:` line)")
        out.append("")
        out.append(f"- in-script duration: {stats(inside)}")
        out.append(f"- debug-log duration: {stats(outside)}")
        out.append(f"- process-start overhead (debug minus in-script): {stats(overhead)}")
        out.append("")
    return out


# --- telemetry ---------------------------------------------------------------


def seq(rec):
    value = rec.get("attrs", {}).get("event.sequence")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def report_telemetry(otel, bad, firings) -> list:
    out = ["## Telemetry", "", f"Lines that failed to parse: **{bad}**", ""]
    logs = sorted((r for r in otel if r.get("signal") == "log"), key=lambda r: (seq(r) is None, seq(r) or 0))
    metrics = [r for r in otel if r.get("signal") == "metric"]
    spans = [r for r in otel if r.get("signal") == "span"]

    counts = {}
    for r in otel:
        name = r.get("body") if r.get("signal") == "log" else r.get("name")
        key = (r.get("signal"), word(name) if isinstance(name, str) else "<other>", word(r.get("path")))
        counts[key] = counts.get(key, 0) + 1
    out.append(table(["signal", "name", "path", "count"], [(*k, v) for k, v in sorted(counts.items())]))
    out.append("")

    redacted = sorted({name for r in otel for name, v in r.get("attrs", {}).items()
                       if isinstance(v, dict) and v.get("redacted")})
    out.append("Attributes seen but not allowlisted (values dropped by the sink): "
               + (", ".join(word(n) for n in redacted) or "none"))
    out.append("")

    def attrs_of(name):
        return [r for r in logs if r.get("body") == f"claude_code.{name}"]

    reg = attrs_of("hook_registered")
    out.append("### hook_registered")
    out.append("")
    out.append(table(["hook_event", "hook_type", "hook_source", "hook_matcher"],
                     [(word(a.get("hook_event")), word(a.get("hook_type")), word(a.get("hook_source")),
                       word(a.get("hook_matcher")))
                      for a in (r["attrs"] for r in reg)]) if reg else "none")
    out.append("")

    completes = attrs_of("hook_execution_complete")
    out.append("### hook_execution_complete")
    out.append("")
    cols = ["num_hooks", "num_success", "num_blocking", "num_non_blocking_error", "num_cancelled",
            "total_duration_ms", "stdout_chars", "additional_context_chars"]
    out.append(table(["seq", "hook_name", *cols],
                     [(num(seq(r)), word(r["attrs"].get("hook_name")), *(num(r["attrs"].get(c)) for c in cols))
                      for r in completes]) if completes else "none")
    out.append("")

    # tool_decision joined back to the preceding PreToolUse completion and to the dispatcher.
    route_by_id = {f.get("tool_use_id"): f for f in firings if f.get("event") == "PreToolUse"}
    decisions = attrs_of("tool_decision")
    rows = []
    for td in decisions:
        a, s = td["attrs"], seq(td)
        prior = [c for c in completes if c["attrs"].get("hook_event") == "PreToolUse"
                 and s is not None and seq(c) is not None and seq(c) < s]
        hc = prior[-1]["attrs"] if prior else {}
        f = route_by_id.get(a.get("tool_use_id"), {})
        rows.append((num(s), tail(a.get("tool_use_id")), word(a.get("tool_name")), word(f.get("route")),
                     word(f.get("decision")), word(a.get("decision")), word(a.get("source")),
                     num(seq(prior[-1])) if prior else "-",
                     num(hc.get("num_blocking")), num(hc.get("num_non_blocking_error")), num(hc.get("num_cancelled"))))
    out.append("### tool_decision, joined")
    out.append("")
    out.append("The completion column is the nearest preceding PreToolUse `hook_execution_complete` by "
               "`event.sequence`. Check it by eye when calls ran in parallel.")
    out.append("")
    out.append(table(["seq", "tool_use_id", "tool", "dispatcher route", "dispatcher decision", "decision",
                      "source", "completion seq", "num_blocking", "num_non_blocking_error", "num_cancelled"],
                     rows) if rows else "none")
    out.append("")

    results = attrs_of("tool_result")
    out.append("### tool_result")
    out.append("")
    out.append(table(["seq", "tool_use_id", "tool", "success", "decision_source", "duration_ms"],
                     [(num(seq(r)), tail(r["attrs"].get("tool_use_id")), word(r["attrs"].get("tool_name")),
                       word(r["attrs"].get("success")), word(r["attrs"].get("decision_source")),
                       num(r["attrs"].get("duration_ms"))) for r in results]) if results else "none")
    out.append("")

    # api_request events inside a hook's start/complete bracket.
    starts = attrs_of("hook_execution_start")
    api = attrs_of("api_request")
    bracket_rows = []
    for st in starts:
        s0 = seq(st)
        end = next((c for c in completes if seq(c) is not None and s0 is not None and seq(c) > s0
                    and c["attrs"].get("hook_name") == st["attrs"].get("hook_name")), None)
        if end is None:
            continue
        for r in api:
            if s0 < (seq(r) or -1) < seq(end):
                a = r["attrs"]
                bracket_rows.append((word(st["attrs"].get("hook_name")), num(s0), num(seq(end)), num(seq(r)),
                                     word(a.get("query_source")), word(a.get("model")), word(a.get("agent.name")),
                                     num(a.get("input_tokens")), num(a.get("output_tokens")),
                                     num(a.get("cache_read_tokens")), num(a.get("cache_creation_tokens")),
                                     num(a.get("cost_usd"))))
    out.append("### api_request inside a hook bracket")
    out.append("")
    out.append(table(["hook_name", "start seq", "complete seq", "api seq", "query_source", "model", "agent.name",
                      "input", "output", "cache_read", "cache_creation", "cost_usd"], bracket_rows)
               if bracket_rows else "none")
    out.append("")

    totals = {}
    for r in api:
        a = r["attrs"]
        key = (word(a.get("query_source")), word(a.get("model")), word(a.get("agent.name")))
        t = totals.setdefault(key, [0, 0, 0, 0, 0, 0.0])
        t[0] += 1
        for i, name in enumerate(("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"), 1):
            try:
                t[i] += int(a.get(name) or 0)
            except (TypeError, ValueError):
                pass
        try:
            t[5] += float(a.get("cost_usd") or 0)
        except (TypeError, ValueError):
            pass
    out.append("### api_request totals")
    out.append("")
    out.append(table(["query_source", "model", "agent.name", "requests", "input", "output", "cache_read",
                      "cache_creation", "cost_usd"],
                     [(*k, *v[:5], f"{v[5]:.6f}") for k, v in sorted(totals.items())]) if totals else "none")
    out.append("")

    # Metrics: delta (1) points are summed, cumulative (2) take the latest value.
    series = {}
    for m in metrics:
        a = m.get("attrs", {})
        key = (word(m.get("name")) if isinstance(m.get("name"), str) else "<other>",
               word(a.get("query_source")), word(a.get("type")), word(a.get("model")), word(a.get("agent.name")))
        value = m.get("value")
        if isinstance(value, dict):
            value = value.get("sum")
        if not isinstance(value, (int, float)):
            continue
        entry = series.setdefault(key, {"delta": 0.0, "latest": (0, 0.0), "temporality": m.get("temporality")})
        if m.get("temporality") == 1:
            entry["delta"] += value
        else:
            stamp = int(m.get("time_unix_nano") or 0)
            if stamp >= entry["latest"][0]:
                entry["latest"] = (stamp, value)
    out.append("### Metrics")
    out.append("")
    out.append(table(["metric", "query_source", "type", "model", "agent.name", "temporality", "value"],
                     [(*k, num(v["temporality"]),
                       f"{(v['delta'] if v['temporality'] == 1 else v['latest'][1]):g}")
                      for k, v in sorted(series.items())]) if series else "none")
    out.append("")

    if spans:
        names = {}
        for s in spans:
            name = word(s.get("name")) if isinstance(s.get("name"), str) else "<other>"
            names[name] = names.get(name, 0) + 1
        out.append("### Spans")
        out.append("")
        out.append(table(["span", "count"], sorted(names.items())))
        out.append("")
    return out


# --- http guard, judge, session ---------------------------------------------


def report_http(records, bad, hooks) -> list:
    out = ["## HTTP guard", "", f"Lines that failed to parse: **{bad}**", ""]
    out.append(table(["recv_ms", "mode", "sentinel", "tool_use_id", "status", "decision", "delivered", "held_ms"],
                     [(num(r.get("recv_ms")), word(r.get("mode")),
                       r.get("sentinel") if r.get("sentinel") in SENTINELS else "-",
                       tail(r.get("tool_use_id")), num(r.get("status")), word(r.get("decision")),
                       word(r.get("delivered")),
                       num(round(r["sent_ms"] - r["recv_ms"], 1)) if r.get("sent_ms") and r.get("recv_ms") else "-")
                      for r in records]))
    out.append("")
    if hooks is not None:
        http_lines = [h for h in hooks if h["script"] == "<other>" and h["event"] == "PreToolUse"]
        out.append(f"Debug `Hooks:` lines for PreToolUse with no known script (candidate http-hook lines): "
                   f"**{len(http_lines)}**")
        out.append("")
    return out


def report_judge(records, bad) -> list:
    out = ["## Judge client", "", f"Lines that failed to parse: **{bad}**", ""]
    rows = []
    for r in records:
        u = r.get("usage") or {}
        rows.append((tail(r.get("tool_use_id")), word(r.get("decision")), word(r.get("ok")), word(r.get("stop_reason")),
                     word(r.get("error")), num(u.get("input_tokens")), num(u.get("output_tokens")),
                     num(u.get("cache_read_input_tokens")), num(u.get("cache_creation_input_tokens")),
                     num(r.get("import_ms")), num(r.get("api_ms")), num(r.get("total_ms"))))
    out.append(table(["tool_use_id", "decision", "ok", "stop_reason", "error", "input", "output", "cache_read",
                      "cache_creation", "import_ms", "api_ms", "total_ms"], rows))
    out.append("")
    return out


def sentinel(path) -> str:
    if not isinstance(path, str):
        return "-"
    name = Path(path).name
    return name if name in SENTINELS else "<other>"


def report_session(path: Path) -> list:
    out = [f"## Sanitized session: {word(path.name)}", ""]
    types, subtypes, denial_kinds = {}, {}, {}
    uses, results = {}, {}
    hook_keys = {k: 0 for k in ("hookInfos", "hookErrors", "hookCount", "toolDenialKind")}
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        types[word(rec.get("type"))] = types.get(word(rec.get("type")), 0) + 1
        if rec.get("subtype"):
            subtypes[word(rec.get("subtype"))] = subtypes.get(word(rec.get("subtype")), 0) + 1
        for key in hook_keys:
            if key in rec:
                hook_keys[key] += 1
        if rec.get("toolDenialKind"):
            kind = word(rec.get("toolDenialKind"))
            denial_kinds[kind] = denial_kinds.get(kind, 0) + 1
        content = (rec.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses[block.get("id")] = (word(block.get("name")), sentinel((block.get("input") or {}).get("file_path")))
            elif block.get("type") == "tool_result":
                result = rec.get("toolUseResult")
                read_path = (result.get("file") or {}).get("filePath") if isinstance(result, dict) else None
                pd = rec.get("permissionDecision") if isinstance(rec.get("permissionDecision"), dict) else {}
                results[block.get("tool_use_id")] = (word(block.get("is_error")), sentinel(read_path),
                                                     word(rec.get("toolDenialKind")),
                                                     "/".join(word(pd.get(k)) for k in ("decision", "source", "reasonType"))
                                                     if pd else "-")
    out.append(table(["type", "lines"], sorted(types.items())))
    out.append("")
    out.append("system subtypes: " + (", ".join(f"{k}={v}" for k, v in sorted(subtypes.items())) or "none"))
    out.append("hook-related keys (lines carrying each): " + ", ".join(f"{k}={v}" for k, v in hook_keys.items()))
    out.append("toolDenialKind values: " + (", ".join(f"{k}={v}" for k, v in sorted(denial_kinds.items())) or "none"))
    out.append("")
    out.append(table(["tool_use_id", "tool", "input file", "is_error", "file actually read", "toolDenialKind",
                      "permissionDecision"],
                     [(tail(i), *uses[i], *results.get(i, ("-", "-", "-", "-"))) for i in uses]))
    out.append("")
    return out


# --- baseline ----------------------------------------------------------------


def baseline(runs: int = 20) -> list:
    here = Path(__file__).resolve().parent
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Read",
                          "tool_input": {"file_path": "/tmp/plain-1.txt"}, "tool_use_id": "toolu_baseline"})
    bare, disp = [], []
    with tempfile.TemporaryDirectory() as tmp:
        env = {"CLAUDE_PROJECT_DIR": tmp, "HOOKCAP_TAG": "baseline", "PATH": "/usr/bin:/bin"}
        for _ in range(runs):
            t = time.monotonic()
            subprocess.run([sys.executable, "-c", "pass"], check=True)
            bare.append((time.monotonic() - t) * 1000)
            t = time.monotonic()
            subprocess.run([sys.executable, str(here / "dispatcher.py")], input=payload, text=True,
                           env=env, check=True, capture_output=True)
            disp.append((time.monotonic() - t) * 1000)
    return ["## Baseline", "", f"- `python -c pass`: {stats(bare)}",
            f"- dispatcher, no-decision payload: {stats(disp)}", ""]


# --- main --------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=".", help="the scratch project directory")
    parser.add_argument("--tag", help="session tag, e.g. s1")
    parser.add_argument("--session", action="append", default=[], help="a SANITIZED session file; repeatable")
    parser.add_argument("--baseline", action="store_true", help="time interpreter and dispatcher start-up")
    args = parser.parse_args(argv)

    projects = (Path.home() / ".claude" / "projects").resolve()
    for s in args.session:
        resolved = Path(s).expanduser().resolve()
        if resolved == projects or projects in resolved.parents:
            print("analyze: refusing a raw session file; run ccs-sanitize first", file=sys.stderr)
            return 2

    out = []
    if args.tag:
        d = Path(args.dir)
        hooks, unparsed, telemetry_errors = parse_debug(d / f"debug-{args.tag}.log")
        out += [f"# Capture report: {word(args.tag)}", ""]
        if hooks is not None:
            out.append(f"Debug log: **{len(hooks)}** `Hooks:` lines parsed, **{unparsed}** unparsed, "
                       f"**{telemetry_errors}** `[3P telemetry]` lines")
            out.append("")
            counts = {}
            for h in hooks:
                key = (h["event"], h["target"], h["script"], h["outcome"], num(h["status"]), num(h["timeout_ms"]))
                counts[key] = counts.get(key, 0) + 1
            out.append(table(["event", "target", "script", "outcome", "status", "timeout_ms", "count"],
                             [(*k, v) for k, v in sorted(counts.items())]))
            out.append("")
        dispatch, bad = load_jsonl(d / f"dispatch-{args.tag}.jsonl")
        firings = firings_from(dispatch) if dispatch else []
        if dispatch is not None:
            match_debug(firings, hooks)
            out += report_dispatcher(firings, bad, hooks)
        otel, bad = load_jsonl(d / f"otel-{args.tag}.jsonl")
        if otel is not None:
            out += report_telemetry(otel, bad, firings)
        guard, bad = load_jsonl(d / f"http-guard-{args.tag}.jsonl")
        if guard is not None:
            out += report_http(guard, bad, hooks)
        judge, bad = load_jsonl(d / f"judge-{args.tag}.jsonl")
        if judge is not None:
            out += report_judge(judge, bad)
    for s in args.session:
        out += report_session(Path(s))
    if args.baseline:
        out += baseline()
    if not out:
        parser.print_help()
        return 1
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
