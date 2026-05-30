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
  - ``default_skip_predicate`` — the PRD section 6b B skip-list, encoded as
    a predicate over JSON paths. The auditable question is "which fields do
    we deliberately NOT scrub?" — a short, reviewable list — instead of
    "did we remember to reach every field that might carry data?".
  - ``run_pipeline`` — the line loop. Parses each line, strips by ``type``,
    walks survivors through the transform, re-serializes with the pinned
    settings.

What this module does NOT ship:

  - Any rule logic (paths in #21, identifiers in #22, secrets in #23).
  - The residual secret scan / fail-closed orchestration around the
    pipeline (#24). The pipeline raises ``PipelineError`` on malformed
    JSONL; the residual scan and atomic write live in the CLI layer.
  - Sidecar emission (#25); the pipeline returns counts that the sidecar
    will consume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

JsonPath = tuple[str, ...]
JsonNode = Any
TransformCallback = Callable[[str, JsonPath], str]
SkipPredicate = Callable[[JsonPath], bool]

DEFAULT_STRIP_TYPES: frozenset[str] = frozenset({"file-history-snapshot", "attachment"})

# Per PRD section 6b B. Fields named here are NEVER passed to the transform
# callback. The set is intentionally short so the audit question is
# "is this list right?" rather than "did we reach every leaf?".
#
#   - identifier fields (UUID graph, request/tool/message ids)
#   - type/role/version/model identity fields (no PII; analytically valuable)
#   - thinking signatures (opaque blobs; replaced with a fixed placeholder
#     by a separate step, not by the rule layers)
_SKIP_LEAF_NAMES: frozenset[str] = frozenset({
    "version",
    "type",
    "role",
    "model",
    "uuid",
    "parentUuid",
    "sessionId",
    "agentId",
    "id",
    "requestId",
    "tool_use_id",
    "signature",
})


class PipelineError(ValueError):
    """Raised on malformed JSONL.

    Maps to CLI exit code 2 (safety failure, PRD section 11): on a security
    tool, a parse error means something is wrong with the input — no
    ``--skip-malformed`` escape hatch ships in v0.
    """


@dataclass(frozen=True)
class PipelineCounts:
    """Per-run tallies the sidecar will surface (PRD section 10).

    ``stripped_lines`` maps each stripped ``type`` value to the count of
    lines dropped for it. Only types actually encountered appear; a zero
    count is never written.
    """

    stripped_lines: dict[str, int] = field(default_factory=dict)


def default_skip_predicate(path: JsonPath) -> bool:
    """Return True if a string leaf at ``path`` must NOT be scrubbed.

    Encodes the PRD section 6b B skip-list. List indices are not part of
    ``path`` (the walker drops them), so the predicate compares only
    string keys.
    """
    if not path:
        return False
    last = path[-1]
    if last in _SKIP_LEAF_NAMES:
        return True
    if last.endswith("_tokens"):
        return True
    # ``usage.*`` defensively — usage entries are numeric in practice and
    # never reach the transform anyway, but skip them if a future format
    # adds a string-valued field under ``usage``.
    if "usage" in path:
        return True
    return False


def _identity_transform(leaf: str, path: JsonPath) -> str:
    return leaf


def walk_strings(
    node: JsonNode,
    transform: TransformCallback = _identity_transform,
    *,
    skip_predicate: SkipPredicate = default_skip_predicate,
    _path: JsonPath = (),
) -> JsonNode:
    """Recursively walk ``node`` and apply ``transform`` to every string
    leaf whose path is not skipped.

    Dicts and lists are rebuilt rather than mutated; CPython dict iteration
    preserves insertion order, so a structural copy round-trip is
    order-stable — this is what makes the I-1 serialization contract
    meaningful at the structure level too, not just the JSON token level.

    Non-string leaves are passed through untouched. Numbers, booleans, and
    None never reach the transform.
    """
    if isinstance(node, str):
        if skip_predicate(_path):
            return node
        return transform(node, _path)
    if isinstance(node, dict):
        return {
            key: walk_strings(
                value,
                transform,
                skip_predicate=skip_predicate,
                _path=_path + (key,),
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        # List indices are intentionally not part of the path; the skip-list
        # uses string keys only, and rule layers should not depend on
        # positional addressing.
        return [
            walk_strings(
                item,
                transform,
                skip_predicate=skip_predicate,
                _path=_path,
            )
            for item in node
        ]
    return node


def serialize_line(obj: JsonNode) -> str:
    """Re-serialize a parsed JSON object per PRD section 11 I-1.

    Pinning these parameters in one place is what turns "deterministic
    output" from a claim into a property. ``ensure_ascii=False`` keeps
    unicode content readable; ``separators=(',', ':')`` removes the
    whitespace ``json.dumps`` would otherwise insert.

    Keys are NOT sorted: a parsed line preserves its original key order
    (Python ``json.loads`` is insertion-order-stable), and ``walk_strings``
    rebuilds dicts preserving that order, so the round-trip is byte-stable
    for byte-stable input.
    """
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


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
            any non-blank line that fails to parse raises ``PipelineError``.
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
    """
    stripped: dict[str, int] = {}
    out: list[str] = []
    for index, raw in enumerate(_iter_records(lines)):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PipelineError(
                f"malformed JSONL on record {index}: {exc.msg} (col {exc.colno})"
            ) from exc
        if isinstance(obj, dict):
            line_type = obj.get("type")
            if isinstance(line_type, str) and line_type in strip_types:
                stripped[line_type] = stripped.get(line_type, 0) + 1
                continue
        transformed = walk_strings(obj, transform, skip_predicate=skip_predicate)
        out.append(serialize_line(transformed))
    return out, PipelineCounts(stripped_lines=stripped)


def _iter_records(lines: Iterable[str]) -> Iterator[str]:
    """Yield non-blank records. Trailing newlines and incidental blank
    lines from file iteration are dropped silently; anything else with
    non-whitespace content goes through to be parsed.
    """
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        yield stripped


__all__ = [
    "DEFAULT_STRIP_TYPES",
    "JsonPath",
    "PipelineCounts",
    "PipelineError",
    "SkipPredicate",
    "TransformCallback",
    "default_skip_predicate",
    "run_pipeline",
    "serialize_line",
    "walk_strings",
]
