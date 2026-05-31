"""YAML config loader for path/identifier rules and additive secret patterns.

PRD reference:

  - section 12 — hybrid config model (D-1). Secrets are code-defined and
    non-weakenable; paths and identifiers are YAML-configured per project;
    ``extra_secret_patterns`` is additive only.
  - section 10 — the sidecar reproduces ``replace`` values verbatim, so a
    misconfigured rule whose replacement is itself sensitive would leak
    through the sidecar (I-3). ``load_config`` runs the replacement-leak
    guard at load time: any path/identifier ``replace`` that matches any
    other path rule (including itself), any identifier rule, or any built-in /
    extra secret pattern is rejected with a typed error.

CLI wiring (translating ``ConfigError`` to exit code 3 per PRD section 11)
lands with #26. A missing config file surfaces as ``FileNotFoundError`` and
maps to exit 1 (usage error) at the CLI layer; other I/O or decoding errors
from the loader are normalized to ``ConfigError`` so the CLI can distinguish
them cleanly.

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

from .rules.secrets import COMPILED_SECRET_PATTERNS

_SUPPORTED_VERSION = 1
_REGEX_PREFIX = "re:"

_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {"version", "paths", "identifiers", "options", "extra_secret_patterns"}
)
_ALLOWED_RULE_KEYS = frozenset({"match", "replace"})
_ALLOWED_OPTION_KEYS = frozenset({"scrub_git_branch", "remap_uuids", "uuid_seed"})
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

    ``__post_init__`` validates that ``compiled`` and ``is_regex`` are
    consistent with ``pattern``, so direct ``Rule(...)`` construction
    (the type is public via ``__all__``) cannot produce a desynced object
    that the I-3 guard would silently miscompare against.
    """

    pattern: str
    replace: str
    is_regex: bool
    compiled: re.Pattern[str]

    def __post_init__(self) -> None:
        expected_is_regex = self.pattern.startswith(_REGEX_PREFIX)
        expected_source = (
            self.pattern[len(_REGEX_PREFIX) :]
            if expected_is_regex
            else re.escape(self.pattern)
        )
        if self.is_regex != expected_is_regex:
            raise ValueError(
                f"Rule.is_regex={self.is_regex} does not match pattern={self.pattern!r}"
            )
        if self.compiled.pattern != expected_source:
            raise ValueError(
                f"Rule.compiled.pattern={self.compiled.pattern!r} does not match "
                f"expected {expected_source!r} derived from pattern={self.pattern!r}"
            )


@dataclass(frozen=True)
class ExtraSecretPattern:
    """A user-supplied additive secret pattern (PRD section 9).

    Schema parity with ``Rule``: bare ``pattern`` strings are treated as
    literals (escaped to a regex), strings prefixed with ``re:`` are
    compiled as regex — matching how paths and identifiers behave. The
    earlier version of this loader compiled bare strings raw, which created
    surprising semantics for users writing ``pattern: "C++"`` or similar.
    """

    pattern: str
    kind: str
    compiled: re.Pattern[str]

    def __post_init__(self) -> None:
        if self.pattern.startswith(_REGEX_PREFIX):
            expected_source = self.pattern[len(_REGEX_PREFIX) :]
        else:
            expected_source = re.escape(self.pattern)
        if self.compiled.pattern != expected_source:
            raise ValueError(
                f"ExtraSecretPattern.compiled.pattern={self.compiled.pattern!r} does not "
                f"match expected {expected_source!r} derived from pattern={self.pattern!r}"
            )


@dataclass(frozen=True)
class ConfigOptions:
    scrub_git_branch: bool = True
    remap_uuids: bool = False
    # UUID-remap seed (PRD section 8 — "fixed seed"). Same seed across runs
    # and files yields the same remapped UUIDs, which is what keeps the
    # parent↔subagent graph coherent when sanitizing files independently.
    # Surfacing the seed on the config (rather than burying it in a function
    # default) makes the determinism contract auditable: the sidecar can
    # report which seed produced its substitution table, and changing the
    # seed in a config diff signals that the byte-output for every UUID in
    # every fixture will change.
    uuid_seed: str = "ccs-sanitize/v1"


@dataclass(frozen=True)
class Config:
    """Validated, immutable config tree.

    Field lists (``paths``, ``identifiers``, ``extra_secret_patterns``) are
    converted to tuples in ``__post_init__`` so that ``Config`` is
    structurally immutable. A frozen dataclass with mutable ``list`` fields
    would allow downstream code to ``config.paths.append(...)`` post-
    validation, bypassing the I-3 replacement-leak guard that ran at load
    time. Tuples keep the iteration ergonomics callers expect while
    blocking that bypass.
    """

    version: int
    paths: tuple[Rule, ...] = ()
    identifiers: tuple[Rule, ...] = ()
    options: ConfigOptions = field(default_factory=ConfigOptions)
    extra_secret_patterns: tuple[ExtraSecretPattern, ...] = ()

    def __post_init__(self) -> None:
        # Accept lists at construction time (the loader builds lists), but
        # store as tuples so the public surface is immutable.
        if not isinstance(self.paths, tuple):
            object.__setattr__(self, "paths", tuple(self.paths))
        if not isinstance(self.identifiers, tuple):
            object.__setattr__(self, "identifiers", tuple(self.identifiers))
        if not isinstance(self.extra_secret_patterns, tuple):
            object.__setattr__(
                self, "extra_secret_patterns", tuple(self.extra_secret_patterns)
            )


def load_config(path: Path | str) -> Config:
    """Load and validate a sanitizer config file.

    The path's ``~`` prefix is expanded so callers can pass
    ``~/.ccs-sanitize.yaml`` without pre-expansion. Read errors and
    decode errors are normalized to ``ConfigError`` so the CLI layer
    sees a single error class for every config-stage failure other than
    "file does not exist".

    Raises:
        FileNotFoundError: the path does not exist (CLI maps to exit 1).
        ConfigError: I/O error, file is not UTF-8, YAML is malformed,
            schema is violated, a regex fails to compile, or the I-3
            replacement-leak guard fires (CLI maps to exit 3).
    """
    path = Path(path).expanduser()

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"config file is not valid UTF-8: {path} ({exc})"
        ) from exc
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc

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

    if "version" not in data:
        raise ConfigError("missing required field: version")
    version = data["version"]
    # bool is a subclass of int in Python, so `True == 1` and `False == 0`;
    # float `1.0` also compares equal to `1`. Without the isinstance gate, a
    # YAML body of ``version: true`` or ``version: 1.0`` would pass the
    # equality check and produce a Config carrying a non-int version. The
    # sidecar then serializes that value into ``sanitizer_version:``, which
    # downstream consumers (fixture-validator, sibling projects) expect to
    # be an integer.
    if isinstance(version, bool) or not isinstance(version, int):
        raise ConfigError(
            f"version must be an integer, got {type(version).__name__}: {version!r}"
        )
    if version != _SUPPORTED_VERSION:
        raise ConfigError(
            f"unsupported config version: {version!r} "
            f"(this sanitizer reads version {_SUPPORTED_VERSION})"
        )

    paths = _build_rules(data.get("paths"), section="paths")
    identifiers = _build_rules(data.get("identifiers"), section="identifiers")
    options = _build_options(data.get("options"))
    extras = _build_extras(data.get("extra_secret_patterns"))

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
    # ``section:`` written with no value parses to ``None``; treat as empty.
    # The earlier version raised ConfigError here for paths/identifiers/extras
    # while ``options:`` accepted None as defaults — a usability inconsistency
    # since users naturally write ``paths:`` to mean "no rules".
    if raw is None:
        return []
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
    pattern_text, is_regex = _split_regex_prefix(pattern_str, where=where)
    if is_regex:
        try:
            compiled = re.compile(pattern_text)
        except re.error as exc:
            raise ConfigError(
                f"{where}.match: invalid regex {pattern_text!r}: {exc}"
            ) from exc
        _reject_zero_width_pattern(pattern_str, compiled, where=where)
        return Rule(pattern=pattern_str, replace=replace, is_regex=True, compiled=compiled)
    # Literal: escape so a single Pattern.search() works uniformly. Literal
    # patterns can never be zero-width here (empty literals are rejected
    # upstream in ``_build_rules``), so no zero-width check is needed.
    return Rule(
        pattern=pattern_str,
        replace=replace,
        is_regex=False,
        compiled=re.compile(re.escape(pattern_text)),
    )


def _reject_zero_width_pattern(
    pattern_str: str, compiled: re.Pattern[str], *, where: str
) -> None:
    """Reject patterns whose compiled regex matches the empty string at
    position 0 with zero width.

    Catches anchors (``^``, ``$``, ``\\A``, ``\\Z``), empty groups
    (``(?:)``), and unbounded-optional quantifiers (``.*``, ``a*``,
    ``a?``). These match zero characters at every position, so as a rule
    pattern they would either substitute at every zero-width position in
    every leaf or pollute the substitution audit log with ('' -> X) rows
    the sidecar (PRD section 10) cannot interpret.

    PRD section 11 fail-closed posture: a security tool surfaces
    misconfigured rules loudly, rather than silently no-op-ing them.
    The rule layer's runtime guard (``rules/_engine.py`` ``apply_rule``)
    remains for input-dependent zero-width matches the static check
    cannot see (lookaheads, ``\\b``).
    """
    test_match = compiled.match("")
    if test_match is not None and test_match.start() == test_match.end():
        raise ConfigError(
            f"{where}.match: pattern {pattern_str!r} matches the empty "
            f"string with zero width. Anchor-only patterns (^, $, (?:)) "
            f"and unbounded-optional patterns (.*, a*, a?) cannot scrub "
            f"any content; tighten to a consuming form (e.g. .+ instead "
            f"of .*) or use a literal match."
        )


def _split_regex_prefix(pattern_str: str, *, where: str) -> tuple[str, bool]:
    """Split a YAML pattern string into ``(source, is_regex)``.

    Raises ``ConfigError`` if the input is ``"re:"`` (empty after prefix
    strip). Shared between ``_compile_rule`` and ``_build_extras`` so
    extras get the same empty-regex guard.
    """
    if pattern_str.startswith(_REGEX_PREFIX):
        pattern_text = pattern_str[len(_REGEX_PREFIX) :]
        if not pattern_text:
            raise ConfigError(f"{where}: empty regex after 're:' prefix")
        return pattern_text, True
    return pattern_str, False


def _build_options(raw: Any) -> ConfigOptions:
    if raw is None:
        return ConfigOptions()
    if not isinstance(raw, dict):
        raise ConfigError(f"options must be a mapping, got {type(raw).__name__}")
    _check_unknown_keys(raw, _ALLOWED_OPTION_KEYS, "options")
    # Forward only the keys actually present in YAML so the dataclass owns
    # the defaults. Listing the defaults here too would mean a future change
    # to ``ConfigOptions``' default values silently disagrees with this
    # function for explicitly-set keys vs omitted keys.
    kwargs: dict[str, Any] = {}
    if "scrub_git_branch" in raw:
        kwargs["scrub_git_branch"] = _require_bool(
            raw["scrub_git_branch"], "options.scrub_git_branch"
        )
    if "remap_uuids" in raw:
        kwargs["remap_uuids"] = _require_bool(
            raw["remap_uuids"], "options.remap_uuids"
        )
    if "uuid_seed" in raw:
        seed = raw["uuid_seed"]
        if not isinstance(seed, str) or not seed:
            raise ConfigError(
                f"options.uuid_seed must be a non-empty string, got "
                f"{type(seed).__name__}: {seed!r}"
            )
        kwargs["uuid_seed"] = seed
    return ConfigOptions(**kwargs)


def _require_bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            f"{where} must be a boolean, got {type(value).__name__}"
        )
    return value


def _build_extras(raw: Any) -> list[ExtraSecretPattern]:
    if raw is None:
        return []
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
        # Mirror _compile_rule so extras have parity with paths/identifiers:
        # bare strings are literals (re.escape'd); ``re:``-prefixed strings
        # are regex. The earlier loader compiled bare strings raw, which
        # silently turned ``pattern: "C++"`` into a regex with a quantifier.
        pattern_text, is_regex = _split_regex_prefix(
            pattern_value, where=f"{where}.pattern"
        )
        try:
            compiled = re.compile(pattern_text if is_regex else re.escape(pattern_text))
        except re.error as exc:
            raise ConfigError(
                f"{where}.pattern: invalid regex {pattern_text!r}: {exc}"
            ) from exc
        if is_regex:
            _reject_zero_width_pattern(
                pattern_value, compiled, where=f"{where}.pattern"
            )
        out.append(
            ExtraSecretPattern(pattern=pattern_value, kind=kind, compiled=compiled)
        )
    return out


def _check_replacement_leak(config: Config) -> None:
    """I-3: a replacement may not itself match any built-in or configured
    path/identifier/secret rule.

    The sidecar reproduces replacements verbatim (PRD section 10), so a
    config that maps a sensitive token to another sensitive token, or that
    happens to use a generic-looking placeholder that itself looks like a
    credential pattern, would leak through the sidecar even though the
    output file is clean.

    The rule-vs-rule loop deliberately includes the self-comparison: a
    rule whose own ``replace`` contains its own ``match`` is a non-
    idempotent rule (a second pass would re-substitute) and a sidecar leak
    in its own right.
    """
    all_rules = [("paths", r) for r in config.paths] + [
        ("identifiers", r) for r in config.identifiers
    ]

    # Function-local import: identifiers.py imports from this module
    # (config.Rule), so a top-level import here would cycle. The leak
    # check only runs at load_config time, so per-call cost is fine.
    from .rules.identifiers import GIT_BRANCH_PLACEHOLDER

    for section, rule in all_rules:
        for other_section, other in all_rules:
            if other.compiled.search(rule.replace):
                if other is rule:
                    raise ConfigError(
                        f"{section} rule replacement {rule.replace!r} matches "
                        f"its own match {rule.pattern!r} — the rule is not "
                        f"idempotent and would leak the original pattern "
                        f"through the sidecar (PRD section 10, I-3)"
                    )
                raise ConfigError(
                    f"{section} rule replacement {rule.replace!r} matches "
                    f"{other_section} rule match {other.pattern!r} — "
                    f"replacements must not themselves match any other rule "
                    f"(PRD section 10, I-3)"
                )
        for pattern, label in COMPILED_SECRET_PATTERNS:
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
        # I-3 extension: reject any user rule whose pattern matches the
        # gitBranch placeholder. Otherwise the gitBranch substitution
        # (which records real_branch -> "feature/example") and the user
        # rule (which records "feature/example" -> replace) both fire on
        # the same string, producing a sidecar that contradicts itself
        # and an output file whose gitBranch field shows the placeholder
        # while every other leaf shows the user's replacement.
        if rule.compiled.search(GIT_BRANCH_PLACEHOLDER):
            raise ConfigError(
                f"{section} rule match {rule.pattern!r} matches the "
                f"gitBranch placeholder {GIT_BRANCH_PLACEHOLDER!r} — "
                f"a user rule that catches the placeholder would record "
                f"a substitution conflicting with the gitBranch field "
                f"substitution (PRD section 10, I-3)"
            )


__all__ = [
    "Config",
    "ConfigError",
    "ConfigOptions",
    "ExtraSecretPattern",
    "Rule",
    "load_config",
]
