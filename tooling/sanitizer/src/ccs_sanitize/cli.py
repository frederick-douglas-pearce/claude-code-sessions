"""CLI entry point for `ccs-sanitize`.

PRD reference: section 11 (CLI shape & fail-closed behavior).

Exit codes (PRD section 11):

    0 — success (output + sidecar written)
    1 — usage error (bad args, missing input/config file, output exists
        without --force)
    2 — safety failure (PipelineError, ResidualSecretError, SidecarLeakError,
        or any unexpected exception during the scrub pipeline)
    3 — config error (ConfigError: malformed YAML, schema violation, regex
        compile failure, I-3 replacement-leak)

``_SafeArgumentParser.error`` overrides argparse's default exit-2 on parse
errors so usage errors (bad/missing args) map to exit 1 and exit 2 stays
reserved for safety failures. Conflating "bad CLI args" with "a secret
survived redaction" would be a meaningful regression on a security tool.

``FileNotFoundError`` from ``load_config`` is exit 1 (the file at that
path does not exist — a usage problem); ``ConfigError`` is exit 3 (the
file exists but is broken). ``config.py`` deliberately re-raises
``FileNotFoundError`` separately precisely so the CLI can keep this
distinction.

Atomicity & rename order (I-5). Both output and sidecar are written to
temp files in the destination directory (same filesystem, so ``os.replace``
is atomic) and renamed into place only after ``sanitize_session`` and
``build_sidecar`` both succeed. The sidecar is renamed first, then the
output — a crash in the gap leaves an orphan sidecar (harmless,
overwritten on re-run) but never a scrubbed output without a sidecar.
``_atomic_write_pair`` keeps that ordering plus cleanup in one auditable
function.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import Config, ConfigError, load_config
from .orchestrator import sanitize_session
from .pipeline import DEFAULT_STRIP_TYPES, PipelineError
from .residual import ResidualSecretError
from .sidecar import (
    SidecarLeakError,
    SidecarMetadata,
    build_sidecar,
    sha256_hex,
    utc_now_iso8601,
)

_CONFIG_FILENAME = ".ccs-sanitize.yaml"
_EXAMPLE_CONFIG_FILENAME = ".ccs-sanitize.example.yaml"
# Package-data resource shipped with the wheel. The committed
# `.ccs-sanitize.example.yaml` at the repo root must stay byte-identical
# to this file; ``test_template_resource_matches_repo_root_example`` in
# ``tests/test_init_and_check.py`` pins the equality so the two cannot
# silently drift.
_CONFIG_TEMPLATE_RESOURCE = "ccs-sanitize.example.yaml"


class _UsageError(Exception):
    """Raised for runtime usage errors that surface after argparse (missing
    input file, output exists without --force, no discoverable config).

    Maps to exit 1. Kept distinct from argparse's parse-time errors so the
    error message can be tailored — the parser's ``error()`` prints a usage
    line, which is unhelpful for "output already exists"."""


class _SafeArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that exits 1 on usage errors instead of argparse's
    default 2 — exit code 2 is reserved for safety failures (PRD section 11).
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parse_strip_types(value: str) -> frozenset[str]:
    """Parse the ``--strip-types`` comma-separated list.

    Empty string is accepted and means "strip nothing" — without an
    explicit empty form there is no way to opt out of stripping, since
    omitting the flag falls back to ``DEFAULT_STRIP_TYPES``.
    """
    if not value:
        return frozenset()
    items = [item.strip() for item in value.split(",")]
    if any(not item for item in items):
        raise argparse.ArgumentTypeError(
            f"--strip-types contains an empty element: {value!r}"
        )
    return frozenset(items)


def _build_parser() -> argparse.ArgumentParser:
    # ``allow_abbrev=False``: with multiple ``--no-*`` flags (currently
    # ``--no-check``), argparse's prefix-abbreviation would let ``--no``
    # silently resolve to whichever future flag happens to be
    # unambiguous, and a script using ``--no`` shorthand would shift
    # meaning across releases. Long-form only.
    parser = _SafeArgumentParser(
        prog="ccs-sanitize",
        description=(
            "Scrub a Claude Code session JSONL file for safe publication. "
            "See PRD: .claude/specs/prd-sanitizer.md"
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ccs-sanitize {__version__}",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="Path to the session JSONL file to scrub.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSONL path. The sidecar is written to <output>.scrubbed.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help=(
            "Rules YAML. Discovery: explicit > ./.ccs-sanitize.yaml "
            "> <input_dir>/.ccs-sanitize.yaml."
        ),
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help=(
            f"Bootstrap a new project: write {_EXAMPLE_CONFIG_FILENAME} and "
            f"{_CONFIG_FILENAME} into the current working directory (if "
            "missing) and exit. Does NOT modify .gitignore -- gitignoring "
            f"{_CONFIG_FILENAME} is the user's job; the pre-run gitignore "
            "guard (default-on; opt out with --no-check) enforces it on "
            "every subsequent run."
        ),
    )
    parser.add_argument(
        "--no-check",
        action="store_true",
        help=(
            "Skip the pre-run check that the resolved config path is "
            "gitignored. The guard fails closed (exit 3) only when the "
            "config is inside a git repository and is not gitignored; "
            "outside a repository it already warns and proceeds. This "
            "flag is a deliberate override of the guard, used by the "
            "test suite and by anyone who has knowingly accepted the "
            "risk. It is not the fix for exit 3 -- gitignoring the "
            "config is. PRD section 12b."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the full pipeline + residual scan and print the sidecar "
            "YAML to stdout; write nothing to disk."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting an existing output file.",
    )
    parser.add_argument(
        "--strip-types",
        type=_parse_strip_types,
        default=DEFAULT_STRIP_TYPES,
        help=(
            "Comma-separated line types to drop wholesale. Default: "
            f"{','.join(sorted(DEFAULT_STRIP_TYPES))}. Pass an empty string "
            "to strip nothing."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-stage progress milestones to stderr.",
    )
    return parser


def _read_config_template() -> str:
    """Return the bundled `.ccs-sanitize.example.yaml` template text.

    Source of truth for ``--init``. The committed
    ``.ccs-sanitize.example.yaml`` at the repo root is byte-equal to this
    resource; ``test_template_resource_matches_repo_root_example`` in
    ``tests/test_init_and_check.py`` pins the equality so the two cannot
    silently drift across a release.
    """
    return (
        resources.files("ccs_sanitize._templates")
        .joinpath(_CONFIG_TEMPLATE_RESOURCE)
        .read_text(encoding="utf-8")
    )


def _run_init(verbose: bool) -> int:
    """Bootstrap a new project's sanitizer config in the current directory.

    Writes ``.ccs-sanitize.example.yaml`` and ``.ccs-sanitize.yaml`` (both
    from the bundled template) if they do not already exist. Existing
    files are NOT overwritten — re-running ``--init`` on a populated
    directory is intentionally a no-op so it is safe to invoke from a
    setup script. Does NOT touch ``.gitignore``: silently mutating a
    tracked file on first run is surprising and risks merge conflicts
    (issue #45 architect review). Prints a one-line reminder to stderr
    pointing the user at the gitignore convention; the pre-run check
    enforces it mechanically on the next scrub.

    ``FileNotFoundError`` from the package-data template lookup and
    ``OSError`` / ``PermissionError`` from the file writes are caught
    and re-raised as ``_UsageError`` -> exit 1. Without this, both
    cases would fall through to ``main()``'s defensive
    ``except Exception`` and be reported as ``safety failure`` /
    exit 2 -- exit 2 is reserved for residual-secret leaks (PRD §11),
    so a packaging error or a read-only cwd must NOT borrow that exit
    code. Mirrors the ``_atomic_write_pair`` OSError handling.
    """
    try:
        template = _read_config_template()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise _UsageError(
            f"--init: bundled config template is missing from the install "
            f"({type(exc).__name__}: {exc}). This indicates a packaging "
            "regression -- reinstall ccs-sanitize."
        ) from exc
    cwd = Path.cwd()
    example_path = cwd / _EXAMPLE_CONFIG_FILENAME
    live_path = cwd / _CONFIG_FILENAME

    try:
        wrote_example = _write_if_missing(example_path, template, verbose=verbose)
        wrote_live = _write_if_missing(live_path, template, verbose=verbose)
    except OSError as exc:
        raise _UsageError(
            f"--init: cannot write into {cwd} ({type(exc).__name__}: "
            f"{exc}). Check directory permissions or run --init in a "
            "writable cwd."
        ) from exc

    if not wrote_example and not wrote_live:
        print(
            f"ccs-sanitize: --init: both {_EXAMPLE_CONFIG_FILENAME} and "
            f"{_CONFIG_FILENAME} already exist; nothing to do.",
            file=sys.stderr,
        )

    # Reminder is printed unconditionally — even on a no-op run — because the
    # check it points at is the one users forget. Cheap to repeat; costly to
    # omit on the run that would have caught a missing gitignore entry.
    print(
        f"ccs-sanitize: reminder: add `{_CONFIG_FILENAME}` to your "
        f".gitignore before committing. See "
        f"`{_EXAMPLE_CONFIG_FILENAME}` for the recommended pattern; the "
        "pre-run gitignore guard refuses to run otherwise, once this "
        "directory is a git repository.",
        file=sys.stderr,
    )
    return 0


def _write_if_missing(path: Path, content: str, *, verbose: bool) -> bool:
    """Write ``content`` to ``path`` only if ``path`` does not yet exist.

    Returns True if the file was written, False if it already existed.
    Uses ``x`` mode so a race with another process picks one writer and
    leaves the other's contents intact — relevant because ``--init`` is
    the kind of command users sometimes run twice in a script.

    A dangling symlink (``is_symlink()`` True, ``exists()`` False) is
    surfaced as a hard error rather than silently skipped: a stale
    symlink at the config path would cause the next ``ccs-sanitize``
    invocation to fail in ``load_config`` with a confusing
    target-path error, and ``--init`` cannot just overwrite the link
    without erasing whatever the user intended to point at.
    """
    if path.is_symlink() and not path.exists():
        raise OSError(
            f"{path.name} is a dangling symlink (target does not exist); "
            "refusing to silently overwrite. Remove or repoint the link, "
            "then re-run --init."
        )
    if path.exists() or path.is_symlink():
        _log(verbose, f"--init: {path.name} already exists; leaving as-is")
        return False
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError:
        _log(verbose, f"--init: {path.name} appeared concurrently; leaving as-is")
        return False
    _log(verbose, f"--init: wrote {path}")
    return True


def _git_check_ignore_env() -> dict[str, str]:
    """Return an environment for ``git check-ignore`` scrubbed of ambient
    ``GIT_*`` redirects.

    Without this scrub, ``GIT_DIR`` / ``GIT_WORK_TREE`` (set by wrapper
    scripts or some IDE integrations) silently redirect the subprocess at
    a different repository than the one the user's config lives in, and
    the gitignore check evaluates the wrong ignore rules. The strict
    fail-closed claim in PRD §12b requires the check to consult the same
    working tree the user is in, not whichever repo ``GIT_DIR`` happens
    to point at. ``HOME`` and ``XDG_CONFIG_HOME`` are preserved so global
    config (``~/.gitconfig``) still applies — the user's intentional
    ``core.excludesfile`` is part of the legitimate gitignore picture; it
    is the *process-level* redirects we drop.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _check_config_gitignored(config_path: Path, verbose: bool) -> None:
    """Refuse to operate if the resolved config path is not gitignored.

    Implements the PRD section 12b pre-run guard. Behavior table:

      - Config file does not exist: skip the check and return silently.
        The caller's ``load_config`` will raise a clean
        ``FileNotFoundError`` -> exit 1 ("config file not found") with a
        diagnostic that names the right problem; a "not gitignored"
        message for a non-existent file would misdirect the user.
      - ``git`` binary missing or cwd not a git repository: warn to
        stderr and proceed. Defense-in-depth, not the only defense —
        the convention + hook layer ([#47]) catch the threat from other
        angles, and the test suite + CI environments without ``.git``
        legitimately have nothing to check against.
      - ``git check-ignore`` exit 0: path is gitignored, proceed silently.
      - ``git check-ignore`` exit 1: path is NOT gitignored, raise
        ``ConfigError`` (CLI maps to exit 3) with a message naming the
        file and pointing at ``.ccs-sanitize.example.yaml``.
      - Any other ``git`` exit (128 = not a repo, broken index, etc.):
        warn and proceed for the same reason as the binary-missing path.

    Implementation notes:

      - The path passed to ``git check-ignore`` is the bare basename and
        the subprocess ``cwd`` is the config's parent directory (NOT
        ``.resolve().parent`` — resolving symlinks would consult the
        target's repo, silently weakening the guard for a user who
        symlinks the config in from a dotfiles tree).
      - ``encoding='utf-8', errors='replace'`` is passed explicitly so a
        non-ASCII byte in git's stderr under a POSIX/C locale cannot
        raise ``UnicodeDecodeError`` past the ``(OSError,
        SubprocessError)`` catch and turn a warn-and-proceed into an
        exit-2 safety failure.
      - Ambient ``GIT_*`` env vars are scrubbed (see
        ``_git_check_ignore_env``) so a wrapper script's ``GIT_DIR``
        cannot redirect the check away from the config's actual repo.

    Raises:
        ConfigError: the config path exists on disk but is not gitignored.
    """
    # If the file does not exist, skip — load_config will raise a clean
    # FileNotFoundError -> exit 1 in the caller, which is a more
    # accurate diagnostic than "not gitignored: <missing path>".
    if not config_path.is_file():
        _log(verbose, f"gitignore-check: skipped (file missing): {config_path}")
        return

    git_bin = shutil.which("git")
    if git_bin is None:
        print(
            "ccs-sanitize: warning: git not found on PATH; cannot verify "
            f"that {config_path} is gitignored (PRD §12b). Proceeding; "
            "the gitignore convention is defense-in-depth, not the only "
            "defense. Pass --no-check to skip this guard.",
            file=sys.stderr,
        )
        return
    # cwd = the directory that physically contains the path entry as the
    # user wrote it (no .resolve()), so check-ignore consults the repo
    # the user actually staged the file in -- not the symlink target's
    # repo. The arg is the bare basename so the relative-vs-absolute
    # form of `config_path` cannot re-resolve into a doubled-up subpath.
    parent_dir = config_path.parent if str(config_path.parent) else Path(".")
    try:
        result = subprocess.run(
            [git_bin, "check-ignore", "-v", "--", config_path.name],
            cwd=str(parent_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            env=_git_check_ignore_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"ccs-sanitize: warning: could not invoke `git check-ignore` "
            f"on {config_path}: {exc}. Proceeding; pass --no-check to "
            "skip this guard.",
            file=sys.stderr,
        )
        return

    if result.returncode == 0:
        _log(verbose, f"gitignore-check: {config_path} is gitignored")
        return
    if result.returncode == 1:
        raise ConfigError(
            f"config file is not gitignored: {config_path}\n"
            f"  The sanitizer config holds literal PII match values and "
            f"would leak through `git add .`. Add `{_CONFIG_FILENAME}` "
            f"to your .gitignore and re-run. See "
            f"`{_EXAMPLE_CONFIG_FILENAME}` for the recommended "
            "convention.\n"
            "  --no-check is a deliberate override of this guard, not a "
            "fix for this error: it scrubs anyway, leaving the config "
            "stageable."
        )
    # Anything else: not a git repo (128), broken index, etc. Treat as
    # "cannot check" rather than failing closed — the test suite and CI
    # legitimately run outside a git repo, and the convention layer +
    # hook layer cover this threat from other angles.
    stderr_excerpt = (result.stderr or "").strip().splitlines()
    detail = stderr_excerpt[0] if stderr_excerpt else f"exit {result.returncode}"
    print(
        f"ccs-sanitize: warning: `git check-ignore` could not evaluate "
        f"{config_path} ({detail}). Proceeding; pass --no-check to "
        "skip this guard.",
        file=sys.stderr,
    )


def _discover_config(explicit: Path | None, input_path: Path) -> Path:
    """Resolve the config path by PRD section 11 precedence.

    Precedence: ``--config`` explicit > CWD ``./.ccs-sanitize.yaml`` >
    ``<input_dir>/.ccs-sanitize.yaml``. An explicit path is returned without
    checking existence (``load_config`` raises ``FileNotFoundError``, which
    the caller maps to exit 1). For the discovery path, a missing config in
    every candidate is a ``_UsageError`` (exit 1) — the user did not point
    us at a valid file and none of the defaults exist.
    """
    if explicit is not None:
        return explicit
    candidates = [
        Path.cwd() / _CONFIG_FILENAME,
        input_path.parent / _CONFIG_FILENAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise _UsageError(
        f"no config file found via discovery (looked for: "
        f"{', '.join(str(c) for c in candidates)}). Pass --config explicitly."
    )


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message, file=sys.stderr)


def _atomic_write_pair(
    *,
    output_path: Path,
    output_bytes: bytes,
    sidecar_path: Path,
    sidecar_text: str,
) -> None:
    """Write both files atomically with the I-5 rename ordering.

    Temp files live in the destination directory (same filesystem) so
    ``os.replace`` is atomic. The sidecar is renamed FIRST, then the
    output. A crash in the gap leaves an orphan sidecar (harmless,
    overwritten on the next run); never a scrubbed output without a
    sidecar. On any error before both renames complete, leftover temp
    files are unlinked.

    The two temp paths are tracked separately so cleanup is precise: if
    the sidecar rename succeeds but the output rename fails, the sidecar
    temp is already gone (rename consumed it) and only the output temp
    needs unlinking. The function does not try to undo the sidecar
    rename — the orphan-sidecar invariant says leaving it is fine.
    """
    output_dir = output_path.parent
    sidecar_temp: Path | None = None
    output_temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(output_dir),
            prefix=output_path.name + ".tmp.",
            delete=False,
        ) as handle:
            output_temp = Path(handle.name)
            handle.write(output_bytes)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(output_dir),
            prefix=sidecar_path.name + ".tmp.",
            delete=False,
        ) as handle:
            sidecar_temp = Path(handle.name)
            handle.write(sidecar_text)

        os.replace(sidecar_temp, sidecar_path)
        sidecar_temp = None  # consumed by rename
        os.replace(output_temp, output_path)
        output_temp = None  # consumed by rename
    finally:
        # Best-effort cleanup. Suppress every OSError (PermissionError, EBUSY,
        # FileNotFoundError on a race) so the original exception that
        # triggered the finally block — which is the diagnostic the user
        # actually needs — is the one that propagates.
        for leftover in (sidecar_temp, output_temp):
            if leftover is None:
                continue
            try:
                leftover.unlink()
            except OSError:
                pass


def _serialize_output(lines: Sequence[str]) -> bytes:
    """Join scrub output lines into the final file bytes.

    Each element from ``sanitize_session`` is one serialized JSONL record
    with no trailing newline. The file is joined with ``\\n`` and ends
    with a trailing newline (POSIX text-file convention; ``wc -l``
    correctness; ``cat | jq`` friendliness).
    """
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _validate_input(input_path: Path) -> None:
    """Reject inputs the sanitizer should not read.

    Uses ``lstat``-equivalent predicates (``is_symlink``, ``exists``) so a
    symlink whose target is a regular file is rejected explicitly: per
    CLAUDE.md security posture, the sanitizer is the sanctioned path from
    raw session JSONL to a committable fixture and that path is meant to
    be invoked against the underlying file directly, not via a symlink
    that could be redirected (TOCTOU is explicitly deferred but blanket
    symlink rejection costs nothing and removes the surface).
    """
    if not input_path.exists() and not input_path.is_symlink():
        raise _UsageError(f"input file not found: {input_path}")
    if input_path.is_symlink():
        raise _UsageError(
            f"input is a symlink (refusing to follow): {input_path}"
        )
    if not input_path.is_file():
        raise _UsageError(
            f"input is not a regular file (got directory/device): {input_path}"
        )


def _derive_sidecar_path(output_path: Path) -> Path:
    """Build ``<output>.scrubbed`` with an explicit empty-name guard.

    ``Path.with_name`` raises ``ValueError`` on an empty name; surface that
    as a usage error rather than letting it propagate as an unhandled
    traceback.
    """
    if not output_path.name:
        raise _UsageError(
            f"output has no filename component: {output_path}"
        )
    return output_path.with_name(output_path.name + ".scrubbed")


def _output_already_exists(path: Path) -> bool:
    """True if ``path`` resolves to anything on disk, including a dangling
    symlink. ``Path.exists`` returns False for dangling symlinks; the
    ``or is_symlink`` clause covers them so the --force guard cannot be
    bypassed by leaving a stale link at the destination.
    """
    return path.exists() or path.is_symlink()


def _reject_init_with_scrub_args(args: argparse.Namespace) -> None:
    """Raise ``_UsageError`` if ``--init`` is mixed with a scrub-only arg.

    Argparse cannot easily express "if --init then nothing else" at parse
    time, so the check lands here. The motivating case: a user runs
    ``ccs-sanitize --init session.jsonl -o out.jsonl`` expecting both
    init AND a scrub; before this guard, --init would silently win and
    the user would believe ``out.jsonl`` had been produced. ``--verbose``
    is allowed because it just gates extra stderr in ``_run_init``.
    """
    offending: list[str] = []
    if args.input is not None:
        offending.append("<input>")
    if args.output is not None:
        offending.append("-o/--output")
    if args.config is not None:
        offending.append("-c/--config")
    if args.dry_run:
        offending.append("--dry-run")
    if args.force:
        offending.append("--force")
    if args.no_check:
        offending.append("--no-check")
    if offending:
        raise _UsageError(
            f"--init cannot be combined with scrub arguments "
            f"({', '.join(offending)}). Run --init first to bootstrap "
            "the config, then invoke ccs-sanitize again to scrub."
        )


def _run(args: argparse.Namespace) -> int:
    """Inner CLI flow. Exceptions propagate to ``main`` for exit-code mapping."""
    # --init runs before the scrub-argument validation so a user can
    # bootstrap a fresh repo with just `ccs-sanitize --init`. To avoid the
    # "I thought I scrubbed but only init'd" trap, --init refuses to
    # accept any scrub-only argument: a user who passes both is almost
    # certainly expecting both to run, not one to be silently ignored.
    if args.init:
        _reject_init_with_scrub_args(args)
        return _run_init(args.verbose)

    if args.input is None:
        raise _UsageError("missing required argument: input")
    # --output is required for normal runs; under --dry-run we write nothing
    # so the user does not need to commit to an output path just to preview
    # the sidecar.
    if args.output is None and not args.dry_run:
        raise _UsageError("missing required argument: -o/--output")

    input_path: Path = args.input
    _validate_input(input_path)

    config_path = _discover_config(args.config, input_path)
    # PRD section 12b: refuse to scrub if the resolved config is not
    # gitignored. Runs BEFORE the output-existence check so a user
    # repeatedly hitting "output already exists" cannot keep using the
    # tool without ever being told their config would leak. The
    # gitignore check is cheap (one subprocess); the security message
    # must take precedence over the convenience message.
    if not args.no_check:
        _check_config_gitignored(config_path, args.verbose)

    output_path: Path | None = args.output
    sidecar_path: Path | None = (
        _derive_sidecar_path(output_path) if output_path is not None else None
    )

    # Resolve --force / existing-output BEFORE running the pipeline so the
    # user finds out about an unintended overwrite without paying the scrub
    # cost. Symmetric on sidecar_path: the sidecar is the audit record and
    # should not be silently clobbered either. Dry-run skips both checks --
    # it writes nothing.
    if not args.dry_run and not args.force:
        assert output_path is not None and sidecar_path is not None
        if _output_already_exists(output_path):
            raise _UsageError(
                f"output already exists (use --force to overwrite): {output_path}"
            )
        if _output_already_exists(sidecar_path):
            raise _UsageError(
                f"sidecar already exists (use --force to overwrite): {sidecar_path}"
            )

    _log(args.verbose, f"loading config: {config_path}")
    # Scope the FileNotFoundError catch tightly to load_config: re-raise as
    # _UsageError so the top-level handler maps it to exit 1 with a config-
    # specific diagnostic and is not confused with a FileNotFoundError from
    # the write path.
    try:
        config: Config = load_config(config_path)
    except FileNotFoundError as exc:
        raise _UsageError(f"config file not found: {exc}") from exc

    _log(args.verbose, f"reading input: {input_path}")
    try:
        input_bytes = input_path.read_bytes()
    except OSError as exc:
        raise _UsageError(f"cannot read input: {input_path} ({exc})") from exc
    try:
        input_text = input_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Malformed input is a safety condition on a security tool — exit 2.
        # PipelineError is the closest fit; wrap to keep the exit-code map clean.
        raise PipelineError(
            f"input is not valid UTF-8: {input_path} ({exc})"
        ) from exc

    # split('\n') instead of splitlines(): splitlines() also splits on
    # U+2028 / U+2029 / \v / \f / \x1c-\x1e / \x85, which a JSON string
    # value can legally contain raw under ensure_ascii=False. Treating
    # any of those as a record boundary would fragment one valid JSONL
    # record into two non-parseable halves. JSONL records are separated
    # by LF/CRLF only; the pipeline already tolerates blank lines, so a
    # trailing empty element from a newline-terminated file is fine.
    lines = input_text.split("\n")
    _log(args.verbose, f"input lines: {len(lines)}")

    _log(args.verbose, "running pipeline")
    serialized, counts, subtable, secret_counts = sanitize_session(
        lines, config, strip_types=args.strip_types
    )
    _log(args.verbose, f"output lines: {len(serialized)} (residual scan: clean)")

    metadata = SidecarMetadata(
        input_filename=input_path.name,
        input_sha256=sha256_hex(input_bytes),
        config_source=config_path.name,
        scrubbed_at=utc_now_iso8601(),
    )
    _log(args.verbose, "building sidecar")
    sidecar_text = build_sidecar(
        metadata=metadata,
        config=config,
        serialized_lines=serialized,
        counts=counts,
        subtable=subtable,
        secret_counts=secret_counts,
    )

    if args.dry_run:
        sys.stdout.write(sidecar_text)
        if not sidecar_text.endswith("\n"):
            sys.stdout.write("\n")
        _log(args.verbose, "dry-run: nothing written to disk")
        return 0

    assert output_path is not None and sidecar_path is not None
    output_bytes = _serialize_output(serialized)
    _log(args.verbose, f"writing temp files in {output_path.parent}")
    try:
        _atomic_write_pair(
            output_path=output_path,
            output_bytes=output_bytes,
            sidecar_path=sidecar_path,
            sidecar_text=sidecar_text,
        )
    except OSError as exc:
        # ENOSPC, EROFS, PermissionError, NotADirectoryError, missing
        # output dir all land here. These are environment failures, not
        # safety failures -- map to exit 1 at main(). Re-raise as
        # _UsageError so the message names the actual destination
        # instead of a random tempfile path.
        raise _UsageError(
            f"cannot write output ({type(exc).__name__}): {output_path} ({exc})"
        ) from exc
    _log(args.verbose, f"renamed sidecar -> {sidecar_path}")
    _log(args.verbose, f"renamed output  -> {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except _UsageError as exc:
        # All usage-level conditions (bad args, missing input/config file,
        # output exists without --force, environment write failures) land
        # here. ``load_config``'s ``FileNotFoundError`` is rewrapped to
        # _UsageError inside _run so a stray FileNotFoundError from elsewhere
        # in the pipeline does not get reported as "config file not found".
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 1
    except ConfigError as exc:
        print(f"{parser.prog}: config error: {exc}", file=sys.stderr)
        return 3
    except (PipelineError, ResidualSecretError, SidecarLeakError) as exc:
        # D-2 invariant: ResidualSecretError and SidecarLeakError carry only
        # category labels, never the matched bytes. Printing str(exc) is safe.
        print(f"{parser.prog}: safety failure: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive catch-all
        # Defense-in-depth: any unexpected exception falls through to exit 2
        # (safety failure) rather than printing a traceback that may carry
        # local-variable bytes from a real session. The exception class name
        # is included so a debugger has something to start from; the message
        # itself comes from str(exc) and is printed only because every typed
        # exception we raise structurally guards against putting originals
        # in str().
        print(
            f"{parser.prog}: safety failure ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
