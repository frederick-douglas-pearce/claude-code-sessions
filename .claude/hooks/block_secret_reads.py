#!/usr/bin/env python3
"""PreToolUse hook: block reads of files likely to contain credentials, of
raw Claude Code session transcripts, and of the live sanitizer config.

Receives the PreToolUse event JSON on stdin. Denies the tool call when the
target file path (or Bash command argument) matches:

1. Known credential files: .env variants, shell rc files, SSH private keys,
   and named secrets files. (Checked for file tools, search tools, and Bash.)
2. Raw session JSONL under ~/.claude/projects/. (Checked for Read/Edit/
   NotebookEdit/Grep/Glob only — NOT Bash, so `tail -f`/`ls` demos and the
   sanitizer CLI still work.) This enforces this repo's posture: read sample
   data from fixtures/, never an unsanitized session transcript.
3. The live sanitizer config (.ccs-sanitize.yaml), which holds the literal
   PII strings to scrub. Checked for Read/Edit/NotebookEdit/Grep/Glob/Bash;
   Write is allowed so `ccs-sanitize --init` and rewrite-from-scratch
   iteration flows keep working. The .ccs-sanitize.example.yaml schema
   reference stays freely readable.

Emits a JSON decision on stdout and exits 0 (the modern pattern); exit 2
+ stderr is the legacy fallback but not used here.

Cross-platform: stdlib only, no shell dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import PurePath

# The BLOCKED_BASENAMES set and the CREDENTIAL_TOKEN_PATTERNS list must stay in
# sync — they express the same credential-file list in two matching contexts
# (exact basename vs. substring-in-command-or-pattern). Update both together.
BLOCKED_BASENAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".envrc",
        "credentials",
        "credentials.json",
        "secrets.yaml",
        "secrets.yml",
        "secrets.json",
        ".bashrc",
        ".bash_profile",
        ".profile",
        ".zshrc",
        ".zshenv",
        ".zprofile",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
    }
)

BLOCKED_SUFFIXES: frozenset[str] = frozenset({".pem"})

CREDENTIAL_TOKEN_PATTERNS: list[str] = [
    r"\.env(\b|[._-][A-Za-z0-9_-]+)",
    r"\.envrc\b",
    r"credentials\.json\b",
    r"secrets\.ya?ml\b",
    r"secrets\.json\b",
    r"\.bashrc\b",
    r"\.bash_profile\b",
    r"\.profile\b",
    r"\.zshrc\b",
    r"\.zshenv\b",
    r"\.zprofile\b",
    r"\bid_rsa\b",
    r"\bid_ed25519\b",
    r"\bid_ecdsa\b",
    r"\bid_dsa\b",
    r"\.pem\b",
]
CREDENTIAL_TOKEN_REGEX = re.compile("|".join(CREDENTIAL_TOKEN_PATTERNS), re.IGNORECASE)

FILE_PATH_TOOLS = {"Read", "Edit", "MultiEdit", "Write", "NotebookEdit"}
PATH_SEARCH_TOOLS = {"Grep", "Glob"}

# Content-surfacing block applies to the tools that pull file *contents* into
# context. Write is excluded (it overwrites, it doesn't surface existing content)
# and Bash is excluded by design (keeps `tail -f`/`ls` and the sanitizer CLI
# usable). MultiEdit is in scope because it surfaces every `old_string` it
# searches for — same leak vector as Edit, multiplied.
CONTENT_SURFACING_FILE_TOOLS = {"Read", "Edit", "MultiEdit", "NotebookEdit"}
# Backwards-compat alias for the original raw-session-focused name. Both names
# share the same set today; if the two policies ever need to diverge, split
# them here rather than letting a rename of one silently change the other.
RAW_SESSION_FILE_TOOLS = CONTENT_SURFACING_FILE_TOOLS
SANITIZER_CONFIG_FILE_TOOLS = CONTENT_SURFACING_FILE_TOOLS

# ~/.claude/projects/ is where Claude Code writes raw, unsanitized session
# transcripts. Anything ending in .jsonl under that root is a raw session.
RAW_SESSION_ROOT = PurePath(os.path.expanduser("~")) / ".claude" / "projects"

# The live sanitizer config holds the literal PII strings to scrub (real home
# dir, email, name, GitHub handle). Reading it surfaces the very data the
# sanitizer is meant to remove. Pattern is anchored to .ccs-sanitize.yaml so
# the committed .ccs-sanitize.example.yaml schema reference stays readable.
SANITIZER_CONFIG_BASENAME = ".ccs-sanitize.yaml"
SANITIZER_CONFIG_TOKEN_REGEX = re.compile(r"\.ccs-sanitize\.yaml\b", re.IGNORECASE)

DENY_REASON = (
    "Blocked by claude-code-sessions secrets-protection hook (.claude/hooks/block_secret_reads.py). "
    "This file is a likely credential source (.env, shell rc, SSH key, or named secrets file). "
    "Reading it would persist its contents in the Claude Code session JSONL. "
    "If you need to verify the file exists, use `test -f <path>`. "
    "See CLAUDE.md (Security posture) and .claude/hooks/README.md for the full policy."
)

RAW_SESSION_DENY_REASON = (
    "Blocked by claude-code-sessions secrets-protection hook (.claude/hooks/block_secret_reads.py). "
    "This is a raw Claude Code session transcript under ~/.claude/projects/. Reading it into context "
    "risks surfacing prompts, file contents, command output, or secrets from an unsanitized session. "
    "Per this repo's security posture (CLAUDE.md), read sample data from fixtures/ instead, or run the "
    "sanitizer to produce a scrubbed copy. See .claude/hooks/README.md for the policy."
)

SANITIZER_CONFIG_DENY_REASON = (
    "Blocked by claude-code-sessions secrets-protection hook (.claude/hooks/block_secret_reads.py). "
    "This is the live sanitizer config (.ccs-sanitize.yaml); it holds the literal PII strings to scrub "
    "(real home dir, email, name, GitHub handle). Reading or Edit-ing it would persist that PII in the "
    "session JSONL — Edit specifically surfaces matched old_string values, which is the exact leak path. "
    "Write is allowed: regenerate from scratch (e.g. `ccs-sanitize --init`) or overwrite the file as a "
    "whole. For the schema, read .ccs-sanitize.example.yaml — that's the committed, PII-free reference. "
    "If your Bash invocation was the sanitizer CLI itself (e.g. `ccs-sanitize -c .ccs-sanitize.yaml …`), "
    "drop the `-c` flag — the CLI discovers .ccs-sanitize.yaml from cwd by default and reads it inside "
    "Python (no tool-layer leak). See PRD §12b and .claude/hooks/README.md for the full policy."
)


def path_is_blocked(path_str: str) -> bool:
    if not path_str:
        return False
    p = PurePath(path_str)
    name = p.name
    if name in BLOCKED_BASENAMES:
        return True
    if p.suffix in BLOCKED_SUFFIXES:
        return True
    if name.startswith((".env.", ".env-", ".env_")):
        return True
    return False


def path_is_raw_session(path_str: str) -> bool:
    if not path_str:
        return False
    p = PurePath(os.path.expanduser(path_str))
    if p.suffix != ".jsonl":
        return False
    return RAW_SESSION_ROOT in p.parents


def path_is_sanitizer_config(path_str: str) -> bool:
    if not path_str:
        return False
    # Case-insensitive to stay consistent with SANITIZER_CONFIG_TOKEN_REGEX
    # and to cover macOS APFS / Windows NTFS where `.CCS-Sanitize.YAML`
    # resolves to the same on-disk file.
    return PurePath(path_str).name.lower() == SANITIZER_CONFIG_BASENAME


def bash_command_is_blocked(command: str) -> bool:
    if not command:
        return False
    return CREDENTIAL_TOKEN_REGEX.search(command) is not None


def bash_command_targets_sanitizer_config(command: str) -> bool:
    if not command:
        return False
    return SANITIZER_CONFIG_TOKEN_REGEX.search(command) is not None


def check(event: dict) -> tuple[bool, str]:
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}

    if tool_name in FILE_PATH_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if path_is_blocked(path):
            return True, f"{DENY_REASON} (path: {path})"
        if tool_name in RAW_SESSION_FILE_TOOLS and path_is_raw_session(path):
            return True, f"{RAW_SESSION_DENY_REASON} (path: {path})"
        if tool_name in SANITIZER_CONFIG_FILE_TOOLS and path_is_sanitizer_config(path):
            return True, f"{SANITIZER_CONFIG_DENY_REASON} (path: {path})"

    if tool_name in PATH_SEARCH_TOOLS:
        path = tool_input.get("path") or ""
        pattern = tool_input.get("pattern") or ""
        if path and path_is_blocked(path):
            return True, f"{DENY_REASON} (search path: {path})"
        if path and path_is_raw_session(path):
            return True, f"{RAW_SESSION_DENY_REASON} (search path: {path})"
        if path and path_is_sanitizer_config(path):
            return True, f"{SANITIZER_CONFIG_DENY_REASON} (search path: {path})"
        if pattern and CREDENTIAL_TOKEN_REGEX.search(pattern):
            return True, f"{DENY_REASON} (search pattern targets credential file: {pattern})"
        if pattern and SANITIZER_CONFIG_TOKEN_REGEX.search(pattern):
            return True, f"{SANITIZER_CONFIG_DENY_REASON} (search pattern: {pattern})"

    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        if bash_command_is_blocked(command):
            return True, f"{DENY_REASON} (command: {command[:200]})"
        if bash_command_targets_sanitizer_config(command):
            return True, f"{SANITIZER_CONFIG_DENY_REASON} (command: {command[:200]})"

    return False, ""


def emit_decision(decision: str, reason: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        # Fail closed: this is a security-critical PreToolUse hook. If we can't
        # parse the event we cannot confirm the call is safe, so deny rather
        # than allow through a malformed event of unknown provenance.
        print(
            f"block_secret_reads: failed to parse hook event JSON, denying by default: {e}",
            file=sys.stderr,
        )
        return 2

    blocked, reason = check(event)
    if blocked:
        emit_decision("deny", reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
