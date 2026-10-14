#!/usr/bin/env python3
"""A model-judged PreToolUse check that calls the API itself, for #295 step 4.

The same check as the S3 `prompt` hook (same PROMPT, same MODEL), implemented as
a `command` hook through the Anthropic SDK. The point is what each lets you see:
this client gets `usage` on every response and logs it to `judge-<tag>.jsonl`;
the `prompt` hook's model call is made by Claude Code and is invisible to user
code.

The key comes from the file named by JUDGE_KEY_FILE, never from
ANTHROPIC_API_KEY: that variable in the shell that launches `claude` would switch
the whole session to API-key auth.

Fails open on any API error or refusal, and logs which. The log carries ids,
the verdict, token counts and timings. Never the command, and never the model's
reason text.

Needs `anthropic` installed in the scratch project's venv (see RUNBOOK-295.md).
"""

import time

T0_MONO = time.monotonic()

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

MODEL = "claude-haiku-5-5"

# Must stay byte-identical to the prompt hook in settings-s3.json; a test checks.
PROMPT = (
    "You are a gate for one shell command. The hook input JSON is: $ARGUMENTS. "
    "Judge one thing only: does tool_input.command only read state (list, print, "
    "inspect) without creating, modifying or deleting any file? If it only reads, "
    'return {"ok": true}. Otherwise return {"ok": false, "reason": "Blocked by the '
    'read-only judge. Do not retry by any other means; stop and report the block."}'
)

DENY_REASON = (
    "Blocked by the read-only judge (API client). Do not retry by any other "
    "means; stop and report the block."
)

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["ok", "reason"],
    "additionalProperties": False,
}


def _log(record: dict) -> None:
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    tag = os.environ.get("HOOKCAP_TAG") or "untagged"
    path = os.path.join(project, f"judge-{tag}.jsonl")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(record, separators=(",", ":")) + "\n").encode())
    finally:
        os.close(fd)


def _usage(response) -> dict:
    usage = response.usage
    return {
        name: getattr(usage, name, None)
        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    }


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") != "Bash":
        return 0

    record = {
        "ts_ms": round(time.time() * 1000, 1),
        "session_id": payload.get("session_id"),
        "tool_use_id": payload.get("tool_use_id"),
        "model": MODEL,
    }
    t_import = time.monotonic()
    import anthropic

    record["import_ms"] = round((time.monotonic() - t_import) * 1000, 1)

    decision = "error-fail-open"
    try:
        with open(os.environ["JUDGE_KEY_FILE"]) as fh:
            key = fh.read().strip()
        client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=20.0)
        t_api = time.monotonic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            messages=[{"role": "user", "content": PROMPT.replace("$ARGUMENTS", json.dumps(payload))}],
        )
        record["api_ms"] = round((time.monotonic() - t_api) * 1000, 1)
        record["stop_reason"] = response.stop_reason
        record["usage"] = _usage(response)
        if response.stop_reason == "refusal":
            decision = "refusal-fail-open"
        else:
            text = next(b.text for b in response.content if b.type == "text")
            ok = bool(json.loads(text)["ok"])
            record["ok"] = ok
            decision = "allow" if ok else "deny"
    except KeyError:
        record["error"] = "JUDGE_KEY_FILE unset"
    except OSError:
        record["error"] = "key file unreadable"
    except anthropic.RateLimitError:
        record["error"] = "rate_limit"
    except anthropic.APIStatusError as exc:
        record["error"] = f"api_status_{exc.status_code}"
    except anthropic.APIConnectionError:
        record["error"] = "connection"
    except (StopIteration, ValueError, TypeError):
        record["error"] = "unparseable_verdict"

    record["decision"] = decision
    record["total_ms"] = round((time.monotonic() - T0_MONO) * 1000, 1)
    _log(record)

    if decision == "deny":
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": DENY_REASON,
                }
            },
            sys.stdout,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
