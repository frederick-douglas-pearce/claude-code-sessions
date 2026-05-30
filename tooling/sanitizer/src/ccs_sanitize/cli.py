"""CLI entry point for `ccs-sanitize`.

PRD reference: section 11 (CLI shape & fail-closed behavior).

Exit codes (defined in PRD section 11):

    0 — success
    1 — usage error (bad args, missing input, output exists without --force)
    2 — safety failure (rule raised, malformed line, residual scan found a secret)
    3 — config error

argparse's default behavior on parse errors is `sys.exit(2)`. Because exit
code 2 is reserved for safety failures on this tool, the parser overrides
`error()` to exit 1 instead. Conflating "bad CLI args" with "a secret survived
redaction" would be a meaningful regression on a security tool.

Scaffold scope (issue #18): only `--version` is wired. The full flag surface
arrives with the CLI implementation story (#26).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


class _SafeArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that exits 1 on usage errors instead of argparse's
    default 2 — exit code 2 is reserved for safety failures (PRD section 11)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
