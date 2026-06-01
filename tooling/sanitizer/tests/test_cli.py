"""Tests for the `ccs-sanitize` CLI (issue #26).

Covers PRD section 11 acceptance criteria:

  - Exit-code map: 0 success / 1 usage / 2 safety / 3 config.
  - Atomic write + rename order (I-5): sidecar first, then output. A crash
    in the gap leaves an orphan sidecar but never an output without a
    sidecar.
  - ``--dry-run`` runs the full pipeline + residual scan, prints the
    sidecar to stdout, writes nothing to disk.
  - ``--force`` is required to overwrite an existing output file.
  - ``--strip-types`` overrides the default strip set.
  - Config discovery precedence: explicit > CWD > input-dir.
  - End-to-end on a synthetic multi-line session covering paths,
    identifiers, and a fake secret.

Tests prefer ``ccs_sanitize.cli.main(argv)`` over ``subprocess`` so the
exit-code map is exercised in-process. The smoke tests in
``test_cli_smoke.py`` already cover the ``python -m`` and ``ccs-sanitize``
entry-point wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ccs_sanitize import __version__
from ccs_sanitize.cli import _atomic_write_pair, main
from ccs_sanitize.pipeline import serialize_line


# Synthetic identifiers only -- per CLAUDE.md "Security posture" the
# test suite must not commit real personal data. ``.test`` TLD is
# RFC-2606 reserved and cannot collide with a real domain.
_REAL_HOME = "/home/realuser"
_REAL_EMAIL = "user-old@example.test"
_FAKE_AWS_KEY = "AKIA" + "A" * 16

_CONFIG_BODY = f"""
version: 1
paths:
  - match: "{_REAL_HOME}"
    replace: "/home/user"
identifiers:
  - match: "{_REAL_EMAIL}"
    replace: "user@example.com"
"""


def _write_config(path: Path, body: str = _CONFIG_BODY) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _line(obj: dict[str, Any]) -> str:
    return serialize_line(obj)


def _write_input(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _default_session_lines() -> list[str]:
    return [
        _line(
            {
                "type": "user",
                "cwd": f"{_REAL_HOME}/projects/foo",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"hello from {_REAL_EMAIL}",
                        }
                    ]
                },
            }
        ),
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "ack"}
                    ]
                },
            }
        ),
    ]


# ----- version + parse-time errors ---------------------------------------


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_unknown_flag_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--no-such-flag"])
    assert excinfo.value.code == 1


# ----- usage errors (exit 1) ---------------------------------------------


def test_missing_input_arg_exits_one(tmp_path: Path) -> None:
    # ``input`` is nargs="?", so omitting it parses successfully and is
    # caught at the runtime usage layer (_UsageError -> exit 1) rather
    # than at argparse.
    code = main(["-o", str(tmp_path / "out.jsonl")])
    assert code == 1


def test_missing_output_arg_exits_one(tmp_path: Path) -> None:
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    code = main([str(inp)])
    assert code == 1


def test_nonexistent_input_exits_one(tmp_path: Path) -> None:
    code = main(
        [
            str(tmp_path / "does-not-exist.jsonl"),
            "-o",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert code == 1


def test_input_is_directory_exits_one(tmp_path: Path) -> None:
    bogus = tmp_path / "a_dir"
    bogus.mkdir()
    code = main([str(bogus), "-o", str(tmp_path / "out.jsonl")])
    assert code == 1


def test_existing_output_without_force_exits_one(tmp_path: Path) -> None:
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    out = tmp_path / "out.jsonl"
    out.write_text("preexisting", encoding="utf-8")
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    code = main([str(inp), "-o", str(out), "-c", str(cfg)])
    assert code == 1
    # Preexisting file is untouched.
    assert out.read_text(encoding="utf-8") == "preexisting"
    assert not (tmp_path / "out.jsonl.scrubbed").exists()


def test_force_overwrites_existing_output(tmp_path: Path) -> None:
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    out = tmp_path / "out.jsonl"
    out.write_text("preexisting", encoding="utf-8")
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    code = main([str(inp), "-o", str(out), "-c", str(cfg), "--force"])
    assert code == 0
    assert out.exists()
    # Output is no longer the placeholder text.
    assert out.read_text(encoding="utf-8") != "preexisting"
    assert (tmp_path / "out.jsonl.scrubbed").exists()


# ----- config discovery and config errors --------------------------------


def test_explicit_missing_config_exits_one(tmp_path: Path) -> None:
    """An explicit --config pointing at a missing file is a usage error.

    PRD/config.py contract: FileNotFoundError -> exit 1. ConfigError (file
    exists but broken) -> exit 3.
    """
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    code = main(
        [
            str(inp),
            "-o",
            str(tmp_path / "out.jsonl"),
            "-c",
            str(tmp_path / "missing.yaml"),
        ]
    )
    assert code == 1


def test_no_discoverable_config_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery candidates (CWD, input-dir) absent -> exit 1.

    Routed via ``_UsageError`` for the same reason as an explicit missing
    --config: it is the user's responsibility to point us at a config.
    """
    monkeypatch.chdir(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    inp = _write_input(sub / "in.jsonl", _default_session_lines())
    code = main([str(inp), "-o", str(sub / "out.jsonl")])
    assert code == 1


def test_discovery_finds_config_in_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / ".ccs-sanitize.yaml")
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    code = main([str(inp), "-o", str(tmp_path / "out.jsonl")])
    assert code == 0


def test_discovery_finds_config_alongside_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    _write_config(session_dir / ".ccs-sanitize.yaml")
    inp = _write_input(session_dir / "in.jsonl", _default_session_lines())
    code = main([str(inp), "-o", str(session_dir / "out.jsonl")])
    assert code == 0


def test_malformed_config_exits_three(tmp_path: Path) -> None:
    bad_cfg = tmp_path / ".ccs-sanitize.yaml"
    bad_cfg.write_text("version: 1\npaths: not-a-list\n", encoding="utf-8")
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    code = main(
        [str(inp), "-o", str(tmp_path / "out.jsonl"), "-c", str(bad_cfg)]
    )
    assert code == 3


# ----- safety failures (exit 2) ------------------------------------------


def test_malformed_input_exits_two(tmp_path: Path) -> None:
    """A non-JSON line is a PipelineError -> exit 2."""
    inp = tmp_path / "in.jsonl"
    inp.write_text("this is not json\n", encoding="utf-8")
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    code = main(
        [str(inp), "-o", str(tmp_path / "out.jsonl"), "-c", str(cfg)]
    )
    assert code == 2
    # Fail-closed: no output, no sidecar.
    assert not (tmp_path / "out.jsonl").exists()
    assert not (tmp_path / "out.jsonl.scrubbed").exists()


def test_residual_failure_exits_two(tmp_path: Path) -> None:
    """A secret surviving scrub is a ResidualSecretError -> exit 2.

    Planting an AWS-key-shaped string inside ``thinking.signature`` (which
    the pipeline skip-list exempts from scrubbing) lets the secret pass
    the secret transform; the residual scan then catches it. Same setup
    as ``test_orchestrator.py``'s residual path.
    """
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "...",
                            "signature": _FAKE_AWS_KEY,
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    code = main(
        [str(inp), "-o", str(tmp_path / "out.jsonl"), "-c", str(cfg)]
    )
    assert code == 2
    assert not (tmp_path / "out.jsonl").exists()
    assert not (tmp_path / "out.jsonl.scrubbed").exists()


# ----- --dry-run ---------------------------------------------------------


def test_dry_run_prints_sidecar_no_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    out = tmp_path / "out.jsonl"

    code = main(
        [str(inp), "-o", str(out), "-c", str(cfg), "--dry-run"]
    )
    assert code == 0
    captured = capsys.readouterr()
    # Sidecar YAML is recognizable: required keys per PRD section 10.
    parsed = yaml.safe_load(captured.out)
    assert parsed["sanitizer_version"] == __version__
    assert parsed["residual_scan"] == "clean"
    # Nothing on disk.
    assert not out.exists()
    assert not (tmp_path / "out.jsonl.scrubbed").exists()


def test_dry_run_runs_residual_scan(tmp_path: Path) -> None:
    """Dry-run must not skip the residual gate."""
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "...",
                            "signature": _FAKE_AWS_KEY,
                        }
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    code = main(
        [
            str(inp),
            "-o",
            str(tmp_path / "out.jsonl"),
            "-c",
            str(cfg),
            "--dry-run",
        ]
    )
    assert code == 2


# ----- --strip-types -----------------------------------------------------


def test_strip_types_override_changes_dropped_lines(tmp_path: Path) -> None:
    """Override default to drop ``user`` lines; the assistant line stays."""
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    out = tmp_path / "out.jsonl"
    code = main(
        [
            str(inp),
            "-o",
            str(out),
            "-c",
            str(cfg),
            "--strip-types",
            "user",
        ]
    )
    assert code == 0
    body = out.read_text(encoding="utf-8")
    # Exactly one line of output remains: the ``assistant`` line.
    surviving = [ln for ln in body.splitlines() if ln]
    assert len(surviving) == 1
    assert '"type":"assistant"' in surviving[0]

    sidecar_text = (tmp_path / "out.jsonl.scrubbed").read_text(encoding="utf-8")
    parsed = yaml.safe_load(sidecar_text)
    assert parsed["stripped_lines"] == {"user": 1}


def test_strip_types_empty_means_strip_nothing(tmp_path: Path) -> None:
    inp_lines = [
        _line({"type": "file-history-snapshot", "snapshot": "ignored"}),
        _line({"type": "user", "message": {"content": []}}),
    ]
    inp = _write_input(tmp_path / "in.jsonl", inp_lines)
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    out = tmp_path / "out.jsonl"
    code = main(
        [str(inp), "-o", str(out), "-c", str(cfg), "--strip-types", ""]
    )
    assert code == 0
    body = out.read_text(encoding="utf-8")
    surviving = [ln for ln in body.splitlines() if ln]
    # Both lines survive: nothing was stripped.
    assert len(surviving) == 2


# ----- atomic write helper -----------------------------------------------


def test_atomic_write_rename_order_orphan_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the SECOND os.replace fails (output rename), the sidecar is
    already in place. PRD: orphan sidecar is acceptable; bare scrubbed
    output is not."""
    output_path = tmp_path / "out.jsonl"
    sidecar_path = tmp_path / "out.jsonl.scrubbed"

    import ccs_sanitize.cli as cli_module

    real_replace = cli_module.os.replace
    call_count = {"n": 0}

    def fake_replace(src: str, dst: str) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            real_replace(src, dst)
            return
        raise OSError("simulated rename failure")

    monkeypatch.setattr(cli_module.os, "replace", fake_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        _atomic_write_pair(
            output_path=output_path,
            output_bytes=b"final\n",
            sidecar_path=sidecar_path,
            sidecar_text="sidecar: yes\n",
        )

    # Orphan sidecar exists; output does NOT exist; no leftover temp files.
    assert sidecar_path.exists()
    assert sidecar_path.read_text(encoding="utf-8") == "sidecar: yes\n"
    assert not output_path.exists()
    leftover = [
        p
        for p in tmp_path.iterdir()
        if p.name not in {sidecar_path.name}
    ]
    assert leftover == [], f"unexpected leftover temp files: {leftover}"


def test_atomic_write_cleanup_when_first_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the FIRST os.replace (sidecar) fails, neither file is created and
    both temp files are unlinked."""
    output_path = tmp_path / "out.jsonl"
    sidecar_path = tmp_path / "out.jsonl.scrubbed"

    import ccs_sanitize.cli as cli_module

    def fake_replace(src: str, dst: str) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(cli_module.os, "replace", fake_replace)

    with pytest.raises(OSError, match="simulated rename failure"):
        _atomic_write_pair(
            output_path=output_path,
            output_bytes=b"final\n",
            sidecar_path=sidecar_path,
            sidecar_text="sidecar: yes\n",
        )

    assert not output_path.exists()
    assert not sidecar_path.exists()
    leftover = list(tmp_path.iterdir())
    assert leftover == [], f"unexpected leftover temp files: {leftover}"


# ----- end-to-end --------------------------------------------------------


def test_end_to_end_synthetic_session(tmp_path: Path) -> None:
    """Multi-line JSONL with paths, identifiers, and a fake AWS key.

    Asserts: exit 0, output bytes are clean of all originals, sidecar is
    valid YAML with the expected categories, input SHA matches.
    """
    import hashlib

    lines = [
        _line(
            {
                "type": "user",
                "cwd": f"{_REAL_HOME}/projects/foo",
                "message": {
                    "content": [
                        {"type": "text", "text": f"reach me at {_REAL_EMAIL}"}
                    ]
                },
            }
        ),
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "input": {
                                "command": f"echo AWS_KEY={_FAKE_AWS_KEY}"
                            },
                        }
                    ]
                },
            }
        ),
        _line({"type": "file-history-snapshot", "snapshot": "should-drop"}),
    ]
    inp_path = _write_input(tmp_path / "session.jsonl", lines)
    cfg_path = _write_config(tmp_path / ".ccs-sanitize.yaml")
    out_path = tmp_path / "out.jsonl"

    code = main([str(inp_path), "-o", str(out_path), "-c", str(cfg_path)])
    assert code == 0

    body = out_path.read_text(encoding="utf-8")
    assert _REAL_HOME not in body
    assert _REAL_EMAIL not in body
    assert _FAKE_AWS_KEY not in body
    # Strip default drops the file-history-snapshot line.
    surviving = [ln for ln in body.splitlines() if ln]
    assert len(surviving) == 2

    sidecar = yaml.safe_load(
        (tmp_path / "out.jsonl.scrubbed").read_text(encoding="utf-8")
    )
    assert sidecar["sanitizer_version"] == __version__
    assert sidecar["residual_scan"] == "clean"
    assert sidecar["input_filename"] == "session.jsonl"
    expected_sha = hashlib.sha256(inp_path.read_bytes()).hexdigest()
    assert sidecar["input_sha256"] == expected_sha
    assert sidecar["stripped_lines"] == {"file-history-snapshot": 1}
    assert sidecar["rules_applied"]["paths"]["substitutions"] >= 1
    assert sidecar["rules_applied"]["identifiers"]["substitutions"] >= 1
    assert sidecar["rules_applied"]["secrets"]["matches"] >= 1


def test_verbose_writes_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    cfg = _write_config(tmp_path / ".ccs-sanitize.yaml")
    out = tmp_path / "out.jsonl"
    code = main([str(inp), "-o", str(out), "-c", str(cfg), "--verbose"])
    assert code == 0
    captured = capsys.readouterr()
    # Some milestone surfaces on stderr; stdout stays empty for non-dry-run.
    assert captured.err != ""
    assert captured.out == ""
