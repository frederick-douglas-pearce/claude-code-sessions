"""Tests for the YAML config loader (issue #19).

Covers:

  - Loading a valid config returns the expected ``Config`` shape.
  - Malformed YAML raises ``ConfigError`` (not ``yaml.YAMLError``).
  - Schema violations (unknown keys, wrong types, missing required fields,
    invalid regex) raise ``ConfigError`` with a message that names the offender.
  - The I-3 replacement-leak guard rejects replacements that themselves match
    any path, identifier, or built-in/extra secret rule.
  - The Tier-1 and Tier-2 secret-pattern constants are present and compile.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ccs_sanitize.config import (
    ConfigError,
    ConfigOptions,
    load_config,
)
from ccs_sanitize.rules.secrets import (
    BATCH_PATTERNS,
    SECRET_PATTERNS,
    VENDORED_PATTERNS,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# ----- happy paths --------------------------------------------------------


def test_minimal_valid_config(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, "version: 1\n"))
    assert config.version == 1
    assert config.paths == []
    assert config.identifiers == []
    assert config.options == ConfigOptions()
    assert config.extra_secret_patterns == []


def test_full_valid_config(tmp_path: Path) -> None:
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "re:-home-fdpearce-([a-z0-9-]+)"
    replace: "-home-user-project"
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
options:
  scrub_git_branch: true
  remap_uuids: false
extra_secret_patterns:
  - pattern: "re:CORP-[A-Z0-9]{32}"
    kind: "corp-token"
"""
    config = load_config(_write(tmp_path, body))
    assert config.version == 1
    assert len(config.paths) == 2
    assert config.paths[0].pattern == "/home/fdpearce"
    assert config.paths[0].is_regex is False
    assert config.paths[1].is_regex is True
    assert config.identifiers[0].replace == "user@example.com"
    assert config.options.scrub_git_branch is True
    assert config.options.remap_uuids is False
    assert len(config.extra_secret_patterns) == 1
    assert config.extra_secret_patterns[0].kind == "corp-token"


def test_options_defaults_when_omitted(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, "version: 1\n"))
    assert config.options.scrub_git_branch is True
    assert config.options.remap_uuids is False


def test_compiled_regex_matches_literal_rule(tmp_path: Path) -> None:
    """A literal rule's compiled pattern matches the literal text via re.search."""
    body = 'version: 1\npaths:\n  - match: "/home/fdpearce"\n    replace: "/home/user"\n'
    config = load_config(_write(tmp_path, body))
    rule = config.paths[0]
    assert rule.compiled.search("/home/fdpearce/code") is not None
    assert rule.compiled.search("/elsewhere") is None


# ----- file-level errors --------------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_empty_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty"):
        load_config(_write(tmp_path, ""))


def test_malformed_yaml_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="malformed YAML"):
        load_config(_write(tmp_path, "version: 1\n  bad: ["))


def test_non_mapping_root_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(_write(tmp_path, "- just\n- a\n- list\n"))


# ----- schema errors ------------------------------------------------------


def test_missing_version_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing required field: version"):
        load_config(_write(tmp_path, "paths: []\n"))


def test_unsupported_version_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unsupported config version"):
        load_config(_write(tmp_path, "version: 2\n"))


def test_unknown_top_level_key_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(_write(tmp_path, "version: 1\nnotakey: hi\n"))


def test_unknown_rule_key_raises(tmp_path: Path) -> None:
    body = """
version: 1
paths:
  - match: "/x"
    replace: "/y"
    extra: nope
"""
    with pytest.raises(ConfigError, match="unknown key.+paths\\[0\\]"):
        load_config(_write(tmp_path, body))


def test_unknown_option_key_raises(tmp_path: Path) -> None:
    body = "version: 1\noptions:\n  scrub_git_branch: true\n  disable_secrets: true\n"
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(_write(tmp_path, body))


def test_option_wrong_type_raises(tmp_path: Path) -> None:
    body = "version: 1\noptions:\n  scrub_git_branch: yes_please\n"
    with pytest.raises(ConfigError, match="must be a boolean"):
        load_config(_write(tmp_path, body))


def test_invalid_regex_in_match_raises(tmp_path: Path) -> None:
    body = 'version: 1\npaths:\n  - match: "re:[unterminated"\n    replace: "/x"\n'
    with pytest.raises(ConfigError, match="invalid regex"):
        load_config(_write(tmp_path, body))


def test_empty_regex_prefix_raises(tmp_path: Path) -> None:
    body = 'version: 1\npaths:\n  - match: "re:"\n    replace: "/x"\n'
    with pytest.raises(ConfigError, match="empty regex"):
        load_config(_write(tmp_path, body))


def test_paths_not_a_list_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="paths must be a list"):
        load_config(_write(tmp_path, "version: 1\npaths: {}\n"))


def test_rule_missing_match_raises(tmp_path: Path) -> None:
    body = 'version: 1\npaths:\n  - replace: "/y"\n'
    with pytest.raises(ConfigError, match="paths\\[0\\].match"):
        load_config(_write(tmp_path, body))


def test_rule_missing_replace_raises(tmp_path: Path) -> None:
    body = 'version: 1\npaths:\n  - match: "/x"\n'
    with pytest.raises(ConfigError, match="paths\\[0\\].replace"):
        load_config(_write(tmp_path, body))


# ----- extra_secret_patterns ---------------------------------------------


def test_extra_secret_pattern_bad_regex_raises(tmp_path: Path) -> None:
    body = """
version: 1
extra_secret_patterns:
  - pattern: "re:[unclosed"
    kind: "broken"
"""
    with pytest.raises(ConfigError, match="invalid regex"):
        load_config(_write(tmp_path, body))


def test_extra_secret_pattern_missing_kind_raises(tmp_path: Path) -> None:
    body = 'version: 1\nextra_secret_patterns:\n  - pattern: "re:X+"\n'
    with pytest.raises(ConfigError, match="\\.kind"):
        load_config(_write(tmp_path, body))


# ----- I-3 replacement-leak guard ----------------------------------------


def test_i3_replace_matches_builtin_secret_pattern(tmp_path: Path) -> None:
    """A literal replacement that looks like an Anthropic key must be rejected."""
    fake_key = "sk-ant-" + "A" * 25  # matches VENDORED_PATTERNS[0]
    body = f"""
version: 1
identifiers:
  - match: "fpearce@gmail.com"
    replace: "{fake_key}"
"""
    with pytest.raises(ConfigError, match="anthropic-key"):
        load_config(_write(tmp_path, body))


def test_i3_replace_matches_other_path_match(tmp_path: Path) -> None:
    """Replacement containing another path rule's literal match must be rejected."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
  - match: "/home"
    replace: "/anywhere"
"""
    # The first rule's replace "/home/user" contains the second rule's match "/home".
    with pytest.raises(ConfigError, match="must not themselves match"):
        load_config(_write(tmp_path, body))


def test_i3_path_replace_matches_identifier_match(tmp_path: Path) -> None:
    """Cross-section: a path replacement that matches an identifier rule is rejected."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "owner@example.com"
identifiers:
  - match: "re:[A-Za-z0-9._%+-]+@example\\\\.com"
    replace: "user@scrubbed.invalid"
"""
    with pytest.raises(ConfigError, match="must not themselves match"):
        load_config(_write(tmp_path, body))


def test_i3_replace_matches_extra_secret_pattern(tmp_path: Path) -> None:
    body = """
version: 1
identifiers:
  - match: "fpearce@gmail.com"
    replace: "CORP-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
extra_secret_patterns:
  - pattern: "re:CORP-[A-Z0-9]{32}"
    kind: "corp-token"
"""
    with pytest.raises(ConfigError, match="corp-token"):
        load_config(_write(tmp_path, body))


def test_i3_generic_placeholders_pass(tmp_path: Path) -> None:
    """The PRD's recommended placeholders ('/home/user', 'user@example.com')
    must not trip the I-3 guard."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
identifiers:
  - match: "fpearce@gmail.com"
    replace: "user@example.com"
"""
    config = load_config(_write(tmp_path, body))
    assert config.paths[0].replace == "/home/user"
    assert config.identifiers[0].replace == "user@example.com"


# ----- pattern constants -------------------------------------------------


def test_vendored_patterns_are_non_empty() -> None:
    assert VENDORED_PATTERNS, "Tier-1 vendored secret patterns must not be empty"


def test_batch_patterns_are_non_empty() -> None:
    assert BATCH_PATTERNS, "Tier-2 batch secret patterns must not be empty"


def test_secret_patterns_is_concatenation() -> None:
    assert SECRET_PATTERNS == VENDORED_PATTERNS + BATCH_PATTERNS


def test_all_secret_patterns_compile() -> None:
    for pat, label in SECRET_PATTERNS:
        try:
            re.compile(pat)
        except re.error as exc:  # pragma: no cover — defensive
            pytest.fail(f"secret pattern {label!r} failed to compile: {exc}")


def test_secret_pattern_labels_are_unique() -> None:
    labels = [label for _, label in SECRET_PATTERNS]
    assert len(labels) == len(set(labels)), f"duplicate labels: {labels}"
