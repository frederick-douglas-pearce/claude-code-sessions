"""Tests for the output-side oracle over the config rule family (issue #195).

`scan_residual` gives the *secret* layer a position-agnostic guarantee:
it re-reads the serialized output, so a value the structural walk never reached
is still in those bytes and still aborts the run. Paths and identifiers had no
such pass, so the same traversal gap leaked **silently** -- exit 0, output
written, and a sidecar reporting `residual_scan: clean` on a file that still
contained the value. `scan_residual_rules` closes that asymmetry.

Two halves, and both matter:

  - the **unit** contract of `scan_residual_rules` (what it flags, what it
    excuses, and that the exception carries no PII), and
  - the **integration** contract through `sanitize_session`, which is where
    #190 and #194 actually bite. A unit test alone would not prove the
    orchestrator calls the scan on the real output at all, and a gate that is
    never reached is the way this goes quietly soft.

Per PRD section 14 every value planted here is synthetic -- `/home/realuser`,
`realuser`, and invented tokens -- never real personal data (CLAUDE.md,
"Security posture").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ccs_sanitize.orchestrator import sanitize_session
from ccs_sanitize.residual import ResidualRuleError, scan_residual_rules

from ._helpers import serialize_test_line as _line, write_config as _config


_REAL_USER_HOME = "/home/realuser"
_BASE_CONFIG = f"""
version: 1
paths:
  - match: "{_REAL_USER_HOME}"
    replace: "/home/user"
identifiers:
  - match: "realuser"
    replace: "user"
"""


def _rules(config):
    """The two rule sequences the scan takes, after ``lines``."""
    return (config.paths, config.identifiers)


# ----- unit: what the scan flags and what it excuses ----------------------


def test_clean_lines_return_none(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    assert (
        scan_residual_rules(['{"k": "nothing interesting here"}'], *_rules(config))
        is None
    )


def test_empty_lines_is_clean(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    assert scan_residual_rules([], *_rules(config)) is None


def test_surviving_path_value_raises_naming_section_and_index(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules([f'{{"k": "{_REAL_USER_HOME}/x"}}'], *_rules(config))
    assert exc.value.section == "paths"
    assert exc.value.index == 0


def test_exception_never_carries_the_match_or_the_span(tmp_path: Path) -> None:
    """D-2, extended. The rule's own ``match`` value IS the literal PII here,
    so unlike ``ResidualSecretError`` (whose ``kind`` is a generic label) this
    exception may name neither the pattern nor the matched span."""
    config = _config(tmp_path, _BASE_CONFIG)
    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules([f'{{"k": "{_REAL_USER_HOME}/secret"}}'], *_rules(config))
    rendered = str(exc.value)
    assert _REAL_USER_HOME not in rendered
    assert "realuser" not in rendered
    assert "paths[0]" in rendered


def test_replacement_in_output_does_not_trip_the_scan(tmp_path: Path) -> None:
    """The load-time I-3 guard already forbids a rule matching any configured
    replacement, so ordinary scrubbed output is clean with no exemption
    mechanism at all."""
    config = _config(tmp_path, _BASE_CONFIG)
    assert scan_residual_rules(['{"k": "/home/user/x"}'], *_rules(config)) is None


def test_regex_rules_are_not_scanned(tmp_path: Path) -> None:
    """Regex rules are deliberately out of this gate's scope.

    "Present in the output means leaked" is true of a literal value and false
    of a *shape*: shapes legitimately survive scrub. Scanning them
    unconditionally aborted clean runs (see the two regressions below), so
    regex rules are covered by the in-walk scrub only. PRD section 10 states
    what the sidecar may therefore claim; the gap is tracked in the follow-up
    issue, not silently accepted.
    """
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:CORP-[0-9]{4}"
    replace: "<ticket>"
""",
    )
    assert (
        scan_residual_rules(['{"ticket": "CORP-4821"}'], *_rules(config))
        is None
    )


def test_literal_rule_matches_by_value_not_by_pattern_source(tmp_path: Path) -> None:
    """A literal rule is compiled ``re.escape``d, so regex metacharacters in a
    match value are matched literally rather than as a pattern."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "a.b[0]"
    replace: "<id>"
""",
    )
    # "axb0" is the discriminator: read as a raw pattern, ``a.b[0]`` means
    # a-anychar-b-then-the-class-[0], which "axb0" satisfies. Escaped, it means
    # the six literal characters, which "axb0" does not. So this line fails if
    # the rule is ever compiled raw. (An earlier version used "axbQ", which
    # matches under neither reading and so discriminated nothing.)
    assert scan_residual_rules(['{"k": "axb0"}'], *_rules(config)) is None
    # The literal itself must still abort.
    with pytest.raises(ResidualRuleError):
        scan_residual_rules(['{"k": "a.b[0]"}'], *_rules(config))


def test_section_and_index_report_the_matching_rule(tmp_path: Path) -> None:
    """Iteration order is part of the contract: paths first, then identifiers,
    ascending index within each. Tests assert on ``section[index]``, so an
    unstable order would make those assertions meaningless."""
    config = _config(
        tmp_path,
        """
version: 1
paths:
  - match: "/home/alpha"
    replace: "/home/a"
  - match: "/home/bravo"
    replace: "/home/b"
identifiers:
  - match: "charlie"
    replace: "c"
""",
    )
    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules(['{"k": "/home/bravo"}'], *_rules(config))
    assert (exc.value.section, exc.value.index) == ("paths", 1)

    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules(['{"k": "charlie"}'], *_rules(config))
    assert (exc.value.section, exc.value.index) == ("identifiers", 0)


# ----- why there is no allow-set ------------------------------------------


def test_regex_expanded_replacement_does_not_excuse_a_literal_leak(
    tmp_path: Path,
) -> None:
    """The reproduction that removed the allow-set. It leaked.

    An earlier version excused a match whose span was exactly a replacement the
    run had recorded, so a synthesized value could not trip the scan. But a
    regex rule's replacement is produced at runtime by ``match.expand()``, and
    I-3 vets only the literal ``replace`` template (``/home/\\1``), never the
    expansion. So the identifiers layer mints ``/home/realuser``, records it,
    and the allow-set then excused the ``paths`` rule whose ``match`` value that
    IS -- exit 0, the operator's real home directory in the output, and a
    sidecar reading ``residual_scan: clean``.

    Note the layer order is what makes it reachable: paths run BEFORE
    identifiers, so the paths rule never sees ``/home/realuser`` during scrub.
    It exists only in the output, which is exactly what this gate is for.
    """
    config = _config(
        tmp_path,
        r"""
version: 1
paths:
  - match: "/home/realuser"
    replace: "/home/user"
identifiers:
  - match: 're:HOME_(\w+)'
    replace: '/home/\1'
""",
    )
    lines = [_line({"type": "user", "toolUseResult": {"stdout": "see HOME_realuser here"}})]
    with pytest.raises(ResidualRuleError) as exc:
        sanitize_session(lines, config)
    assert (exc.value.section, exc.value.index) == ("paths", 0)


def test_configured_replacements_cannot_trip_the_scan(tmp_path: Path) -> None:
    """Why removing the allow-set costs nothing the config guard does not give.

    I-3 forbids a rule from matching any *configured* replacement, so ordinary
    scrubbed output is clean with no allow-list at all.
    """
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [_line({"type": "user", "toolUseResult": {"stdout": f"{_REAL_USER_HOME}/notes.md"}})]
    out, _, _, _ = sanitize_session(lines, config)
    assert "/home/user/notes.md" in out[0]


def test_gitbranch_placeholder_does_not_trip_the_scan(tmp_path: Path) -> None:
    """The other class I-3 already covers: a rule matching the gitBranch
    placeholder is rejected at load, so the substituted value is safe here."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [_line({"type": "user", "gitBranch": "feature/realuser-work", "toolUseResult": {"stdout": "ok"}})]
    out, _, _, _ = sanitize_session(lines, config)
    assert "feature/example" in out[0]


# ----- integration: the two known traversal gaps now abort ----------------


def test_value_in_a_dict_key_aborts_rather_than_writing(tmp_path: Path) -> None:
    """#190. The structural walk transforms string *leaves*; a dict key is
    copied verbatim. Before the oracle this returned normally with the value
    intact and a sidecar reporting a clean run."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "user", "toolUseResult": {f"{_REAL_USER_HOME}/notes.md": {"size": 42}}})
    ]
    with pytest.raises(ResidualRuleError):
        sanitize_session(lines, config)


@pytest.mark.parametrize(
    "field",
    [
        # _SKIP_LEAF_NAMES -- bare names skipped at any depth.
        "version",
        "type",
        "role",
        "requestId",
        "tool_use_id",
        # _UUID_NAMES -- also skipped bare while remap_uuids is off (the default).
        "sessionId",
        # The `_tokens` SUFFIX skip, which is broader still: it is not a name
        # list at all, so every tool parameter ending in `_tokens` is exempt.
        "max_tokens",
    ],
)
def test_value_under_a_skip_listed_name_in_tool_input_aborts(
    tmp_path: Path, field: str
) -> None:
    """#194. The skip-list exempts these positions at any depth, and tool inputs
    are arbitrary tool-defined JSON, so a tool whose parameter happens to carry
    one of these names puts user data where the walker declines to look.

    The set here is not identical to the one #195's test plan names -- it adds
    ``role``, ``requestId`` and ``tool_use_id`` from ``_SKIP_LEAF_NAMES``, and
    covers #195's ``usage.x`` in ``test_nested_value_under_tool_input_aborts``
    instead. What it spans is three distinct skip *mechanisms*, not one: the
    bare-name list, the UUID-name list (bare while ``remap_uuids`` is off), and
    the ``_tokens`` **suffix** rule. The suffix rule is the broadest of the three -- it exempts a name
    nobody enumerated -- which is the argument for closing the class rather
    than the instances."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "input": {field: f"{_REAL_USER_HOME}/app"},
                        }
                    ]
                },
            }
        )
    ]
    with pytest.raises(ResidualRuleError):
        sanitize_session(lines, config)


def test_nested_value_under_tool_input_aborts(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "input": {"usage": {"x": f"{_REAL_USER_HOME}/deep"}},
                        }
                    ]
                },
            }
        )
    ]
    with pytest.raises(ResidualRuleError):
        sanitize_session(lines, config)


# ----- integration: the happy path must not move --------------------------


def test_ordinary_leaf_still_scrubs_and_does_not_abort(tmp_path: Path) -> None:
    """The control. A reachable leaf redacts as before, and the oracle sees only
    the replacement, so the run completes."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [_line({"type": "user", "toolUseResult": {"stdout": f"{_REAL_USER_HOME}/notes.md"}})]
    out, _, subtable, _ = sanitize_session(lines, config)
    assert _REAL_USER_HOME not in out[0]
    assert "/home/user/notes.md" in out[0]
    assert any(e.original == _REAL_USER_HOME for e in subtable)


def test_value_on_a_stripped_line_does_not_abort(tmp_path: Path) -> None:
    """The scan covers exactly the bytes that get written. A configured value on
    a strip-types-dropped line never reaches the output file, so aborting on it
    would refuse a file over content the tool deliberately discarded."""
    config = _config(tmp_path, _BASE_CONFIG)
    lines = [
        _line({"type": "file-history-snapshot", "note": f"{_REAL_USER_HOME}/dropped"}),
        _line({"type": "user", "toolUseResult": {"stdout": "clean"}}),
    ]
    out, counts, _, _ = sanitize_session(lines, config)
    assert len(out) == 1
    assert _REAL_USER_HOME not in out[0]
    assert dict(counts.stripped_lines) == {"file-history-snapshot": 1}


# ----- regressions for the three findings the code review reproduced ------


def test_escaped_value_in_a_dict_key_is_not_invisible(tmp_path: Path) -> None:
    """Code-review finding A, the one that broke the headline claim.

    Rules match DECODED leaf values; the first implementation scanned the
    SERIALIZED line. A Windows home directory -- the canonical ``paths`` case --
    serializes with doubled backslashes, so ``C:\\Users\\realuser`` in the output
    bytes never matched a rule authored as ``C:\\Users\\realuser`` decoded. It
    shipped at exit 0 with ``residual_scan: clean``, in the #190 dict-key
    position: the exact silent leak this gate exists to close.
    """
    config = _config(
        tmp_path,
        r"""
version: 1
paths:
  - match: "C:\\Users\\realuser"
    replace: "C:\\Users\\user"
""",
    )
    lines = [_line({"type": "user", "toolUseResult": {"C:\\Users\\realuser\\notes.md": {"size": 1}}})]
    with pytest.raises(ResidualRuleError) as exc:
        sanitize_session(lines, config)
    assert exc.value.section == "paths"


def test_value_containing_a_quote_is_not_invisible(tmp_path: Path) -> None:
    """Same root cause as the test above, different escape. A quote in a match
    value is another byte whose serialized and decoded forms differ."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: 'real"user'
    replace: "user"
""",
    )
    # A dict key -- the #190 position the scrub cannot reach. In a reachable
    # leaf the transform would simply scrub it and there would be nothing for
    # this gate to catch.
    lines = [_line({"type": "user", "toolUseResult": {'real"user': {"size": 1}}})]
    with pytest.raises(ResidualRuleError):
        sanitize_session(lines, config)


def test_default_remap_uuids_with_a_uuid_shaped_rule_does_not_abort(
    tmp_path: Path,
) -> None:
    """Code-review finding C, and the reason regex rules are out of scope.

    Under the DEFAULT ``remap_uuids: false`` the UUID-graph fields are
    skip-listed **deliberately**, so the parent/subagent graph stays linkable.
    A UUID-shaped identifier rule therefore matches a value the sanitizer
    preserved on purpose. Scanning regex rules aborted every such session at
    exit 2 though nothing had been mis-scrubbed, and with no override the
    config could never scrub any file.
    """
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    replace: "<uuid>"
""",
    )
    assert config.options.remap_uuids is False
    lines = [
        _line(
            {
                "type": "user",
                "sessionId": "11111111-2222-3333-4444-555555555555",
                "toolUseResult": {"stdout": "clean"},
            }
        )
    ]
    out, _, _, _ = sanitize_session(lines, config)
    assert len(out) == 1
    assert "11111111-2222-3333-4444-555555555555" in out[0]


def test_remap_uuids_true_with_a_uuid_shaped_rule_does_not_abort(
    tmp_path: Path,
) -> None:
    """The other half of finding C. With remapping on, the synthesized UUID is a
    value no load-time check ever saw, so a UUID-shaped rule would match the
    sanitizer's own output."""
    config = _config(
        tmp_path,
        """
version: 1
options:
  remap_uuids: true
identifiers:
  - match: "re:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    replace: "<uuid>"
""",
    )
    original = "11111111-2222-3333-4444-555555555555"
    lines = [_line({"type": "user", "sessionId": original, "message": {"role": "user"}})]
    out, _, subtable, _ = sanitize_session(lines, config)
    assert original not in out[0]
    remapped = {e.replacement for e in subtable if e.label == "identifiers:uuid"}
    assert remapped, "expected a uuid remap entry in the substitution table"


def test_zero_width_regex_does_not_abort_a_clean_run(tmp_path: Path) -> None:
    """Code-review finding B. An input-dependent zero-width match (a lookahead,
    ``\\b``) produces an empty span, which the earlier allow-set-based scan never
    excused, so the first one aborted a run with no PII in it at all. ``_reject_zero_width_pattern``
    does not cover these -- it only tests ``compiled.match("")`` -- which is why
    ``rules/_engine.apply_rule`` carries its own guard. Unreachable now that only
    literal rules are scanned (an empty literal is rejected at load), and pinned
    so a future regex treatment cannot reintroduce it silently."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:(?=hello)"
    replace: ""
""",
    )
    lines = [_line({"type": "user", "toolUseResult": {"stdout": "hello world"}})]
    out, _, _, _ = sanitize_session(lines, config)
    assert len(out) == 1


def test_literal_rule_still_covered_when_a_regex_rule_is_present(
    tmp_path: Path,
) -> None:
    """Narrowing to literals must not be a way to switch the whole gate off: a
    config holding both kinds keeps the literal guarantee, and the reported
    index is the rule's position in its own section, not its position among the
    literals."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:CORP-[0-9]{4}"
    replace: "<ticket>"
  - match: "realuser"
    replace: "user"
""",
    )
    lines = [_line({"type": "user", "toolUseResult": {"realuser": {"size": 1}}})]
    with pytest.raises(ResidualRuleError) as exc:
        sanitize_session(lines, config)
    assert (exc.value.section, exc.value.index) == ("identifiers", 1)


# ----- CLI level: the sidecar cannot certify what was never written -------


def test_cli_exits_two_and_writes_neither_file(tmp_path: Path) -> None:
    """`residual_scan: clean` may only appear on a file that passed BOTH scans.

    The strongest form of that criterion is that on a rule survivor there is no
    sidecar at all: the run aborts before the atomic write pair, so nothing is
    left to read. Before #195 this same input produced exit 0, an output file
    holding the value verbatim, and a sidecar affirmatively reporting
    `residual_scan: clean`.
    """
    from ccs_sanitize.cli import main

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_CONFIG, encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        _line({"type": "user", "toolUseResult": {f"{_REAL_USER_HOME}/notes.md": {"size": 1}}})
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"

    code = main([str(inp), "-o", str(out), "-c", str(cfg), "--no-check"])

    assert code == 2
    assert not out.exists()
    assert not (tmp_path / "out.jsonl.scrubbed").exists()


def test_cli_diagnostic_carries_no_pii(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stderr diagnostic is the surface most likely to be captured into a
    CI log or a Claude Code transcript, so it must name `section[index]` only."""
    from ccs_sanitize.cli import main

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_BASE_CONFIG, encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(
        _line({"type": "user", "toolUseResult": {f"{_REAL_USER_HOME}/notes.md": {"size": 1}}})
        + "\n",
        encoding="utf-8",
    )

    assert main([str(inp), "-o", str(tmp_path / "out.jsonl"), "-c", str(cfg), "--no-check"]) == 2

    err = capsys.readouterr().err
    assert "paths[0]" in err
    assert _REAL_USER_HOME not in err
    assert "realuser" not in err
