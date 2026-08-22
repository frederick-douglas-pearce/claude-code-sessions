"""Adversarial placement matrix: does scrubbing depend on WHERE a value sits?

The rest of this suite covers what a sensitive value looks like -- every
Tier-1/Tier-2 pattern, every rule layer -- with the value in a
straightforward position. This module varies the other axis. It plants one
value at each of ~14 structural positions in a session line and asserts the
outcome is the same everywhere.

WHAT THIS MODULE IS NOT. It is not the leak gate. Enumerating positions
cannot be one: the position space is tool-defined and open (MCP servers
define their own input schemas, and `toolUseResult` bodies are arbitrary),
so a hand-authored list covers what its author thought of and nothing more.
This module demonstrated that itself -- it was built to map positional
coverage and missed #194 entirely, because its cells plant payloads under
innocuous key names and never collide with a skip-listed name.

The guarantee lives in #195: an output-side check for the **literal**
path/identifier rules, mirroring what `scan_residual` already does for
secrets. Literal only -- regex rules are scrub-only, tracked in #198 -- so
this net still covers positions the oracle does not speak for. This module is the coverage net BEHIND that guarantee -- it
tells you which positions are scrubbable, where the oracle only tells you
that nothing leaked.

Verdict vocabulary, and why the assertion is exact:

  REDACTED     Output written, exit 0, value gone. The ONLY passing verdict.
  FAIL-CLOSED  Exit 2 (PRD section 11 safety failure) and no output. Safe,
               but degraded: the transform missed and the residual scan
               caught it. Not accepted as a pass.
  ERROR-<rc>   Any other nonzero exit with no output. A broken CLI, not a
               safety outcome.
  LEAKED       Output written, exit 0, value present. The unacceptable one.

Asserting `verdict == "REDACTED"` rather than `verdict in {REDACTED,
FAIL-CLOSED}` is load-bearing. The permissive form was in the first version
of this file and it meant a stub binary consisting of `echo boom >&2; exit
1` passed 54 of 57 assertions, because every cell read as FAIL-CLOSED and
FAIL-CLOSED read as safe. Ordinary regressions produce exactly that shape:
a renamed flag (exit 1), a config-schema change (exit 3), a re-run hitting
`output already exists` (exit 1). Every known deviation from REDACTED is
therefore an explicit, issue-tagged `xfail(strict=True)` entry rather than
a blanket allowance.

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

# The secret is caught by a built-in pattern and needs no config. The three
# PII payloads are config-driven, which is exactly the asymmetry #190 is
# about: nothing re-scans the output for these after the fact.
PAYLOADS = {
    "secret": SECRET,
    "pii-home": HOME,
    "pii-email": EMAIL,
    "pii-name": NAME,
}

CONFIG = f"""version: 1
paths:
  - match: "{HOME}"
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

# Cells whose verdict is knowingly not REDACTED today, with the issue that
# tracks each and the reason. Keyed (cell, payload_label); the value carries
# its own explanation so a second entry cannot inherit the first one's
# wording. Every entry is a strict xfail: when the tracked issue is fixed the
# cell starts passing, the strict xfail turns red, and whoever fixed it is
# forced to remove the entry rather than leaving a stale exemption behind.
#
# The secret row is here too. It is SAFE today -- a secret in a dict key
# still trips the residual scan and fails closed -- but "safe" is not the
# contract this module asserts, and silently accepting FAIL-CLOSED is what
# let a brick binary pass. It gets an entry like any other deviation.
KNOWN_DEVIATIONS: dict[tuple[str, str], tuple[int, str]] = {
    ("13-dict-key-not-value", "pii-home"): (
        190,
        "dict keys are never transformed, so a config-driven rule cannot "
        "reach this position. As of #195 this fails closed rather than "
        "leaking -- the output-side oracle catches the survivor and aborts "
        "(exit 2, nothing written), so the verdict is FAIL-CLOSED, not "
        "LEAKED. #190 stays open because the file is still unscrubbable: "
        "safe, but the user cannot publish it at all",
    ),
    ("13-dict-key-not-value", "pii-email"): (
        190,
        "dict keys are never transformed, so a config-driven rule cannot "
        "reach this position. As of #195 this fails closed rather than "
        "leaking -- the output-side oracle catches the survivor and aborts "
        "(exit 2, nothing written), so the verdict is FAIL-CLOSED, not "
        "LEAKED. #190 stays open because the file is still unscrubbable: "
        "safe, but the user cannot publish it at all",
    ),
    ("13-dict-key-not-value", "pii-name"): (
        190,
        "dict keys are never transformed, so a config-driven rule cannot "
        "reach this position. As of #195 this fails closed rather than "
        "leaking -- the output-side oracle catches the survivor and aborts "
        "(exit 2, nothing written), so the verdict is FAIL-CLOSED, not "
        "LEAKED. #190 stays open because the file is still unscrubbable: "
        "safe, but the user cannot publish it at all",
    ),
    ("13-dict-key-not-value", "secret"): (
        190,
        "dict keys are never transformed, so the secret transform misses it "
        "and the residual scan catches it instead -- safe, but degraded. "
        "Unchanged by #195: this cell already failed closed, via the secret "
        "residual scan rather than the new rule oracle",
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
    path meant a stale or misspelled value produced 57 identical
    ``FileNotFoundError`` tracebacks out of ``subprocess.run`` instead of one
    line saying the override was wrong.

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
        # Deliberately an error, not a skip. A skip here would drop 57
        # security assertions and still report green -- and the rest of this
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
    re-ran all 14 secret cells, so the slowest module in the suite paid for
    71 process spawns where 56 are needed. Session scope also means a broken
    entry point surfaces once rather than 57 times.
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
    this is the assertion that says so in one line rather than 57.
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


def test_known_deviations_reference_real_cells() -> None:
    """A cell rename must not silently delete a tracked deviation.

    KNOWN_DEVIATIONS is consulted with .get(), so a renamed cell id makes an
    entry stop matching. Today that would go red (the leak is real), but a
    future entry for a different cell would silently stop applying and turn
    a tracked known-leak into an untracked one with no signal.
    """
    unknown_cells = {c for c, _ in KNOWN_DEVIATIONS} - set(CELLS)
    assert not unknown_cells, f"KNOWN_DEVIATIONS names cells that do not exist: {unknown_cells}"
    unknown_labels = {l for _, l in KNOWN_DEVIATIONS} - set(PAYLOADS)
    assert not unknown_labels, f"KNOWN_DEVIATIONS names payloads that do not exist: {unknown_labels}"
