"""Tests for the output-side oracle over the config rule family (issue #195).

`scan_residual` gives the *secret* layer a total, position-agnostic guarantee:
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
    orchestrator threads the allow-set through, and threading it wrongly is
    the way this gate goes quietly soft.

Per PRD section 14 the fixtures here use synthetic identifiers only --
`/home/realuser` and RFC-2606 reserved `.test` / `.example` names, never real
personal data (CLAUDE.md, "Security posture").
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
    """The three positional arguments the scan takes, minus the allow-set."""
    return (config.paths, config.identifiers)


# ----- unit: what the scan flags and what it excuses ----------------------


def test_clean_lines_return_none(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    assert scan_residual_rules(["nothing interesting here"], *_rules(config), frozenset()) is None


def test_empty_lines_is_clean(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    assert scan_residual_rules([], *_rules(config), frozenset()) is None


def test_surviving_path_value_raises_naming_section_and_index(tmp_path: Path) -> None:
    config = _config(tmp_path, _BASE_CONFIG)
    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules([f'{{"k": "{_REAL_USER_HOME}/x"}}'], *_rules(config), frozenset())
    assert exc.value.section == "paths"
    assert exc.value.index == 0


def test_exception_never_carries_the_match_or_the_span(tmp_path: Path) -> None:
    """D-2, extended. The rule's own ``match`` value IS the literal PII here,
    so unlike ``ResidualSecretError`` (whose ``kind`` is a generic label) this
    exception may name neither the pattern nor the matched span."""
    config = _config(tmp_path, _BASE_CONFIG)
    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules([f'{{"k": "{_REAL_USER_HOME}/secret"}}'], *_rules(config), frozenset())
    rendered = str(exc.value)
    assert _REAL_USER_HOME not in rendered
    assert "realuser" not in rendered
    assert "paths[0]" in rendered


def test_replacement_in_output_does_not_trip_the_scan(tmp_path: Path) -> None:
    """The load-time I-3 guard already forbids a rule matching any configured
    replacement, so scrubbed output is clean without needing the allow-set."""
    config = _config(tmp_path, _BASE_CONFIG)
    assert scan_residual_rules(['{"k": "/home/user/x"}'], *_rules(config), frozenset()) is None


def test_regex_rule_is_scanned_via_its_compiled_form(tmp_path: Path) -> None:
    """A regex rule must be matched by its compiled pattern, not by a literal
    comparison against its source text."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:CORP-[0-9]{4}"
    replace: "<ticket>"
""",
    )
    # The literal source text "re:CORP-[0-9]{4}" is absent; a value the regex
    # matches is present. Only compiled-form matching flags this.
    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules(['{"ticket": "CORP-4821"}'], *_rules(config), frozenset())
    assert exc.value.section == "identifiers"
    assert exc.value.index == 0


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
        scan_residual_rules(['{"k": "/home/bravo"}'], *_rules(config), frozenset())
    assert (exc.value.section, exc.value.index) == ("paths", 1)

    with pytest.raises(ResidualRuleError) as exc:
        scan_residual_rules(['{"k": "charlie"}'], *_rules(config), frozenset())
    assert (exc.value.section, exc.value.index) == ("identifiers", 0)


# ----- the allow-set: exact membership, not masking -----------------------


_UUID_RULE_CONFIG = """
version: 1
identifiers:
  - match: "re:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    replace: "<uuid>"
"""

# A value the rule above matches, standing in for what ``remap_uuids``
# synthesizes at runtime. The load-time I-3 guard cannot have seen it.
_SYNTHESIZED = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_exact_replacement_span_is_excused(tmp_path: Path) -> None:
    """The allow-set holds replacements the run recorded. A match whose span is
    exactly one of them is the sanitizer's own output, not a survivor."""
    config = _config(tmp_path, _UUID_RULE_CONFIG)
    assert (
        scan_residual_rules(
            [f'{{"sessionId": "{_SYNTHESIZED}"}}'],
            *_rules(config),
            frozenset({_SYNTHESIZED}),
        )
        is None
    )


def test_leak_whose_span_is_not_in_the_allow_set_still_aborts(tmp_path: Path) -> None:
    """Guards the exclusion from over-excusing. A populated allow-set must not
    become a blanket amnesty for every match on the line."""
    config = _config(tmp_path, _UUID_RULE_CONFIG)
    other = "99999999-8888-7777-6666-555555555555"
    with pytest.raises(ResidualRuleError):
        scan_residual_rules(
            [f'{{"a": "{_SYNTHESIZED}", "b": "{other}"}}'],
            *_rules(config),
            frozenset({_SYNTHESIZED}),
        )


def test_later_match_on_a_line_is_reached_when_the_first_is_excused(
    tmp_path: Path,
) -> None:
    """The scan uses ``finditer``, not ``search``. If it stopped at the first
    match it would excuse the whole line whenever the sanitizer's own output
    happened to appear before a genuine survivor."""
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "re:tok-[a-z]+"
    replace: "<token>"
""",
    )
    line = '{"first": "tok-allowed", "second": "tok-leaked"}'
    with pytest.raises(ResidualRuleError):
        scan_residual_rules([line], *_rules(config), frozenset({"tok-allowed"}))


def test_masking_counterexample_is_not_how_this_works(tmp_path: Path) -> None:
    """The construction that ruled out masking-by-deletion (#195 design review).

    Rule ``match: abc123`` / ``replace: abc`` passes the I-3 guard, because
    neither string matches the other's rule. Had the scan deleted every
    recorded replacement from the line before matching, a genuine ``abc123``
    leak would become ``123``, the rule would stop matching, and the leak
    would ship with a clean sidecar -- a **false negative**, the one direction
    a security tool cannot tolerate. Exact-span membership cannot do that:
    the span here is ``abc123``, which is not in the allow-set.
    """
    config = _config(
        tmp_path,
        """
version: 1
identifiers:
  - match: "abc123"
    replace: "abc"
""",
    )
    with pytest.raises(ResidualRuleError):
        scan_residual_rules(['{"k": "abc123"}'], *_rules(config), frozenset({"abc"}))


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

    The set here is the one the #195 acceptance criteria name, and it spans
    three distinct skip mechanisms, not one: the bare-name list, the UUID-name
    list (bare while ``remap_uuids`` is off), and the ``_tokens`` **suffix**
    rule. The suffix rule is the broadest of the three -- it exempts a name
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


# ----- the remap_uuids regression the issue's test plan omitted -----------


def test_remap_uuids_with_a_broad_uuid_rule_does_not_false_abort(
    tmp_path: Path,
) -> None:
    """The Q2 regression, and the reason the allow-set exists at all.

    With ``remap_uuids: true`` the identifier layer early-returns on a
    ``UUID_FIELDS`` leaf and substitutes a SHA-256-derived UUID. That value is
    synthesized at runtime, so the load-time I-3 guard has never seen it: a
    broad rule like ``re:[0-9a-f-]{36}`` never fires on that leaf during scrub
    and *would* match the synthesized UUID in the output. Without the allow-set
    this aborts every run that remaps a UUID -- the tool would refuse to scrub
    anything at all for such a config.
    """
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
    assert config.options.remap_uuids is True
    original = "11111111-2222-3333-4444-555555555555"
    lines = [_line({"type": "user", "sessionId": original, "message": {"role": "user"}})]

    out, _, subtable, _ = sanitize_session(lines, config)

    # The run completed rather than aborting, the original is gone, and what
    # replaced it is the synthesized remap -- which is exactly the value the
    # allow-set excused.
    assert original not in out[0]
    remapped = {e.replacement for e in subtable if e.label == "identifiers:uuid"}
    assert remapped, "expected a uuid remap entry in the substitution table"
    assert any(value in out[0] for value in remapped)


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
