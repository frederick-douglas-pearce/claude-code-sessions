#!/usr/bin/env python3
"""Tests for the secrets-protection hooks. Stdlib only.

Run directly:
    python3 .claude/hooks/tests/test_hooks.py
or via pytest. Each case pipes a synthetic event fixture into the matching
hook and asserts the resulting block/deny/allow decision. The known-bad
fixtures contain only fake, clearly-synthetic credential patterns.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PRE_HOOK = HOOKS_DIR / "block_secret_reads.py"
POST_HOOK = HOOKS_DIR / "detect_secrets_in_output.py"


def run_hook(hook_path: Path, event_text: str) -> str:
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=event_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def hook_for(event_text: str) -> Path:
    name = json.loads(event_text).get("hook_event_name")
    return PRE_HOOK if name == "PreToolUse" else POST_HOOK


class HookBlockingTests(unittest.TestCase):
    def _decision(self, fixture: str) -> dict:
        text = load_fixture(fixture)
        out = run_hook(hook_for(text), text)
        return json.loads(out) if out.strip() else {}

    def test_credential_env_read_denied(self):
        d = self._decision("block_credential_env.json")
        self.assertEqual(
            d.get("hookSpecificOutput", {}).get("permissionDecision"), "deny"
        )
        self.assertIn(
            "credential source",
            d["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_raw_session_read_denied(self):
        d = self._decision("block_raw_session_read.json")
        self.assertEqual(
            d.get("hookSpecificOutput", {}).get("permissionDecision"), "deny"
        )
        self.assertIn(
            "raw Claude Code session",
            d["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_secret_in_output_blocked(self):
        d = self._decision("block_secret_in_output.json")
        self.assertEqual(d.get("decision"), "block")
        self.assertIn("anthropic-key", d.get("reason", ""))

    def test_pem_private_key_blocked(self):
        # `cat ~/.ssh/id_rsa` and similar live tool outputs are the
        # catastrophic case the hook exists to block. The ENCRYPTED PEM
        # header was previously not in the hook's pattern set.
        d = self._decision("block_pem_private_key.json")
        self.assertEqual(d.get("decision"), "block")
        self.assertIn("pem-private-key", d.get("reason", ""))

    def test_fixture_read_allowed(self):
        # A fixtures/ jsonl read is legitimate and must NOT be blocked.
        self.assertEqual(self._decision("allow_fixture_read.json"), {})

    def test_bash_tail_session_allowed(self):
        # Bash is excluded from the raw-session block by design, so the
        # documented `tail -f ~/.claude/projects/...` workflow still works.
        self.assertEqual(self._decision("allow_bash_tail_session.json"), {})

    def _assert_sanitizer_config_deny(self, fixture: str) -> None:
        d = self._decision(fixture)
        self.assertEqual(
            d.get("hookSpecificOutput", {}).get("permissionDecision"), "deny"
        )
        self.assertIn(
            "live sanitizer config",
            d["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_sanitizer_config_read_denied(self):
        self._assert_sanitizer_config_deny("block_sanitizer_config_read.json")

    def test_sanitizer_config_edit_denied(self):
        # Edit is the highest-priority leak vector — it surfaces old_string
        # into the transcript while searching for the replacement target.
        self._assert_sanitizer_config_deny("block_sanitizer_config_edit.json")

    def test_sanitizer_config_multiedit_denied(self):
        # MultiEdit is Edit × N — every old_string in the edits[] array
        # gets surfaced. Same leak vector, larger blast radius.
        self._assert_sanitizer_config_deny("block_sanitizer_config_multiedit.json")

    def test_sanitizer_config_read_uppercase_denied(self):
        # On case-insensitive filesystems (macOS APFS, Windows NTFS) a
        # capitalized path resolves to the same on-disk live config —
        # the basename check must match case-insensitively so the file-tool
        # path cannot diverge from the (already IGNORECASE) bash regex.
        self._assert_sanitizer_config_deny("block_sanitizer_config_read_uppercase.json")

    def test_sanitizer_config_grep_path_denied(self):
        self._assert_sanitizer_config_deny("block_sanitizer_config_grep_path.json")

    def test_sanitizer_config_grep_pattern_denied(self):
        self._assert_sanitizer_config_deny("block_sanitizer_config_grep_pattern.json")

    def test_sanitizer_config_bash_denied(self):
        self._assert_sanitizer_config_deny("block_sanitizer_config_bash.json")

    def test_sanitizer_config_write_allowed(self):
        # Write is the regenerate-from-scratch / `ccs-sanitize --init` path —
        # it overwrites rather than surfacing existing content, so it stays
        # allowed (mirrors the raw-session asymmetry).
        self.assertEqual(self._decision("allow_sanitizer_config_write.json"), {})

    def test_sanitizer_example_read_allowed(self):
        # The committed .example.yaml is the schema reference and contains
        # no PII; the regex is anchored to .ccs-sanitize.yaml so it stays
        # freely readable.
        self.assertEqual(self._decision("allow_sanitizer_example_read.json"), {})

    def test_ccs_sanitize_cli_invocation_allowed(self):
        # The CLI default reads .ccs-sanitize.yaml from cwd without naming
        # it on the command line, so the bash token pattern does not match
        # a vanilla invocation — and the CLI reads the file from Python,
        # outside the Claude Code tool layer, so the hook is not in the
        # path even if it did fire.
        self.assertEqual(self._decision("allow_ccs_sanitize_cli.json"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
