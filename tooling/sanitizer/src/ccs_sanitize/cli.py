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
import sys
import tempfile
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
    parser = _SafeArgumentParser(
        prog="ccs-sanitize",
        description=(
            "Scrub a Claude Code session JSONL file for safe publication. "
            "See PRD: .claude/specs/prd-sanitizer.md"
        ),
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


def _run(args: argparse.Namespace) -> int:
    """Inner CLI flow. Exceptions propagate to ``main`` for exit-code mapping."""
    if args.input is None:
        raise _UsageError("missing required argument: input")
    # --output is required for normal runs; under --dry-run we write nothing
    # so the user does not need to commit to an output path just to preview
    # the sidecar.
    if args.output is None and not args.dry_run:
        raise _UsageError("missing required argument: -o/--output")

    input_path: Path = args.input
    _validate_input(input_path)

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

    config_path = _discover_config(args.config, input_path)
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
