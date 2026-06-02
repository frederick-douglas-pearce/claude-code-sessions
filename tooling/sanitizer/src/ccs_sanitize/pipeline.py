"""Line-oriented sanitization pipeline.

PRD reference:

  - section 6 — architecture overview (the line loop + layered transforms).
  - section 6b — line-type stripping (Step A) and structural traversal with
    skip-list (Step B). The two are coupled: every line that survives Step A
    is walked by Step B, never stringify-and-regex'd.
  - section 7 — consistency / determinism is the safety property.
  - section 11, I-1 — serialization is pinned: ``json.dumps`` with
    ``separators=(',', ':')`` and ``ensure_ascii=False``; original key
    order preserved (Python ``json.loads`` keeps insertion order, so a
    straight round-trip is order-stable — keys are NOT sorted).

What this module ships (issue #20):

  - ``DEFAULT_STRIP_TYPES`` — the ``--strip-types`` default (PRD section 6b A
    / D-7): ``file-history-snapshot`` and ``attachment`` lines are dropped
    wholesale rather than scrubbed.
  - ``walk_strings`` — recursive structural walker. Visits every string leaf
    whose JSON path is not skipped, applies a caller-supplied ``transform``,
    and returns the rebuilt structure. Non-string leaves (numbers, bool,
    None) are passed through.
  - ``default_skip_predicate`` / ``make_skip_predicate`` — the PRD section 6b B
    skip-list, encoded as a predicate over JSON paths. ``make_skip_predicate``
    is a factory so the identifier rule layer (#22) can pass
    ``remap_uuids=True`` to lift the UUID skip per PRD section 8. The
    auditable question is "which fields do we deliberately NOT scrub?" — a
    short, reviewable list — instead of "did we remember to reach every
    field that might carry data?".
  - ``run_pipeline`` — the line loop. Parses each line, strips by ``type``,
    walks survivors through the transform, re-serializes with the pinned
    settings.

What this module does NOT ship:

  - Any rule logic (paths in #21, identifiers in #22, secrets in #23).
  - The residual secret scan (#24): ``residual.py`` re-runs the secret-
    pattern detector over the serialized output as the final fail-closed
    gate. The pipeline raises ``PipelineError`` on malformed JSONL; the
    residual scan raises ``ResidualSecretError`` on a survivor.
  - Layer composition + the orchestration around them (#24):
    ``orchestrator.py`` chains the three rule layers into one
    transform, plugs it into ``run_pipeline``, and runs the residual
    gate. The atomic write that follows lives in the CLI layer (#26).
  - Sidecar emission (#25); the pipeline returns counts that the sidecar
    will consume.
  - The fixed-placeholder substitution for ``thinking.signature`` (PRD §2).
    The signature is currently skip-listed, which means it passes through
    unchanged. A later PR ships the placeholder step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping

JsonPath = tuple[str, ...]
JsonNode = Any
TransformCallback = Callable[[str, JsonPath], str]
SkipPredicate = Callable[[JsonPath], bool]

DEFAULT_STRIP_TYPES: frozenset[str] = frozenset({"file-history-snapshot", "attachment"})

# Per PRD section 6b B. Bare names skip-listed everywhere they appear. These
# names are PRD-documented as content-free identity/identifier fields with
# no user-data collision risk at any depth.
_SKIP_LEAF_NAMES: frozenset[str] = frozenset({
    "version",                                       # line-level format marker
    "type",                                          # line + content-block discriminator
    "role",                                          # message role (always known enum)
    "requestId",                                     # request identifier
    "tool_use_id",                                   # tool_result's link to its tool_use
})

# UUID-graph fields skip-listed when remap_uuids is False (the default).
# PRD section 6b B: "UUID fields (unless remap_uuids is on)".
_UUID_NAMES: frozenset[str] = frozenset({
    "uuid",
    "parentUuid",
    "sessionId",
    "agentId",
})

# Fields whose name overlaps with potential user-data field names ("id",
# "signature", "model"). PRD section 6b B specifies these by parent path
# (message.model, message.id, tool_use.id, thinking.signature); a bare-name
# skip would also exempt user content like ``tool_use.input.id`` from
# scrubbing, leaking PII. The walker drops list indices, so tool_use blocks
# inside the content array have parent "content" in the path.
_ANCHORED_PARENT_LAST_SKIPS: frozenset[tuple[str, str]] = frozenset({
    ("message", "model"),     # PRD: message.model
    ("message", "id"),        # PRD: message.id
    ("content", "id"),        # PRD: tool_use.id (under message.content[*])
    ("content", "signature"), # PRD: thinking.signature (under message.content[*])
})


class PipelineError(ValueError):
    """Raised on malformed JSONL.

    Maps to CLI exit code 2 (safety failure, PRD section 11): on a security
    tool, a parse error or shape violation means something is wrong with the
    input — no ``--skip-malformed`` escape hatch ships in v0.
    """


@dataclass(frozen=True)
class PipelineCounts:
    """Per-run tallies the sidecar will surface (PRD section 10).

    ``stripped_lines`` maps each stripped ``type`` value to the count of
    lines dropped for it. Only types actually encountered appear; a zero
    count is never written.

    ``blank_lines`` is the number of whitespace-only input lines the loop
    in ``run_pipeline`` skipped over. Surfacing the tally is what lets the
    sidecar's ``lines_processed`` equal the number of items the input
    iterable produced (``len(input_text.split("\n"))`` for the CLI):
    survivors + stripped + blanks. Without it, a file with interior blanks
    silently undercounts by the number of blanks. (Note: this is NOT
    literal ``wc -l`` parity -- ``split("\n")`` on a file ending in a
    trailing newline yields one extra empty element vs the newline count,
    which we count as a blank; the audit identity is "input items
    iterated", which equals ``wc -l`` only for files without a trailing
    newline.)

    The mapping is wrapped in a ``MappingProxyType`` after construction so
    callers cannot mutate the dict in place — the dataclass is frozen at the
    attribute level only, but the inner dict would otherwise share state with
    the function-local that built it (and could be mutated downstream,
    silently corrupting the sidecar's tallies).
    """

    stripped_lines: Mapping[str, int] = field(default_factory=dict)
    blank_lines: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "stripped_lines",
            MappingProxyType(dict(self.stripped_lines)),
        )


def make_skip_predicate(*, remap_uuids: bool = False) -> SkipPredicate:
    """Build a skip predicate honoring config options.

    Args:
        remap_uuids: When True, UUID fields (``uuid``, ``parentUuid``,
            ``sessionId``, ``agentId``) are NOT skipped — they're visited so
            the identifier rule layer can remap them consistently. PRD
            section 6b B: "UUID fields (unless ``remap_uuids`` is on)".

    Returns:
        A ``SkipPredicate`` callable that takes a JSON path and returns True
        when the leaf at that path should NOT be scrubbed.
    """
    bare_names = _SKIP_LEAF_NAMES if remap_uuids else _SKIP_LEAF_NAMES | _UUID_NAMES

    def predicate(path: JsonPath) -> bool:
        if not path:
            return False
        last = path[-1]
        if isinstance(last, str):
            if last in bare_names:
                return True
            if last.endswith("_tokens"):
                return True
        if len(path) >= 2:
            parent = path[-2]
            # Defense: any field whose immediate parent is ``usage`` (the
            # token-accounting block). PRD section 6b B scopes the skip
            # explicitly to ``usage.*``; a previous version of this predicate
            # used ``"usage" in path`` which over-skipped any descendant of
            # any ``usage`` key at any depth.
            if parent == "usage":
                return True
            if (parent, last) in _ANCHORED_PARENT_LAST_SKIPS:
                return True
        return False

    return predicate


default_skip_predicate: SkipPredicate = make_skip_predicate()


def _identity_transform(leaf: str, path: JsonPath) -> str:
    return leaf


def walk_strings(
    node: JsonNode,
    transform: TransformCallback = _identity_transform,
    *,
    skip_predicate: SkipPredicate = default_skip_predicate,
) -> JsonNode:
    """Recursively walk ``node`` and apply ``transform`` to every string
    leaf whose path is not skipped.

    Dicts and lists are rebuilt rather than mutated; CPython dict iteration
    preserves insertion order, so a structural copy round-trip is
    order-stable.

    Non-string leaves are passed through untouched. Numbers, booleans, and
    None never reach the transform.

    The recursion state (the current JSON path) is held in a nested helper
    so it does not leak into the public signature — earlier versions exposed
    a leading-underscore ``_path`` keyword, which Python does not actually
    treat as private and which callers could accidentally pass.
    """

    def _walk(value: JsonNode, path: JsonPath) -> JsonNode:
        if isinstance(value, str):
            if skip_predicate(path):
                return value
            return transform(value, path)
        if isinstance(value, dict):
            return {key: _walk(sub, path + (key,)) for key, sub in value.items()}
        if isinstance(value, list):
            # List indices are intentionally not part of the JSON path — the
            # skip-list is keyed on field names only, and rule layers should
            # not rely on positional addressing of array elements.
            return [_walk(item, path) for item in value]
        return value

    return _walk(node, ())


def serialize_line(obj: JsonNode) -> str:
    """Re-serialize a parsed JSON object per PRD section 11 I-1.

    Pinning these parameters in one place is what turns "deterministic
    output" from a claim into a property. ``ensure_ascii=False`` keeps
    unicode content readable (callers MUST write the result as UTF-8;
    locale-default encodings on Windows can mangle non-ASCII).
    ``separators=(',', ':')`` removes the whitespace ``json.dumps`` would
    otherwise insert. ``allow_nan=False`` forbids ``NaN`` / ``Infinity``
    output (which is non-RFC-8259 JSON and would surface as a corrupt line
    downstream); a NaN/Infinity in the parsed tree raises ``PipelineError``.

    Keys are NOT sorted: a parsed line preserves its original key order
    (Python ``json.loads`` is insertion-order-stable) and ``walk_strings``
    rebuilds dicts preserving that order. Two runs of the pipeline over the
    same parsed object produce byte-identical output, which is the
    determinism contract the residual scan and fixture-validator depend on.

    Strict source-byte preservation is NOT a goal — numeric literals
    normalize through ``json.dumps`` (e.g. ``1e10`` becomes
    ``10000000000.0``) and other small format-level normalizations are
    inherent to round-tripping through Python's ``json`` module.
    """
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError as exc:
        # json.dumps raises ValueError on NaN/Infinity when allow_nan=False.
        raise PipelineError(f"non-finite number in input: {exc}") from exc


def run_pipeline(
    lines: Iterable[str],
    *,
    strip_types: frozenset[str] = DEFAULT_STRIP_TYPES,
    transform: TransformCallback = _identity_transform,
    skip_predicate: SkipPredicate = default_skip_predicate,
) -> tuple[list[str], PipelineCounts]:
    """Run the pipeline over an iterable of JSONL lines.

    Args:
        lines: input JSONL records (one per element). Whitespace-only
            elements are tolerated (newline residue from file iteration);
            any non-blank line that fails to parse or has the wrong shape
            raises ``PipelineError``.
        strip_types: line ``type`` values to drop wholesale (PRD section 6b A).
        transform: callable invoked on each string leaf surviving the
            skip-list. Defaults to identity, so a rule-free pipeline is a
            structural pass-through.
        skip_predicate: callable returning True for leaves NOT to scrub.

    Returns:
        A pair of ``(serialized_lines, counts)``. ``serialized_lines`` is
        the list of re-serialized JSONL records in original order, with
        stripped lines absent. ``counts.stripped_lines`` reports the
        per-type drop tally; rule-level counts are accumulated by the
        transform itself (typically into a ``SubstitutionTable``).

    Raises:
        ``PipelineError`` for malformed JSONL, non-object records, or
        records whose ``type`` field is missing or non-string. Line numbers
        in the error message are 1-indexed positions in the input iterable,
        so they map to the source file lines a user can locate.
    """
    stripped: dict[str, int] = {}
    out: list[str] = []
    blank_lines = 0
    for line_number, record in _iter_records(lines):
        if not record:
            blank_lines += 1
            continue
        try:
            obj = json.loads(record)
        except json.JSONDecodeError as exc:
            raise PipelineError(
                f"malformed JSONL at line {line_number}: {exc.msg} (col {exc.colno})"
            ) from exc
        if not isinstance(obj, dict):
            raise PipelineError(
                f"line {line_number}: record must be a JSON object, got {type(obj).__name__}"
            )
        if "type" not in obj:
            raise PipelineError(
                f"line {line_number}: missing required 'type' field"
            )
        line_type = obj["type"]
        if not isinstance(line_type, str):
            raise PipelineError(
                f"line {line_number}: 'type' field must be a string, got {type(line_type).__name__}"
            )
        if line_type in strip_types:
            stripped[line_type] = stripped.get(line_type, 0) + 1
            continue
        transformed = walk_strings(obj, transform, skip_predicate=skip_predicate)
        out.append(serialize_line(transformed))
    return out, PipelineCounts(stripped_lines=stripped, blank_lines=blank_lines)


def _iter_records(lines: Iterable[str]) -> Iterator[tuple[int, str]]:
    """Yield ``(input_line_number, stripped_line)`` for EVERY input line.

    Whitespace-only lines are yielded with their stripped form (the empty
    string); the caller decides whether to treat them as blanks (counting
    for ``PipelineCounts.blank_lines``) or as records (parsing as JSON).
    Pushing the blank/record decision up to ``run_pipeline`` is what lets
    ``lines_processed`` cover interior blank lines (#43) -- earlier the
    helper silently dropped blanks here and the count was unrecoverable,
    so a file with interior whitespace lines undercounted.

    The line number is 1-indexed and tracks the original input position so
    ``PipelineError`` messages can name the file line a user can locate.
    """
    for line_number, raw in enumerate(lines, start=1):
        yield line_number, raw.strip()


__all__ = [
    "DEFAULT_STRIP_TYPES",
    "JsonPath",
    "PipelineCounts",
    "PipelineError",
    "SkipPredicate",
    "TransformCallback",
    "default_skip_predicate",
    "make_skip_predicate",
    "run_pipeline",
    "serialize_line",
    "walk_strings",
]
