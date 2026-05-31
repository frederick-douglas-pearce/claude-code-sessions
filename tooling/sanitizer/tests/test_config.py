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
    assert config.paths == ()
    assert config.identifiers == ()
    assert config.options == ConfigOptions()
    assert config.extra_secret_patterns == ()


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


def test_uuid_seed_defaults_when_omitted(tmp_path: Path) -> None:
    """The seed has a stable default so existing configs (no
    ``uuid_seed:`` key) keep working under remap_uuids without forcing
    the user to declare it. Defaults live on ``ConfigOptions`` so the
    default change would surface as a single-source-of-truth diff."""
    config = load_config(_write(tmp_path, "version: 1\n"))
    assert config.options.uuid_seed == "ccs-sanitize/v1"


def test_uuid_seed_custom_value_loaded(tmp_path: Path) -> None:
    body = "version: 1\noptions:\n  uuid_seed: my-project-seed-2026\n"
    config = load_config(_write(tmp_path, body))
    assert config.options.uuid_seed == "my-project-seed-2026"


def test_uuid_seed_empty_string_raises(tmp_path: Path) -> None:
    """An empty seed would make the SHA-256 input depend only on the
    original UUID, which is a real but silent change to the determinism
    contract. Reject at load time so the user notices."""
    body = 'version: 1\noptions:\n  uuid_seed: ""\n'
    with pytest.raises(ConfigError, match="uuid_seed"):
        load_config(_write(tmp_path, body))


def test_uuid_seed_wrong_type_raises(tmp_path: Path) -> None:
    body = "version: 1\noptions:\n  uuid_seed: 42\n"
    with pytest.raises(ConfigError, match="uuid_seed"):
        load_config(_write(tmp_path, body))


def test_invalid_regex_in_match_raises(tmp_path: Path) -> None:
    body = 'version: 1\npaths:\n  - match: "re:[unterminated"\n    replace: "/x"\n'
    with pytest.raises(ConfigError, match="invalid regex"):
        load_config(_write(tmp_path, body))


def test_empty_regex_prefix_raises(tmp_path: Path) -> None:
    body = 'version: 1\npaths:\n  - match: "re:"\n    replace: "/x"\n'
    with pytest.raises(ConfigError, match="empty regex"):
        load_config(_write(tmp_path, body))


def test_anchor_only_regex_rejected_at_load_time(tmp_path: Path) -> None:
    """Anchor-only patterns (``^``, ``$``, ``\\A``) match zero characters
    and as a scrub rule would either insert at every position or pollute
    the audit log with empty-original rows. The loader rejects them so the
    user gets a ``ConfigError`` (exit 3) instead of a silent no-op rule.
    PRD section 11 fail-closed posture for security-relevant misconfig."""
    body = 'version: 1\npaths:\n  - match: "re:^"\n    replace: "X"\n'
    with pytest.raises(ConfigError, match="zero width"):
        load_config(_write(tmp_path, body))


def test_unbounded_optional_regex_rejected_at_load_time(tmp_path: Path) -> None:
    """``.*``, ``a*``, ``a?`` all match the empty string. A user who wrote
    ``re:.*`` as a path rule almost certainly meant ``re:.+`` (a likely
    typo); rejecting at load time surfaces the bug instead of letting the
    rule erase every leaf or silently match nothing."""
    body = 'version: 1\npaths:\n  - match: "re:.*"\n    replace: "X"\n'
    with pytest.raises(ConfigError, match="zero width"):
        load_config(_write(tmp_path, body))


def test_extra_secret_anchor_pattern_rejected(tmp_path: Path) -> None:
    """The static zero-width check applies to ``extra_secret_patterns``
    too, since they share the same matching infrastructure."""
    body = """
version: 1
extra_secret_patterns:
  - pattern: "re:^"
    kind: "broken"
"""
    with pytest.raises(ConfigError, match="zero width"):
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


def test_pem_pattern_catches_encrypted_private_key() -> None:
    """Standard PKCS#8 encrypted PEM headers (what openssl pkcs8 and
    passphrase-protected ssh-keygen produce) must match the PEM pattern.
    PEM is now a Tier-1 (VENDORED) pattern so the live hook gets it too —
    previously it was Tier-2-only and the hook had no PEM coverage."""
    import re as _re

    pem_pattern = next(p for p, label in VENDORED_PATTERNS if label == "pem-private-key")
    compiled = _re.compile(pem_pattern)
    assert compiled.search("-----BEGIN ENCRYPTED PRIVATE KEY-----") is not None
    assert compiled.search("-----BEGIN RSA PRIVATE KEY-----") is not None
    assert compiled.search("-----BEGIN PRIVATE KEY-----") is not None


def test_pem_pattern_is_in_tier_1_not_tier_2() -> None:
    """PEM was promoted from BATCH_PATTERNS to VENDORED_PATTERNS so the
    live hook (which only mirrors Tier 1 via the I-4 sync test) gets PEM
    coverage. Pin the partition so a regression bringing PEM back into
    Tier 2 trips the test rather than silently un-syncing the hook."""
    vendored_labels = {label for _, label in VENDORED_PATTERNS}
    batch_labels = {label for _, label in BATCH_PATTERNS}
    assert "pem-private-key" in vendored_labels
    assert "pem-private-key" not in batch_labels


# ----- /simplify review fixes -------------------------------------------


def test_version_bool_rejected(tmp_path: Path) -> None:
    """``version: true`` in YAML parses to Python ``True``; without the
    isinstance gate ``True == 1`` would silently accept it (and the
    sidecar would later serialize a bool)."""
    with pytest.raises(ConfigError, match="version must be an integer"):
        load_config(_write(tmp_path, "version: true\n"))


def test_version_float_rejected(tmp_path: Path) -> None:
    """``version: 1.0`` compares equal to ``1`` but is a float; reject so
    the sidecar's sanitizer_version stays integer-typed."""
    with pytest.raises(ConfigError, match="version must be an integer"):
        load_config(_write(tmp_path, "version: 1.0\n"))


def test_version_string_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="version must be an integer"):
        load_config(_write(tmp_path, 'version: "1"\n'))


def test_extra_secret_pattern_re_prefix_empty_raises(tmp_path: Path) -> None:
    """``pattern: "re:"`` is empty after the prefix strip; ``re.compile("")``
    silently succeeds and matches every position, so we must reject it
    the same way ``_compile_rule`` does for paths/identifiers."""
    body = """
version: 1
extra_secret_patterns:
  - pattern: "re:"
    kind: "oops"
"""
    with pytest.raises(ConfigError, match="empty regex"):
        load_config(_write(tmp_path, body))


def test_extra_secret_pattern_bare_string_is_literal(tmp_path: Path) -> None:
    """Bare ``pattern`` strings in extras are treated as literals (escaped),
    matching how paths and identifiers handle bare ``match:`` values. The
    earlier loader compiled bare strings raw, so ``pattern: "C++"`` was
    silently a regex with a quantifier."""
    body = """
version: 1
extra_secret_patterns:
  - pattern: "C++"
    kind: "lang-tag"
"""
    config = load_config(_write(tmp_path, body))
    extra = config.extra_secret_patterns[0]
    # Literal compile: source pattern is re.escape("C++").
    assert extra.compiled.pattern == re.escape("C++")
    # The literal substring matches; the would-be regex 'C++' (one+ Cs)
    # would have matched a bare "C" too — verify it does NOT under our
    # literal interpretation.
    assert extra.compiled.search("C++") is not None
    assert extra.compiled.search("C") is None


def test_i3_self_rule_replace_contains_own_match(tmp_path: Path) -> None:
    """A rule whose own ``replace`` contains its own ``match`` is non-
    idempotent (a second pass would re-substitute) and leaks the original
    pattern through the sidecar. The earlier guard skipped the self-
    comparison and let this through."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/fdpearce-redacted"
"""
    with pytest.raises(ConfigError, match="not.+idempotent|own match"):
        load_config(_write(tmp_path, body))


def test_config_paths_are_immutable_tuple(tmp_path: Path) -> None:
    """Config(frozen=True) only blocks attribute reassignment; ensure the
    field types are tuples so callers cannot ``.append`` to bypass the
    I-3 guard post-validation."""
    body = """
version: 1
paths:
  - match: "/home/fdpearce"
    replace: "/home/user"
"""
    config = load_config(_write(tmp_path, body))
    assert isinstance(config.paths, tuple)
    assert isinstance(config.identifiers, tuple)
    assert isinstance(config.extra_secret_patterns, tuple)
    # And mutation attempts fail:
    with pytest.raises(AttributeError):
        config.paths.append(config.paths[0])  # type: ignore[attr-defined]


def test_load_config_expands_tilde(tmp_path: Path, monkeypatch) -> None:
    """``Path("~/...")`` does not auto-expand; load_config must expand so a
    quoted ``~/.ccs-sanitize.yaml`` from the CLI works."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _write(tmp_path, "version: 1\n")
    # Reference the file via tilde-prefixed string.
    config = load_config("~/config.yaml")
    assert config.version == 1


def test_non_utf8_config_raises_config_error(tmp_path: Path) -> None:
    """``read_text(encoding='utf-8')`` raises UnicodeDecodeError on non-
    UTF-8 input; load_config normalizes to ConfigError so the CLI's exit-
    code-3 mapping catches it."""
    p = tmp_path / "config.yaml"
    # 0xFF is not valid UTF-8 anywhere.
    p.write_bytes(b"version: 1\n# \xff\xfe broken bytes here\n")
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_config(p)


def test_empty_paths_section_is_treated_as_empty(tmp_path: Path) -> None:
    """``paths:`` with no value parses to ``None``; treat it as ``[]`` for
    consistency with ``options:`` which already returns defaults on None."""
    config = load_config(_write(tmp_path, "version: 1\npaths:\nidentifiers:\nextra_secret_patterns:\n"))
    assert config.paths == ()
    assert config.identifiers == ()
    assert config.extra_secret_patterns == ()


def test_options_defaults_only_apply_when_key_omitted(tmp_path: Path) -> None:
    """When the YAML sets an option explicitly, that value wins; defaults
    only fill in for omitted keys. Earlier the loader duplicated defaults
    in both the dataclass and ``_build_options``, which would silently
    disagree if the dataclass default changed."""
    body = "version: 1\noptions:\n  remap_uuids: true\n"
    config = load_config(_write(tmp_path, body))
    # Explicit setting wins.
    assert config.options.remap_uuids is True
    # Omitted option takes the dataclass default.
    assert config.options.scrub_git_branch is True


def test_rule_with_mismatched_compiled_raises() -> None:
    """Rule and ExtraSecretPattern are in __all__ so they're constructable
    directly. Without a __post_init__ consistency check, a caller could
    build a Rule(pattern="/foo", compiled=re.compile("BAR")) that lies
    about itself."""
    from ccs_sanitize.config import ExtraSecretPattern, Rule

    with pytest.raises(ValueError, match="does not match"):
        Rule(
            pattern="/foo",
            replace="/bar",
            is_regex=False,
            compiled=re.compile("BAR"),
        )
    with pytest.raises(ValueError, match="does not match"):
        # is_regex disagrees with pattern (no re: prefix).
        Rule(
            pattern="/foo",
            replace="/bar",
            is_regex=True,
            compiled=re.compile(re.escape("/foo")),
        )
    with pytest.raises(ValueError, match="does not match"):
        ExtraSecretPattern(
            pattern="literal",
            kind="kind",
            compiled=re.compile("DIFFERENT"),
        )
