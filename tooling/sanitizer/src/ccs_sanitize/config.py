"""YAML config loader for path/identifier rules and additive secret patterns.

PRD reference:

  - section 12 — hybrid config model (D-1). Secrets are code-defined and
    non-weakenable; paths and identifiers are YAML-configured per project;
    ``extra_secret_patterns`` is additive only.
  - section 10 — the sidecar reproduces ``replace`` values verbatim, so a
    misconfigured rule whose replacement is itself sensitive would leak
    through the sidecar (I-3). ``load_config`` runs the replacement-leak
    guard at load time: any path/identifier ``replace`` that matches any
    other path rule, any identifier rule, or any built-in/extra secret
    pattern is rejected with a typed error.

CLI wiring (translating ``ConfigError`` to exit code 3 per PRD section 11)
lands with #26. A missing config file surfaces as ``FileNotFoundError`` and
maps to exit 1 (usage error) at the CLI layer.

The YAML schema uses ``match:`` per the PRD; the Python field is named
``pattern`` to avoid visual collision with Python's ``match``/``case``
statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .rules.secrets import SECRET_PATTERNS

_SUPPORTED_VERSION = 1
_REGEX_PREFIX = "re:"

_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {"version", "paths", "identifiers", "options", "extra_secret_patterns"}
)
_ALLOWED_RULE_KEYS = frozenset({"match", "replace"})
_ALLOWED_OPTION_KEYS = frozenset({"scrub_git_branch", "remap_uuids"})
_ALLOWED_EXTRA_KEYS = frozenset({"pattern", "kind"})


class ConfigError(ValueError):
    """Raised when a config file fails to load or validate.

    Maps to CLI exit code 3 (PRD section 11) when caught at the CLI layer.
    The message names the offending field/rule so a human reviewer can fix
    it without digging.
    """


@dataclass(frozen=True)
class Rule:
    """A path or identifier rule.

    ``pattern`` is the YAML ``match:`` value as written (with the ``re:``
    prefix preserved if regex). ``compiled`` is the regex used for matching:

      - Literal rules compile to ``re.escape(pattern)`` so the I-3 guard and
        future scrub layers can use one ``re.Pattern`` code path.
      - Regex rules compile the substring after ``re:``.
    """

    pattern: str
    replace: str
    is_regex: bool
    compiled: re.Pattern[str]


@dataclass(frozen=True)
class ExtraSecretPattern:
    pattern: str
    kind: str
    compiled: re.Pattern[str]


@dataclass(frozen=True)
class ConfigOptions:
    scrub_git_branch: bool = True
    remap_uuids: bool = False


@dataclass(frozen=True)
class Config:
    version: int
    paths: list[Rule] = field(default_factory=list)
    identifiers: list[Rule] = field(default_factory=list)
    options: ConfigOptions = field(default_factory=ConfigOptions)
    extra_secret_patterns: list[ExtraSecretPattern] = field(default_factory=list)


def load_config(path: Path | str) -> Config:
    """Load and validate a sanitizer config file.

    Raises:
        FileNotFoundError: the path does not exist (CLI maps to exit 1).
        ConfigError: YAML is malformed, schema is violated, a regex fails
            to compile, or the I-3 replacement-leak guard fires.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed YAML in {path}: {exc}") from exc

    if data is None:
        raise ConfigError(f"empty config file: {path}")
    if not isinstance(data, dict):
        raise ConfigError(
            f"config root must be a mapping, got {type(data).__name__}: {path}"
        )

    _check_unknown_keys(data, _ALLOWED_TOP_LEVEL_KEYS, "<root>")

    version = data.get("version")
    if version is None:
        raise ConfigError("missing required field: version")
    if version != _SUPPORTED_VERSION:
        raise ConfigError(
            f"unsupported config version: {version!r} (this sanitizer reads version {_SUPPORTED_VERSION})"
        )

    paths = _build_rules(data.get("paths", []), section="paths")
    identifiers = _build_rules(data.get("identifiers", []), section="identifiers")
    options = _build_options(data.get("options", {}))
    extras = _build_extras(data.get("extra_secret_patterns", []))

    config = Config(
        version=version,
        paths=paths,
        identifiers=identifiers,
        options=options,
        extra_secret_patterns=extras,
    )

    _check_replacement_leak(config)
    return config


def _check_unknown_keys(
    mapping: dict[str, Any], allowed: frozenset[str], where: str
) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise ConfigError(
            f"unknown key(s) in {where}: {sorted(extra)!r} "
            f"(allowed: {sorted(allowed)!r})"
        )


def _build_rules(raw: Any, *, section: str) -> list[Rule]:
    if not isinstance(raw, list):
        raise ConfigError(
            f"{section} must be a list, got {type(raw).__name__}"
        )
    rules: list[Rule] = []
    for index, item in enumerate(raw):
        where = f"{section}[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{where} must be a mapping, got {type(item).__name__}")
        _check_unknown_keys(item, _ALLOWED_RULE_KEYS, where)
        pattern_str = item.get("match")
        replace = item.get("replace")
        if not isinstance(pattern_str, str) or not pattern_str:
            raise ConfigError(f"{where}.match must be a non-empty string")
        if not isinstance(replace, str):
            raise ConfigError(f"{where}.replace must be a string")
        rules.append(_compile_rule(pattern_str, replace, where=where))
    return rules


def _compile_rule(pattern_str: str, replace: str, *, where: str) -> Rule:
    if pattern_str.startswith(_REGEX_PREFIX):
        pattern_text = pattern_str[len(_REGEX_PREFIX) :]
        if not pattern_text:
            raise ConfigError(f"{where}.match: empty regex after 're:' prefix")
        try:
            compiled = re.compile(pattern_text)
        except re.error as exc:
            raise ConfigError(
                f"{where}.match: invalid regex {pattern_text!r}: {exc}"
            ) from exc
        return Rule(pattern=pattern_str, replace=replace, is_regex=True, compiled=compiled)
    # Literal: escape so a single Pattern.search() works uniformly.
    return Rule(
        pattern=pattern_str,
        replace=replace,
        is_regex=False,
        compiled=re.compile(re.escape(pattern_str)),
    )


def _build_options(raw: Any) -> ConfigOptions:
    if raw is None:
        return ConfigOptions()
    if not isinstance(raw, dict):
        raise ConfigError(f"options must be a mapping, got {type(raw).__name__}")
    _check_unknown_keys(raw, _ALLOWED_OPTION_KEYS, "options")
    return ConfigOptions(
        scrub_git_branch=_require_bool(
            raw.get("scrub_git_branch", True), "options.scrub_git_branch"
        ),
        remap_uuids=_require_bool(
            raw.get("remap_uuids", False), "options.remap_uuids"
        ),
    )


def _require_bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            f"{where} must be a boolean, got {type(value).__name__}"
        )
    return value


def _build_extras(raw: Any) -> list[ExtraSecretPattern]:
    if not isinstance(raw, list):
        raise ConfigError(
            f"extra_secret_patterns must be a list, got {type(raw).__name__}"
        )
    out: list[ExtraSecretPattern] = []
    for index, item in enumerate(raw):
        where = f"extra_secret_patterns[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{where} must be a mapping, got {type(item).__name__}")
        _check_unknown_keys(item, _ALLOWED_EXTRA_KEYS, where)
        pattern_value = item.get("pattern")
        kind = item.get("kind")
        if not isinstance(pattern_value, str) or not pattern_value:
            raise ConfigError(f"{where}.pattern must be a non-empty string")
        if not isinstance(kind, str) or not kind:
            raise ConfigError(f"{where}.kind must be a non-empty string")
        pattern_text = (
            pattern_value[len(_REGEX_PREFIX) :]
            if pattern_value.startswith(_REGEX_PREFIX)
            else pattern_value
        )
        try:
            compiled = re.compile(pattern_text)
        except re.error as exc:
            raise ConfigError(
                f"{where}.pattern: invalid regex {pattern_text!r}: {exc}"
            ) from exc
        out.append(ExtraSecretPattern(pattern=pattern_value, kind=kind, compiled=compiled))
    return out


def _check_replacement_leak(config: Config) -> None:
    """I-3: a replacement may not itself match any built-in or configured
    path/identifier/secret rule.

    The sidecar reproduces replacements verbatim (PRD section 10), so a
    config that maps a sensitive token to another sensitive token, or that
    happens to use a generic-looking placeholder that itself looks like a
    credential pattern, would leak through the sidecar even though the
    output file is clean.
    """
    builtins: list[tuple[re.Pattern[str], str]] = [
        (re.compile(pat), label) for pat, label in SECRET_PATTERNS
    ]

    all_rules = [("paths", r) for r in config.paths] + [
        ("identifiers", r) for r in config.identifiers
    ]

    for section, rule in all_rules:
        for other_section, other in all_rules:
            if other is rule:
                continue
            if other.compiled.search(rule.replace):
                raise ConfigError(
                    f"{section} rule replacement {rule.replace!r} matches "
                    f"{other_section} rule match {other.pattern!r} — replacements "
                    f"must not themselves match any other rule (PRD section 10, I-3)"
                )
        for pattern, label in builtins:
            if pattern.search(rule.replace):
                raise ConfigError(
                    f"{section} rule replacement {rule.replace!r} matches "
                    f"built-in secret pattern {label!r} — pick a non-leaky "
                    f"placeholder (e.g. /home/user, user@example.com)"
                )
        for extra in config.extra_secret_patterns:
            if extra.compiled.search(rule.replace):
                raise ConfigError(
                    f"{section} rule replacement {rule.replace!r} matches "
                    f"extra_secret_patterns rule {extra.kind!r}"
                )


__all__ = [
    "Config",
    "ConfigError",
    "ConfigOptions",
    "ExtraSecretPattern",
    "Rule",
    "load_config",
]
