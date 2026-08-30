"""Adversarial placement matrix: does scrubbing depend on WHERE a value sits?

The rest of this suite covers what a sensitive value looks like -- every
Tier-1/Tier-2 pattern, every rule layer -- with the value in a
straightforward position. This module varies the other axis. It plants one
value at each of 19 structural positions in a session line and asserts the
outcome is the same everywhere. (That count is pinned by
``test_module_docstring_cell_count_is_current`` -- it went stale once when
cells 15-19 landed, which is the whole reason the pin exists.)

WHAT THIS MODULE IS NOT. It is not the leak gate. Enumerating positions
cannot be one: the position space is tool-defined and open (MCP servers
define their own input schemas, and `toolUseResult` bodies are arbitrary),
so a hand-authored list covers what its author thought of and nothing more.
This module demonstrated that itself -- it was built to map positional
coverage and missed #194 entirely, because cells 01-14 plant payloads under
innocuous key names (`command`, `outer.middle.inner`, `args`) and never
collided with a skip-listed name. Cells 15-19 were added when #194 was fixed
and close that specific gap: one cell per skip MECHANISM, since the
mechanisms failed independently. They do not make the module a leak gate --
the paragraph above still holds -- they remove one blind spot that was known
by name.

The guarantee lives in #195: an output-side check for the **literal**
path/identifier rules, mirroring what `scan_residual` already does for
secrets. #198 extended it to `re:` rules at reachable VALUE positions only --
dict keys stay regex-uncovered (#208), as does any skip-listed position -- so
this net still covers positions the oracle does not speak for. This module is
the coverage net BEHIND that guarantee -- it
tells you which positions are scrubbable, where the oracle only tells you
that nothing leaked.

Verdict vocabulary, and why the assertion is exact:

  REDACTED     Output written, exit 0, value gone. The ONLY passing verdict.
  FAIL-CLOSED  Exit 2 (PRD section 11 safety failure) and no output. Safe,
               but degraded: the transform missed and the residual scan
               caught it. Never a pass for `test_placement_is_redacted` --
               but it IS the asserted outcome for the cells in
               FAIL_CLOSED_BY_DESIGN, where it is the design and not a miss.
  ERROR-<rc>   Any other nonzero exit with no output. A broken CLI, not a
               safety outcome.
  LEAKED       Output written, exit 0, value present. The unacceptable one.

Asserting `verdict == "REDACTED"` rather than `verdict in {REDACTED,
FAIL-CLOSED}` is load-bearing. The permissive form was in the first version
of this file and it meant a stub binary consisting of `echo boom >&2; exit
1` passed 54 of 57 assertions, because every cell read as FAIL-CLOSED and
FAIL-CLOSED read as safe. Ordinary regressions produce exactly that shape:
a renamed flag (exit 1), a config-schema change (exit 3), a re-run hitting
`output already exists` (exit 1). Every departure from REDACTED is
therefore explicit and issue-tagged rather than a blanket allowance, in one
of two forms that must not be confused:

  KNOWN_DEVIATIONS      a position that SHOULD redact and does not yet.
                        `xfail(strict=True)`, so the fix turns it red.
  FAIL_CLOSED_BY_DESIGN a position that is fail-closed on purpose. Asserted
                        POSITIVELY as `== "FAIL-CLOSED"`, because a strict
                        xfail on "expected REDACTED" is satisfied by LEAKED
                        just as well as by FAIL-CLOSED -- so it cannot tell a
                        safe abort from the leak this module exists to catch.

Why this drives the console script instead of importing the orchestrator:
PRD D-5a declares the module surface private and the CLI + sidecar the
supported contract, so testing through ``ccs-sanitize`` tests the thing
that is actually promised. It also means one file covers two targets. Run
from a checkout it exercises the source tree; run from the unpacked sdist
with the wheel's entry point on PATH (or via ``CCS_SANITIZE_BIN``) it
exercises the published artifact. This matrix found #190 against the wheel
installed from PyPI, not against a checkout.

The verdict considers BOTH files the CLI writes. `-o out.jsonl` produces
`out.jsonl` and `out.jsonl.scrubbed`, and per CLAUDE.md the sidecar is a
committed artifact for every sanitized fixture. `SidecarLeakError` exists
because originals reaching the sidecar is a live risk, so "the value is
gone from the output" has to mean both files or it means very little.

No credential-shaped literal appears in this file -- every payload is built
by concatenation, matching ``test_residual.py``. Matched values are never
printed, per the D-2 invariant.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.adversarial

# --------------------------------------------------------------- payloads
# Built piecewise so no key-shaped literal exists in this source file and
# the file cannot match its own detectors.
SECRET = "sk-" + "ant-" + ("Q7x" * 9)
HOME = "/home/" + "testsubject"
EMAIL = "test" + ".person@" + "example.net"
NAME = "Testy " + "McTestface"
# #198's payload family. Every other payload above is matched by a LITERAL
# rule, so before this entry existed the matrix could not observe the `re:`
# class in ANY cell -- the oracle treated the two kinds differently and no cell
# exercised the difference. Distinct from HOME on purpose (`regex` vs `test`
# infix) so the two families cannot be scrubbed by each other's rule, which
# would make this one inert while looking covered.
REGEX_HOME = "/home/" + "regexsubject"

# The secret is caught by a built-in pattern and needs no config. The four
# PII payloads are config-driven, which used to be the asymmetry #190 was
# about: nothing re-scanned the output for those after the fact. **#195 closed
# that for LITERAL rules** -- `scan_residual_rules` re-runs them over the
# decoded output, keys included -- and **#198 closed it for `re:` rules at
# reachable VALUE positions**. Two things stay uncovered for a `re:` config,
# and the matrix shows both: skip-listed positions (#194's documented
# residual), and DICT KEYS (#208) -- which is why the `pii-regex` entry in
# KNOWN_DEVIATIONS below is a LEAK while the other four payloads at that cell
# -- the three config-driven literal ones and the built-in `secret` -- are
# FAIL_CLOSED_BY_DESIGN refusals.
PAYLOADS = {
    "secret": SECRET,
    "pii-home": HOME,
    "pii-email": EMAIL,
    "pii-name": NAME,
    "pii-regex": REGEX_HOME,
}

CONFIG = f"""version: 1
paths:
  - match: "{HOME}"
    replace: "/home/user"
  - match: "re:/home/regex[a-z]+"
    replace: "/home/user"
identifiers:
  - match: "{EMAIL}"
    replace: "user@example.com"
  - match: "{NAME}"
    replace: "Example Author"
"""

BASE = {
    "sessionId": "00000000-0000-0000-0000-0000000000aa",
    "uuid": "11111111-1111-1111-1111-1111111111aa",
    "parentUuid": None,
    "isSidechain": False,
    "cwd": "/home/user/proj",
    "version": "2.1.150",
    "timestamp": "2026-08-19T00:00:00.000Z",
}

# Cells that SHOULD redact and do not yet, with the issue that tracks each and
# the reason. Keyed (cell, payload_label); the value carries its own
# explanation so a second entry cannot inherit the first one's wording. Every
# entry is a strict xfail: when the tracked issue is fixed the cell starts
# passing, the strict xfail turns red, and whoever fixed it is forced to remove
# the entry rather than leaving a stale exemption behind.
#
# THIS IS THE WRONG MAPPING FOR A CELL THAT IS FAIL-CLOSED BY DESIGN -- use
# FAIL_CLOSED_BY_DESIGN below. The distinction is not bookkeeping: a strict
# xfail here asserts only "not REDACTED", and FAIL-CLOSED and LEAKED both
# satisfy that, so an entry parked here cannot tell a safe abort from a leak.
# The four `13-dict-key-not-value` entries -- the three PII payloads AND the
# secret one -- used to live here for exactly that reason and moved out in
# #190. Do not move them back.
KNOWN_DEVIATIONS: dict[tuple[str, str], tuple[int, str]] = {
    # The four LITERAL `13-dict-key-not-value` entries that lived here moved to
    # FAIL_CLOSED_BY_DESIGN below when #190 was scoped to detect-only; see that
    # mapping for why an xfail was the wrong shape for them.
    #
    # The one entry that belongs HERE rather than there is the regex payload,
    # and the distinction is exactly the one this file is careful about: the
    # literal payloads FAIL CLOSED at this cell (the oracle catches them and the
    # run aborts), while the regex payload LEAKS -- exit 0, the value in the
    # written output, sidecar reporting clean. Those are different verdicts and
    # must not share a mapping.
    ("13-dict-key-not-value", "pii-regex"): (
        208,
        "dict keys are never transformed, and the #198 oracle does not scan "
        "keys for `re:` rules -- gating them on the skip allow-list aborted 8 "
        "of 8 fixture files on format key names like `input_tokens`, since that "
        "list enumerates string LEAVES and exempts no key. So both layers miss "
        "this position for a regex config and the value is WRITTEN, not "
        "refused. Closing it needs the key position to become visitable, which "
        "is #208",
    ),
}


# Positions that are fail-closed BY DESIGN, not pending a fix (#190, #208).
#
# WHY THESE ARE NOT `KNOWN_DEVIATIONS` ENTRIES, which is the whole point of
# AC-2: a strict xfail on `test_placement_is_redacted` asserts only that the
# cell is NOT REDACTED. `_classify` returns "FAIL-CLOSED" for a safe abort and
# "LEAKED" for a written output still carrying the payload -- and BOTH fail the
# `== "REDACTED"` assertion, so both satisfy the xfail. A regression from
# FAIL-CLOSED to LEAKED at these cells would have been reported as an expected
# failure and gone unnoticed.
#
# The secret payload was already covered: `test_secret_never_survives_any_
# placement` asserts REDACTED-or-FAIL-CLOSED over every cell unconditionally.
# The three PII payloads had NO positive assertion at all, which is the hole
# this mapping closes.
#
# These cells stay fail-closed until #208 makes the key position scrubbable.
# When it does, this mapping is what goes red and forces the update -- the same
# forcing function the strict xfail provided, now pointed at the right verdict.
FAIL_CLOSED_BY_DESIGN: dict[tuple[str, str], tuple[int, str]] = {
    ("13-dict-key-not-value", "pii-home"): (
        208,
        "dict keys are never transformed, so a config-driven rule cannot "
        "reach this position. #195's output-side oracle catches the survivor "
        "and aborts (exit 2, nothing written). #190 was scoped to detect-only, "
        "so this is the designed outcome, not a pending fix: the file is safe "
        "and deliberately not publishable. #208 carries the scrub work",
    ),
    ("13-dict-key-not-value", "pii-email"): (
        208,
        "dict keys are never transformed, so a config-driven rule cannot "
        "reach this position. #195's output-side oracle catches the survivor "
        "and aborts (exit 2, nothing written). #190 was scoped to detect-only, "
        "so this is the designed outcome, not a pending fix: the file is safe "
        "and deliberately not publishable. #208 carries the scrub work",
    ),
    ("13-dict-key-not-value", "pii-name"): (
        208,
        "dict keys are never transformed, so a config-driven rule cannot "
        "reach this position. #195's output-side oracle catches the survivor "
        "and aborts (exit 2, nothing written). #190 was scoped to detect-only, "
        "so this is the designed outcome, not a pending fix: the file is safe "
        "and deliberately not publishable. #208 carries the scrub work",
    ),
    ("13-dict-key-not-value", "secret"): (
        208,
        "dict keys are never transformed, so the secret transform misses it "
        "and `scan_residual` catches it instead -- safe, but degraded. Unlike "
        "the three PII cells this one was already positively asserted by "
        "test_secret_never_survives_any_placement; it is listed here so the "
        "cell's literal payloads carry one consistent explanation. The fifth, "
        "`pii-regex`, is NOT here: its verdict is LEAKED, not FAIL-CLOSED, so "
        "it sits in KNOWN_DEVIATIONS with a positive verdict assertion of its "
        "own",
    ),
}


def placements(payload: str) -> dict[str, dict]:
    """Return ``{cell_id: session_line}`` with ``payload`` planted in each spot."""

    def rec(**kw: object) -> dict:
        d = dict(BASE)
        d.update(kw)
        return d

    return {
        # Controls: shapes the rest of the suite already reaches.
        "01-user-content-string": rec(
            type="user",
            message={"role": "user", "content": f"see {payload} here"},
        ),
        "02-assistant-text-block": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": f"got {payload}"}],
            },
        ),
        # The placement gap starts here.
        "03-tool-use-input-flat": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_a",
                        "name": "Bash",
                        "input": {"command": f"export TOKEN={payload}"},
                    }
                ],
            },
        ),
        "04-tool-use-input-nested-3-deep": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_b",
                        "name": "X",
                        "input": {"outer": {"middle": {"inner": payload}}},
                    }
                ],
            },
        ),
        "05-tool-use-input-array-of-strings": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_c",
                        "name": "X",
                        "input": {"args": ["--flag", payload, "--other"]},
                    }
                ],
            },
        ),
        "06-tool-result-string": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": f"out: {payload}",
                    }
                ],
            },
        ),
        "07-tool-result-content-array": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": [{"type": "text", "text": f"out: {payload}"}],
                    }
                ],
            },
        ),
        "08-tooluseresult-sibling-field": rec(
            type="user",
            message={"role": "user", "content": "ok"},
            toolUseResult={
                "stdout": f"printed {payload}",
                "stderr": "",
                "exitCode": 0,
            },
        ),
        "09-thinking-block": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": f"the value is {payload}",
                        "signature": "sig",
                    }
                ],
            },
        ),
        "10-multiline-buried-line-3": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": "line one\nline two\nline three has "
                        + payload
                        + "\nline four",
                    }
                ],
            },
        ),
        "11-json-encoded-inside-a-string": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": json.dumps({"config": {"key": payload}}),
                    }
                ],
            },
        ),
        "12-adjacent-to-quotes-and-punctuation": rec(
            type="user",
            message={"role": "user", "content": f'{{"k":"{payload}","n":1}}'},
        ),
        "13-dict-key-not-value": rec(
            type="user",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_a",
                        "content": {payload: "this value is innocuous"},
                    }
                ],
            },
        ),
        "14-url-query-parameter": rec(
            type="user",
            message={
                "role": "user",
                "content": (
                    f"curl https://api.example.com/v1?token={payload}&x=1"
                ),
            },
        ),
        # ----- the payload family this module was missing (#194) ----------
        #
        # Cells 03/04/05 plant payloads under innocuous keys (`command`,
        # `outer.middle.inner`, `args`), so no cell in the matrix ever
        # COLLIDED with a skip-listed name -- which is precisely why this
        # module was built to map placement coverage and still missed #194.
        # Each cell below is a different skip MECHANISM, not a different
        # name, because the mechanisms failed independently.
        "15-tool-use-input-bare-skip-name": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_d",
                        "name": "X",
                        # A tool whose parameter is a version pin. `version`
                        # was skipped at any depth as a "line-level format
                        # marker".
                        "input": {"version": payload},
                    }
                ],
            },
        ),
        "16-tool-use-input-uuid-name": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_e",
                        "name": "X",
                        # `sessionId` was skipped bare while remap_uuids is
                        # off -- which is the default.
                        "input": {"sessionId": payload},
                    }
                ],
            },
        ),
        "17-tool-use-input-tokens-suffix": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_f",
                        "name": "X",
                        # The broadest of the old rules: a SUFFIX, not a name
                        # list, so it exempted a name nobody enumerated.
                        # `max_tokens` is a real parameter on a real API.
                        "input": {"max_tokens": payload},
                    }
                ],
            },
        ),
        "18-tool-use-input-anchored-pair": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_g",
                        "name": "X",
                        # `_ANCHORED_PARENT_LAST_SKIPS` matched the immediate
                        # parent name at ANY depth, so a tool input holding a
                        # `content` object with an `id` landed on exactly the
                        # position its own comment warned about.
                        "input": {"content": {"id": payload}},
                    }
                ],
            },
        ),
        "19-tool-use-input-usage-child": rec(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_h",
                        "name": "X",
                        # The `parent == "usage"` rule. Note the leak was one
                        # level BELOW the `usage` key: `input.usage` was
                        # visited, `input.usage.*` was not.
                        "input": {"usage": {"detail": payload}},
                    }
                ],
            },
        ),
    }


CELLS = sorted(placements("PLACEHOLDER"))


def _resolve_entry_point() -> list[str]:
    """Resolve the CLI under test, as an argv prefix. Called once, at import.

    Three tiers, in descending order of how much they prove:

      1. ``CCS_SANITIZE_BIN`` -- CI points this at a specific artifact (the
         wheel installed into a clean venv) rather than whatever the test
         environment happens to have on PATH. This is the tier that makes
         the matrix evidence about the published package.
      2. ``ccs-sanitize`` on PATH -- the console script, wherever it lives.
      3. ``python -m ccs_sanitize.cli`` -- the module entry point.

    The override is validated rather than trusted. Returning an unchecked
    path meant a stale or misspelled value produced one identical
    ``FileNotFoundError`` traceback per cell out of ``subprocess.run``
    instead of one line saying the override was wrong.

    Tier 3 exists so this module cannot silently skip where the package is
    importable, and exhausting all three raises rather than skips. It is NOT
    a safety net in CI's `package` job, where nothing installs
    ``ccs_sanitize`` into the runner interpreter -- there, only tier 1 can
    resolve. That is why the workflow asserts on the pytest output rather
    than trusting the exit code; see the "Run the placement matrix against
    the built wheel" step.
    """
    override = os.environ.get("CCS_SANITIZE_BIN")
    if override:
        path = pathlib.Path(override)
        if not path.is_file():
            raise RuntimeError(
                f"CCS_SANITIZE_BIN={override!r} is not a file. Point it at a "
                f"ccs-sanitize executable, or unset it to fall back to PATH."
            )
        if not os.access(path, os.X_OK):
            raise RuntimeError(
                f"CCS_SANITIZE_BIN={override!r} is not executable."
            )
        return [str(path)]
    found = shutil.which("ccs-sanitize")
    if found is not None:
        return [found]
    if importlib.util.find_spec("ccs_sanitize") is None:
        # Deliberately an error, not a skip. A skip here would drop EVERY
        # placement assertion in this module and still report green -- and the
        # rest of this
        # suite imports ccs_sanitize directly, so an environment that cannot
        # provide it is broken rather than merely unsuitable.
        raise RuntimeError(
            "ccs-sanitize is not on PATH and ccs_sanitize is not importable, "
            "so the placement matrix has nothing to test. Install the package "
            "(`pip install -e ./tooling/sanitizer[dev]`) or set "
            "CCS_SANITIZE_BIN to a built artifact."
        )
    return [sys.executable, "-m", "ccs_sanitize.cli"]


ENTRY_POINT = _resolve_entry_point()


def _classify(work: pathlib.Path, cell: str, line: dict, payload: str) -> str:
    """Run one cell and return its verdict. Never returns the payload.

    The verdict distinguishes exit 2 from every other nonzero exit. PRD
    section 11 reserves exit 2 for safety failures, so exit 2 with no output
    is a genuine fail-closed abort, while any other nonzero exit is a broken
    invocation wearing the same clothes. Collapsing the two is what let a
    stub that only ran ``exit 1`` pass 54 of 57 assertions.
    """
    work.mkdir(parents=True, exist_ok=True)
    cfg = work / "cfg.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    src = work / "in.jsonl"
    src.write_text(json.dumps(line) + "\n", encoding="utf-8")
    out = work / "out.jsonl"
    sidecar = work / "out.jsonl.scrubbed"

    # --no-check is the documented test-suite override of the pre-run
    # gitignore guard (PRD section 12b). tmp dirs are normally outside any
    # repository, where the guard would warn and proceed anyway, but pinning
    # it keeps the verdict independent of where TMPDIR points. The guard
    # itself is covered by test_init_and_check.py.
    proc = subprocess.run(
        [*ENTRY_POINT, str(src), "-o", str(out), "-c", str(cfg), "--no-check"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if not out.exists():
        if proc.returncode == 2:
            return "FAIL-CLOSED"
        if proc.returncode == 0:
            return "NO-OUTPUT"
        return f"ERROR-{proc.returncode}"

    # "Gone from the output" has to mean both files the CLI writes, or a
    # regression that echoes an original into the sidecar reads as clean.
    written = out.read_text(encoding="utf-8")
    if sidecar.exists():
        written += sidecar.read_text(encoding="utf-8")
    if payload in written:
        return "LEAKED"
    return "REDACTED" if proc.returncode == 0 else f"CLEAN-BUT-{proc.returncode}"


@pytest.fixture(scope="session")
def verdicts(tmp_path_factory) -> dict[tuple[str, str], str]:
    """Every cell's verdict, computed once for the whole session.

    Previously each test spawned its own subprocess and a second test
    re-ran every secret cell, so the slowest module in the suite paid for
    roughly one extra spawn per secret cell on top of the matrix. (The
    absolute figures that used to sit here were written when the matrix had
    14 cells and went stale at 19; the shape is the point, not the numbers.)
    Session scope also means a broken entry point surfaces once rather than
    once per cell.
    """
    root = tmp_path_factory.mktemp("placement")
    out: dict[tuple[str, str], str] = {}
    for label, payload in PAYLOADS.items():
        cells = placements(payload)
        for cell in CELLS:
            out[(label, cell)] = _classify(
                root / label / cell, cell, cells[cell], payload
            )
    return out


def _params():
    for label in PAYLOADS:
        for cell in CELLS:
            if (cell, label) in FAIL_CLOSED_BY_DESIGN:
                # Not a deviation from REDACTED awaiting a fix, so not an
                # xfail. Asserted positively by
                # test_fail_closed_by_design_cells_actually_fail_closed.
                continue
            entry = KNOWN_DEVIATIONS.get((cell, label))
            marks = ()
            if entry is not None:
                issue, why = entry
                marks = pytest.mark.xfail(
                    strict=True,
                    reason=(
                        f"#{issue}: {why}. Strict, so fixing #{issue} turns "
                        f"this red and forces the entry out of "
                        f"KNOWN_DEVIATIONS."
                    ),
                )
            yield pytest.param(label, cell, marks=marks, id=f"{label}:{cell}")


@pytest.mark.parametrize("label,cell", list(_params()))
def test_placement_is_redacted(verdicts, label: str, cell: str) -> None:
    """Every structural position must scrub cleanly.

    Exact equality, not membership in a set of acceptable outcomes. See the
    module docstring for why the permissive form was a hollow gate.

    Asserting on the verdict rather than on output bytes keeps this stable
    across the jitter work planned for v1 (PRD section 9b); byte-exactness
    is owned by test_golden_determinism.py.
    """
    verdict = verdicts[(label, cell)]
    assert verdict == "REDACTED", (
        f"cell {cell} with {label} returned {verdict}, expected REDACTED. "
        f"If this is a newly-accepted deviation it needs an issue-tagged "
        f"entry in KNOWN_DEVIATIONS, not a widened assertion."
    )


def test_controls_are_positively_redacted(verdicts) -> None:
    """Positive control: the two ordinary positions must actually scrub.

    Guards the failure mode where every cell fails closed (or errors) and
    the module still looks meaningful. If the CLI under test is a brick,
    this is the assertion that says so in one line rather than once per cell.
    """
    for label in PAYLOADS:
        for cell in ("01-user-content-string", "02-assistant-text-block"):
            assert verdicts[(label, cell)] == "REDACTED", (
                f"control cell {cell} with {label} is "
                f"{verdicts[(label, cell)]}; the CLI under test is not "
                f"scrubbing at all"
            )


def test_secret_never_survives_any_placement(verdicts) -> None:
    """The fail-closed contract, stated once over the whole matrix.

    Separate from the parametrized test because this is the property the
    residual scan (PRD section 5) promises unconditionally: a secret is
    either scrubbed or the run writes nothing, regardless of where it sits.
    No cell may be exempted -- if this ever needs an entry in
    KNOWN_DEVIATIONS, the entry is the bug.
    """
    bad = {
        cell: verdicts[("secret", cell)]
        for cell in CELLS
        if verdicts[("secret", cell)] not in {"REDACTED", "FAIL-CLOSED"}
    }
    assert not bad, f"secret reached a written output or a broken exit at: {bad}"


@pytest.mark.parametrize(
    "cell,label",
    sorted(FAIL_CLOSED_BY_DESIGN),
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_fail_closed_by_design_cells_actually_fail_closed(
    verdicts, cell: str, label: str
) -> None:
    """#190 AC-2. Assert the verdict these cells DO have, not merely that it
    is not REDACTED.

    The strict xfail these entries used to carry asserted `not REDACTED`, and
    `_classify` has two non-REDACTED verdicts that mean opposite things:
    FAIL-CLOSED (exit 2, nothing written -- safe) and LEAKED (output written,
    payload present -- the thing the whole module exists to catch). Both fail
    the `== "REDACTED"` assertion, so both satisfied the xfail. A regression
    from FAIL-CLOSED to LEAKED at these cells was reported as an expected
    failure.

    Exact equality, for the reason the module docstring gives about the
    permissive form: ERROR-<rc> from a broken invocation must not read as a
    safety outcome either.
    """
    verdict = verdicts[(label, cell)]
    issue, why = FAIL_CLOSED_BY_DESIGN[(cell, label)]
    assert verdict == "FAIL-CLOSED", (
        f"cell {cell} with {label} returned {verdict}, expected FAIL-CLOSED. "
        f"If #{issue} made this position scrubbable for this payload, the "
        f"verdict is now REDACTED: delete this entry from "
        f"FAIL_CLOSED_BY_DESIGN so the cell rejoins "
        f"test_placement_is_redacted. Note #{issue} leaves it explicitly "
        f"undecided whether keys run the SECRET layer too, so the `secret` "
        f"payload may legitimately stay FAIL-CLOSED while the PII payloads "
        f"move. If the verdict is LEAKED, that is the leak this "
        f"module exists to catch. ({why})"
    )


# Cells whose CURRENT verdict is LEAKED and which are tracked rather than fixed.
# Separate from KNOWN_DEVIATIONS' strict xfail on purpose: that xfail asserts only
# `!= REDACTED`, which FAIL-CLOSED, ERROR-<rc> and LEAKED all satisfy -- the exact
# critique this module makes of the permissive form everywhere else. Without a
# positive assertion a silent move from LEAKED to FAIL-CLOSED (or to a broken
# invocation) would go unnoticed, and so would the cell being quietly fixed.
KNOWN_LEAK_VERDICTS: dict[tuple[str, str], int] = {
    ("13-dict-key-not-value", "pii-regex"): 208,
}


@pytest.mark.parametrize(
    "cell,label",
    sorted(KNOWN_LEAK_VERDICTS),
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_known_leak_cells_have_exactly_the_leaked_verdict(
    verdicts, cell: str, label: str
) -> None:
    """Pin the verdict a known-leaking cell actually has.

    This is the LEAKED counterpart to
    ``test_fail_closed_by_design_cells_actually_fail_closed``, and it exists for
    the same reason: the entry in KNOWN_DEVIATIONS records that the cell should
    redact and does not, but its strict xfail cannot say *how* it fails. Asserting
    the verdict exactly means three distinct futures are all visible -- the cell
    getting fixed (REDACTED), the cell degrading differently (ERROR-<rc>), and the
    cell being made safe-but-unscrubbable (FAIL-CLOSED, which #208 might well
    choose as a first step).

    Asserting a LEAK as the expected value is uncomfortable, and deliberately so:
    the discomfort is the point of tracking it in a mapping with an issue number
    rather than leaving it to an xfail that cannot tell a leak from a refusal.
    """
    verdict = verdicts[(label, cell)]
    issue = KNOWN_LEAK_VERDICTS[(cell, label)]
    assert verdict == "LEAKED", (
        f"cell {cell} with {label} returned {verdict}, not the LEAKED verdict "
        f"recorded here. If #{issue} closed it the verdict is REDACTED and this "
        f"entry plus the KNOWN_DEVIATIONS entry both come out. If it is now "
        f"FAIL-CLOSED the position became refusable without becoming scrubbable, "
        f"which is a real improvement that still needs both entries updated."
    )


def test_no_cell_is_both_a_deviation_and_fail_closed_by_design() -> None:
    """The two mappings partition; an overlap would silently win one way.

    A cell in both would be skipped by `_params` (so its xfail never applies)
    AND asserted FAIL-CLOSED -- readable as either, which is how a tracked
    deviation quietly becomes something else.
    """
    overlap = set(KNOWN_DEVIATIONS) & set(FAIL_CLOSED_BY_DESIGN)
    assert not overlap, f"cells listed in both mappings: {overlap}"


def test_module_docstring_cell_count_is_current() -> None:
    """The docstring's cell count is a claim, so pin it like any other.

    It said "~14 structural positions" for the whole life of cells 15-19 --
    a number describing the module one revision back, sitting in the first
    paragraph a reader sees. Cheap to pin, and the failure message says
    exactly what to edit."""
    assert __doc__ is not None
    expected = f"{len(CELLS)} structural positions"
    assert expected in __doc__, (
        f"this module's docstring does not say {expected!r}. CELLS changed "
        f"size to {len(CELLS)}; update the first paragraph to match."
    )


def test_deviation_mappings_reference_real_cells() -> None:
    """A cell rename must not silently detach an entry in EITHER mapping.

    KNOWN_DEVIATIONS is consulted with .get(), so a renamed cell id makes an
    entry stop matching, silently turning a tracked known-leak into an
    untracked one with no signal. FAIL_CLOSED_BY_DESIGN fails louder but
    worse -- see the comment below.
    """
    for name, mapping in (
        ("KNOWN_DEVIATIONS", KNOWN_DEVIATIONS),
        # FAIL_CLOSED_BY_DESIGN is consulted with `in` by `_params`, so a
        # renamed cell there does not merely stop matching -- the cell silently
        # rejoins test_placement_is_redacted and starts asserting REDACTED at a
        # position that cannot redact. Same failure shape, louder consequence.
        ("FAIL_CLOSED_BY_DESIGN", FAIL_CLOSED_BY_DESIGN),
    ):
        unknown_cells = {c for c, _ in mapping} - set(CELLS)
        assert not unknown_cells, f"{name} names cells that do not exist: {unknown_cells}"
        unknown_labels = {l for _, l in mapping} - set(PAYLOADS)
        assert not unknown_labels, f"{name} names payloads that do not exist: {unknown_labels}"
