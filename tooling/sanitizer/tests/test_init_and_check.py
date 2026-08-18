"""Tests for the PRD section 12b safety surfaces (issue #45).

Covers:

  - ``ccs-sanitize --init`` writes ``.ccs-sanitize.example.yaml`` and
    ``.ccs-sanitize.yaml`` into the cwd from the bundled template, prints
    a one-line gitignore reminder, and is idempotent on a re-run.
  - ``--init`` does NOT mutate ``.gitignore`` — architect-reviewed
    decision to leave that to the user (issue #45 review C-3).
  - The package-data template is byte-equal to the committed repo-root
    ``.ccs-sanitize.example.yaml`` (drift guard for the architect-pinned
    "single source of truth" decision, Option A).
  - The shipped template loads via ``load_config`` with no I-3 violations
    so a newly bootstrapped repo can run the sanitizer immediately.
  - The pre-run ``--check`` guard refuses to scrub when the resolved
    config path is not gitignored (exit 3) and is bypassed by
    ``--no-check``. ``git`` unavailable / no repo is a warning-only path
    (defense-in-depth, not the only defense; PRD §12b).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ccs_sanitize.cli import (
    _CONFIG_FILENAME,
    _CONFIG_TEMPLATE_RESOURCE,
    _EXAMPLE_CONFIG_FILENAME,
    _read_config_template,
    main,
)
from ccs_sanitize.config import load_config

from ._helpers import serialize_test_line as _line


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_input(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _default_session_lines() -> list[str]:
    return [
        _line({"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}),
    ]


def _isolated_git_env() -> dict[str, str]:
    """Return an env scrubbed of ambient git redirection so subprocess
    ``git`` calls operate on the tmp_path repo and not whatever the
    developer's shell happens to point at.

    Without this scrub: ``GIT_DIR`` / ``GIT_WORK_TREE`` (set by some
    wrapper scripts and IDE integrations) silently redirect ``git init``
    and ``git check-ignore`` away from the tmp_path repo, and a
    developer's ``core.excludesfile`` / ``init.templateDir`` shipping a
    default ``.gitignore`` can match ``.ccs-sanitize.yaml`` and flip
    the ``not gitignored`` test branch to ``ignored``. The test would
    then pass or fail based on the dev's environment.

    ``GIT_CONFIG_GLOBAL`` and ``GIT_CONFIG_SYSTEM`` set to ``/dev/null``
    neutralize both layers of global git config for git>=2.32 (where
    these env vars are honored); ``HOME`` is overridden too so older
    git versions that read ``~/.gitconfig`` directly still see a clean
    config. All ``GIT_*`` env vars from the parent are dropped.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _init_git_repo(repo: Path) -> None:
    """Initialize a minimal repo so `git check-ignore` has something to consult.

    Tests that need the pre-run guard to actually evaluate (rather than
    fall through the "not a git repo" warn-and-proceed path) call this
    on ``tmp_path``. The environment is scrubbed of ``GIT_*`` redirects
    and global config (see ``_isolated_git_env``) so the test does not
    inherit the developer's gitignore rules.
    """
    subprocess.run(
        [
            "git",
            "-c",
            "init.defaultBranch=main",
            "-c",
            "init.templateDir=",
            "init",
            "-q",
            str(repo),
        ],
        check=True,
        env=_isolated_git_env(),
    )
    # ``git check-ignore`` looks at the index, the working tree, and the
    # gitignore files. An empty repo with no ``.gitignore`` is enough --
    # check-ignore returns exit 1 (not ignored) for the config path.


# ----- --init -------------------------------------------------------------


def test_init_writes_both_files_in_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    code = main(["--init"])
    assert code == 0

    example_path = tmp_path / _EXAMPLE_CONFIG_FILENAME
    live_path = tmp_path / _CONFIG_FILENAME
    assert example_path.is_file()
    assert live_path.is_file()
    # Both files start from the same template -- byte equality is the
    # contract _run_init advertises.
    assert example_path.read_text() == live_path.read_text()

    captured = capsys.readouterr()
    # Reminder is the user's pointer at the gitignore convention. Match
    # on the substring rather than the full sentence so a future copy
    # tweak does not break this assertion gratuitously.
    assert ".gitignore" in captured.err
    assert _CONFIG_FILENAME in captured.err


def test_init_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Re-running --init on a populated directory must not overwrite
    user edits. Architect-pinned (issue #45 review) so --init can be
    safely invoked from setup scripts.
    """
    monkeypatch.chdir(tmp_path)

    # First run writes both.
    assert main(["--init"]) == 0
    live_path = tmp_path / _CONFIG_FILENAME
    user_edit = "# user-customized\nversion: 1\nidentifiers: []\n"
    live_path.write_text(user_edit, encoding="utf-8")

    # Second run must not clobber the user edit.
    capsys.readouterr()  # discard first-run output
    assert main(["--init"]) == 0
    assert live_path.read_text() == user_edit

    captured = capsys.readouterr()
    # No-op message is logged so the user knows nothing happened.
    assert "already exist" in captured.err


def test_init_rejects_scrub_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--init` combined with any scrub-only argument must exit 1 (usage).

    Without this guard a user running `ccs-sanitize --init session.jsonl
    -o scrubbed.jsonl` would see exit 0 with only the init files written
    -- believing they had scrubbed when they had not. Each scrub-only
    arg is independently rejected; this test pins the common case (input
    + -o) plus one other (--dry-run).
    """
    monkeypatch.chdir(tmp_path)
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    out = tmp_path / "out.jsonl"

    code = main(["--init", str(inp), "-o", str(out)])
    assert code == 1
    captured = capsys.readouterr()
    assert "--init cannot be combined" in captured.err
    # No init files written -- the guard fires BEFORE any work.
    assert not (tmp_path / _CONFIG_FILENAME).exists()

    code = main(["--init", "--dry-run"])
    assert code == 1


def test_init_refuses_dangling_symlink_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dangling symlink at .ccs-sanitize.yaml is a hard error -- silently
    skipping it would leave the user with a broken config the next run
    cannot read, and overwriting it would erase whatever the user
    intended to point at. Exit 1 (usage); user must remove or repoint.
    """
    monkeypatch.chdir(tmp_path)
    live_path = tmp_path / _CONFIG_FILENAME
    live_path.symlink_to(tmp_path / "does-not-exist.yaml")
    assert live_path.is_symlink()
    assert not live_path.exists()

    code = main(["--init"])
    assert code == 1
    # Live path remains a (broken) symlink; not overwritten.
    assert live_path.is_symlink()
    assert not live_path.exists()


def test_init_does_not_modify_gitignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Architect review C-3: --init must not mutate a tracked file.

    Pre-existing .gitignore content is preserved; if there's no .gitignore,
    --init does not create one.
    """
    monkeypatch.chdir(tmp_path)

    existing_gitignore = "# user content\n*.log\n"
    (tmp_path / ".gitignore").write_text(existing_gitignore, encoding="utf-8")

    assert main(["--init"]) == 0
    assert (tmp_path / ".gitignore").read_text() == existing_gitignore

    # And in the no-gitignore case, --init must not create one.
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert main(["--init"]) == 0
    assert not (other / ".gitignore").exists()


# ----- template integrity -------------------------------------------------


def test_template_resource_matches_repo_root_example() -> None:
    """Drift guard for architect-pinned Option A (single source of truth).

    The package-data ``_templates/ccs-sanitize.example.yaml`` must be
    byte-identical to the committed ``.ccs-sanitize.example.yaml`` at
    the repo root. If this test fails, one of the two has been edited
    without updating the other -- the fix is to copy whichever is
    canonical over the other.

    When the package is installed (``pytest --pyargs ccs_sanitize`` from
    a wheel install, or tox in an isolated env), ``_REPO_ROOT`` points
    at a directory that has no checkout in it -- there is no repo-root
    file to compare against. Skip rather than fail in that case: the
    drift guard is a source-tree assertion, not an installed-package
    contract.
    """
    repo_example = _REPO_ROOT / _EXAMPLE_CONFIG_FILENAME
    if not repo_example.is_file():
        pytest.skip(
            f"repo-root template missing at {repo_example}; tests are "
            "running outside a source checkout (e.g. against an "
            "installed wheel). The drift guard is a source-tree-only "
            "assertion."
        )
    assert repo_example.read_bytes() == _read_config_template().encode(
        "utf-8"
    ), (
        "Template drift: package-data "
        f"_templates/{_CONFIG_TEMPLATE_RESOURCE} differs from repo-root "
        f"{_EXAMPLE_CONFIG_FILENAME}. Copy whichever is canonical over "
        "the other -- they MUST stay byte-equal (issue #45 architect "
        "review, Option A)."
    )


def test_shipped_template_loads_without_i3_violations(tmp_path: Path) -> None:
    """Acceptance criterion (#45): the shipped example template loads
    cleanly via ``load_config``. The I-3 replacement-leak guard runs at
    load time; a misconfigured placeholder (e.g. a same-string mapping
    like ``Real Name -> Real Name``) would fail here. A user who runs
    --init must be able to ``ccs-sanitize`` immediately without first
    fixing the example.
    """
    target = tmp_path / _EXAMPLE_CONFIG_FILENAME
    target.write_text(_read_config_template(), encoding="utf-8")
    cfg = load_config(target)
    # Sanity: the template is not empty -- a future template that
    # accidentally ships as an empty file would load (with no rules) and
    # silently pass this test. Pin the shape so that case fails loudly.
    assert cfg.version == 1
    assert len(cfg.paths) >= 1
    assert len(cfg.identifiers) >= 1


# ----- pre-run gitignore guard --------------------------------------------


_MINIMAL_CONFIG = (
    "version: 1\n"
    'paths:\n  - match: "/home/realuser"\n    replace: "/home/user"\n'
)


def _seed_session(tmp_path: Path) -> tuple[Path, Path]:
    inp = _write_input(tmp_path / "in.jsonl", _default_session_lines())
    cfg = tmp_path / _CONFIG_FILENAME
    cfg.write_text(_MINIMAL_CONFIG, encoding="utf-8")
    return inp, cfg


def _isolate_global_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point HOME and XDG_CONFIG_HOME at tmp_path so the production
    ``git check-ignore`` subprocess cannot read the developer's
    ``~/.gitconfig`` and pick up a ``core.excludesfile`` that matches
    ``.ccs-sanitize.yaml``.

    The production code (``_git_check_ignore_env``) drops ``GIT_*``
    redirects from the subprocess environment but deliberately preserves
    ``HOME``/``XDG_CONFIG_HOME`` so a user's intentional global gitignore
    still applies. In tests we override HOME to neutralize the dev's
    global config layer for the duration of the test.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not on PATH; pre-run check fall-through path is covered by "
    "test_check_warns_when_git_unavailable.",
)
def test_check_refuses_when_config_not_gitignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fresh git repo, no .gitignore -> config not ignored -> exit 3."""
    _isolate_global_git(monkeypatch, tmp_path)
    _init_git_repo(tmp_path)
    inp, cfg = _seed_session(tmp_path)
    out = tmp_path / "out.jsonl"

    code = main([str(inp), "-o", str(out), "-c", str(cfg)])
    assert code == 3
    captured = capsys.readouterr()
    assert "not gitignored" in captured.err
    # Actionable message names the file and points at the convention.
    assert _CONFIG_FILENAME in captured.err
    assert _EXAMPLE_CONFIG_FILENAME in captured.err
    # The remedy is .gitignore, not --no-check (#164). The message must
    # frame the flag as an override rather than steering a stranger who
    # just hit exit 3 toward disabling the guard.
    assert ".gitignore" in captured.err
    assert "deliberate override" in captured.err
    # Fail-closed: no output, no sidecar (PRD §11 + §12b).
    assert not out.exists()
    assert not (tmp_path / "out.jsonl.scrubbed").exists()


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not on PATH; gitignore path uses git check-ignore.",
)
def test_check_passes_when_config_gitignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gitignored config proceeds to a normal exit-0 scrub."""
    _isolate_global_git(monkeypatch, tmp_path)
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(
        f"{_CONFIG_FILENAME}\n", encoding="utf-8"
    )
    inp, cfg = _seed_session(tmp_path)
    out = tmp_path / "out.jsonl"

    code = main([str(inp), "-o", str(out), "-c", str(cfg)])
    assert code == 0
    assert out.exists()
    assert (tmp_path / "out.jsonl.scrubbed").exists()


@pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git needed to demonstrate that --no-check bypasses the "
    "would-otherwise-fail check.",
)
def test_no_check_bypasses_gitignore_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--no-check`` opts out of the pre-run guard on a non-ignored config.

    A deliberate override, whose main legitimate user is the sanitizer's
    own test suite (issue #45 architect review C-4). Note that a repo-less
    environment does not need it: that path warns and proceeds on its own
    (see ``test_check_warns_when_not_in_git_repo``), which is why the
    flag's help text no longer advertises it as the CI accommodation
    (issue #164).
    """
    _isolate_global_git(monkeypatch, tmp_path)
    _init_git_repo(tmp_path)
    inp, cfg = _seed_session(tmp_path)
    out = tmp_path / "out.jsonl"

    code = main([str(inp), "-o", str(out), "-c", str(cfg), "--no-check"])
    assert code == 0
    assert out.exists()


def test_check_warns_when_not_in_git_repo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Outside a git repo there is no gitignore to consult -- the check
    must warn-and-proceed rather than fail closed (PRD §12b, defense in
    depth). This is also the path the rest of the test suite goes
    through, so it must end in exit 0.
    """
    inp, cfg = _seed_session(tmp_path)
    out = tmp_path / "out.jsonl"

    code = main([str(inp), "-o", str(out), "-c", str(cfg)])
    assert code == 0
    captured = capsys.readouterr()
    # Warning surfaces -- but the run still succeeds.
    assert "warning" in captured.err.lower()


def test_check_warns_when_git_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If `git` is not on PATH, the guard warns and proceeds.

    Same justification as the no-git-repo case: the convention layer
    and hook layer cover this threat from other angles, so a missing
    git binary is defense-in-depth lost, not a stop-the-world error.
    """
    import ccs_sanitize.cli as cli_module

    monkeypatch.setattr(cli_module.shutil, "which", lambda _name: None)
    inp, cfg = _seed_session(tmp_path)
    out = tmp_path / "out.jsonl"

    code = main([str(inp), "-o", str(out), "-c", str(cfg)])
    assert code == 0
    captured = capsys.readouterr()
    assert "git not found" in captured.err
