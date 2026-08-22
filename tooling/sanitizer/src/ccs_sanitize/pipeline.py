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

# ---------------------------------------------------------------------------
# The skip allow-list (PRD section 6b B), keyed on ROOT-ANCHORED paths.
#
# Issue #194. Every rule this replaced matched depth-agnostically -- a bare
# leaf name, a ``_tokens`` suffix, ``path[-2] == "usage"``, or a
# ``(parent, last)`` pair. ``tool_use.input`` is arbitrary tool-defined JSON
# and MCP servers define their own schemas, so every one of those rules fired
# inside it: a tool parameter named ``type``/``version``/``sessionId``/
# ``max_tokens`` sat at a position the walker refused to visit. The value
# survived, the run exited 0, and the sidecar reported ``residual_scan:
# clean``. #195's output-side oracle turns that into a fail-closed refusal for
# *literal* rules, but it deliberately does not re-verify regex rules
# (``residual.scan_residual_rules``), so for a ``re:`` config it stayed a
# SILENT leak.
#
# The fix is an inversion, not a longer name list: enumerating positions
# cannot close an unbounded space, but enumerating the FORMAT's own positions
# can. ``walk_strings`` already builds a rooted path, so matching the whole
# path instead of its tail makes an unlisted position VISITED AND SCRUBBED
# rather than silently skipped. That reverses the failure direction: a format
# field this list forgets gets over-scrubbed rather than user data being
# silently skipped.
#
# BE PRECISE ABOUT WHAT CATCHES THAT, because the obvious candidate does not.
# ``test_golden_determinism.py`` does NOT detect a dropped entry -- removing
# any single one leaves the golden output byte-identical, verified by ablating
# all 29. That is inherent: the golden config carries only literal PII rules
# and no format-marker value contains one, which is the same reason the Tier C
# note below says visiting those positions is a no-op today. An earlier draft
# of this comment claimed the golden test was the safety net; it is not, and
# on a tool whose subject is that an attestation must not outrun what was
# verified, that claim was worth more than the coverage it described.
#
# What actually guards this list lives in ``tests/test_skip_allow_list_corpus.py``:
# the contents are PINNED literally (any add or remove goes red), every entry
# must appear in the corpus, every entry is ablation-tested against a config
# whose rule matches the value at that position, and the set of allow-listed
# NAMES appearing at non-allow-listed PATHS is pinned. What none of them
# catches is a genuinely new format position with a name nothing on the list
# uses.
#
# THAT GAP IS OPEN, NOT COVERED, and it is tracked in #201. Earlier wording
# here said the format-watch queue and human review "are for" that, which
# reads as a mechanical check considered and declined in favour of people.
# The real state is that #194's AC-10 asked for a ``format-scan`` drift check
# as a fast-follow. There is live evidence the human process is the leaky
# link: the corpus carries UUID-graph edges (``sourceToolAssistantUUID``,
# ``leafUuid`` -- #202) that no list here enumerates, and finding them by hand
# took four review rounds and a mutation pass. A mechanical corpus-vs-list
# diff would have surfaced them on day one. Until #201 ships, treat human
# review as what is actually happening, not as coverage.
#
# NO SUBTREE PREFIXES. An entry is an exact path. A "skip everything under
# X" rule is the ``"usage" in path`` membership test this module already
# deleted once (see ``make_skip_predicate``), merely rooted, and it fails the
# same way: ``error.*`` alone carries ``error.headers.set-cookie``,
# ``error.headers.anthropic-organization-id`` and
# ``error.error.error.message``, all of which are scrubbed today and all of
# which a prefix would exempt. Every entry below was verified present in
# fixtures/ (8 files, 1494 records, v2.1.150-2.1.185); the position survey is
# recorded on issue #194.

# Tier A -- load-bearing preserves. The value COULD match a configured rule,
# so visiting it would actually change bytes. This is the tier that earns its
# keep.
#
# The UUID-graph paths are separate because ``remap_uuids`` lifts them (PRD
# section 6b B: "UUID fields (unless remap_uuids is on)"), and because
# ``rules.identifiers`` must remap exactly these positions -- the two sides are
# pinned equal by ``test_uuid_transform_positions_match_pipeline_allow_list``.
#
# ``toolUseResult.agentId`` is in this set and NOT in the identifier tier
# below, because it is the parent side of a CROSS-FILE link: a parent session
# names the subagent it invoked, and that subagent's own top-level ``agentId``
# lives in a different file. The two must remap to the same value or the graph
# breaks, which is exactly what a shared ``uuid_seed`` is for.
#
# THE AUTHORITY IS THE FORMAT CONTRACT, NOT THE CORPUS: the reference docs
# state that a parent's ``toolUseResult.agentId`` equals the invoked subagent's
# own top-level ``agentId`` in a different file (reference/data-dictionary.md,
# the overflow-subdirectory section; reference/subagent-traces.md). That is why
# both positions remap under one ``uuid_seed``.
#
# The corpus is only consistent with that, not evidence for it -- its single
# cross-file match lives in the synthetic parent/subagent fixture pair THIS
# repo authored, so it illustrates the link rather than confirming it in the
# wild. Do not read the rest as proof either: 2 distinct line-level values
# against 25 distinct ``toolUseResult`` ones with zero same-file overlap is the
# EXPECTED shape, since they live in different files, not a counterexample. An
# earlier version of this comment said "carries the same value as the
# line-level agentId (25 records)", which conflated an occurrence count with a
# match count and is not reproducible.
_UUID_PATHS: frozenset[JsonPath] = frozenset({
    ("uuid",),
    ("parentUuid",),
    ("sessionId",),
    ("agentId",),
    ("toolUseResult", "agentId"),
})

# thinking.signature. PRD section 2 earmarks it for a fixed placeholder;
# until that ships it passes through unchanged.
#
# Note what skipping it does and does not buy, because the causality is easy
# to state backwards: ``scan_residual`` is position-agnostic and re-scans the
# serialized output with no exemption for this field, so skipping does NOT
# protect a signature that trips a built-in secret pattern -- such a value
# would reach the output text and fail the run closed at exit 2, where
# visiting it would have redacted it cleanly. It is listed because the value
# is opaque and high-entropy, so scrubbing it would corrupt a field the format
# owns, not because the skip shields it from anything.
_PRESERVE_PATHS: frozenset[JsonPath] = frozenset({
    ("message", "content", "signature"),
})

# Tier B -- opaque format identifiers, preserved so the record graph stays
# linkable. Not enums, so visiting them is not automatically a no-op.
_IDENTIFIER_PATHS: frozenset[JsonPath] = frozenset({
    ("requestId",),
    ("message", "id"),
    ("message", "content", "id"),          # tool_use.id
    ("message", "content", "tool_use_id"), # tool_result -> its tool_use
})

# Tier C -- format-owned leaves, most of them enum discriminators. A
# configured path/identifier rule does not match "assistant" or "standard", so
# visiting these is a NO-OP TODAY. They are listed to pin intent, not because
# they are load-bearing: a rule that did collide would otherwise rewrite a
# format marker. Listed EXACTLY, never as a subtree, for the reason in the
# header comment.
#
# THE TEST FOR THIS TIER IS OWNERSHIP, NOT CARDINALITY -- who writes the
# value, the format or a tool. "Enum" describes most members, not the rule,
# and two members disprove the cardinality reading outright: ``version``
# (4 distinct values in the corpus, a new one every release) and
# ``message.model`` (4, a new one every model) are wide open and still belong
# here, because the runtime writes them. Reaching for "is it a closed enum?"
# is the test the ``toolUseResult.type`` removal below explicitly discarded --
# it had FEWER distinct values (3) than either of those and still came off.
#
# Deliberately absent: ``message.content.content.type`` and
# ``toolUseResult.content.type``. Both are content-block ``type``
# discriminators (values like "text"/"tool_reference"), so scrubbing them is a
# no-op today -- but unlike the entries above they sit INSIDE a tool_result
# payload: ``message.content[i]`` is a ``tool_result`` block whose ``content``
# array even carries CC-injected wrappers. Exempting a ``type`` key inside a
# tool's own output buys nothing -- it is enum-shaped, so scrubbing it changes
# no bytes today -- while widening the exempt surface into tool-shaped data,
# which is #194 one level deeper.
#
# Also deliberately absent, and removed during review rather than never added:
# ``toolUseResult.type``. It reads like the line-level ``type`` but it is not
# one. THE REASON IS OWNERSHIP: the data dictionary calls it a "tool-specific
# subtype indicator" and documents the envelope's shape as tool-dependent, so
# the value is chosen by whichever tool produced the result. That puts it in
# the same unbounded space #194 is about, and exempting it is the #194 shape
# one level in. The corpus corroborates rather than decides -- three values
# varying by tool (``text`` 41, ``create`` 29, ``update`` 9) -- and note that
# the count alone would have argued the WRONG way against ``version`` and
# ``message.model`` above.
#
# Contrast ``message.content.caller.type``, which is listed, and NOT because
# it has one value. It is listed because of where it sits: ``caller`` is a
# sibling of ``input`` on the ``tool_use`` content block (342/342 occurrences
# in the corpus, key set ``{type,id,name,input,caller}``, every one on a
# ``tool_use`` block). A tool controls the CONTENTS OF ``input`` and nothing
# else on that envelope, so a tool cannot reach ``caller`` at all. That
# exemption would stand even if a second caller kind appeared tomorrow. The
# single observed value (``direct``, 342) is corroboration.
#
# Scrubbing ``toolUseResult.type`` is a no-op under every shipped config -- no
# rule matches those three values -- so the cost of removing it is a position
# that BECOMES scrubbable, which is the visible failure direction this whole
# design chose.
#
# ONE HONEST WEAKNESS in the ownership rule, stated rather than papered over:
# it is human judgment, and it is usually read off format docs that are
# themselves incomplete. When ownership is genuinely unclear the rule is to
# LEAVE THE POSITION UNLISTED and let it be scrubbed -- over-scrub is the
# cheap direction.
#
# ``caller`` is worth distinguishing carefully, because it looks like a
# counterexample to that default and is not. Its ownership is NOT unclear: the
# structural argument above settles it, since a tool cannot write a sibling of
# ``input``. What is missing is the REFERENCE, not the proof --
# ``reference/data-dictionary.md`` does not document ``caller`` at all, so the
# premise lives here rather than in the format doc where it belongs. That is a
# documentation gap to close, not grounds to unlist the position.
#
# NOTE what this does NOT say. It is not "nothing under ``toolUseResult`` is
# exempt": five entries above sit there (``agentId`` and the four ``usage``
# leaves), because that envelope is MIXED -- the data dictionary documents
# those as format metadata while ``stdout``/``content``/``task`` are tool
# output. The line is drawn per position, which is the whole point of a path
# allow-list; a blanket per-subtree rule in either direction is what this
# design rejects.
#
# The residual there is ACCEPTED, not overlooked, and it is worth naming since
# the opposite decision (``toolUseResult.type`` coming off) is documented at
# length above. A nonconforming tool that wrote user data into one of those
# five exact keys would carry it past the exemption. It stays exempt because
# scrubbing the runtime's billing rollup and its graph link corrupts
# format-owned fields -- the #199 failure mode -- and because the residual
# secret scan still sweeps those positions for literal secrets regardless of
# the skip. The reachable shape is narrow: a tool would have to name a field
# one of four exact enum names under a ``usage`` key.
#
# ``message.content.content.type`` is the closer call, and an earlier version
# of this comment got the reason wrong: it called the ``type`` KEY arbitrary
# tool output, which the data dictionary contradicts -- that array carries
# content blocks. The deciding line is the FORMAT BOUNDARY, not nesting depth.
# Its outer sibling ``message.content.type`` discriminates the rigid
# Anthropic-API content block and IS listed; this one exists only under a
# tool_result. The arbitrary payload at the sibling ``text`` key is scrubbed
# either way, so exclusion costs no coverage.
_ENUM_PATHS: frozenset[JsonPath] = frozenset({
    ("type",),                                              # line-level kind
    ("version",),                                           # line-level format marker
    ("message", "type"),                                    # always "message"
    ("message", "role"),                                    # known enum
    ("message", "model"),
    ("message", "content", "type"),                         # content-block discriminator
    ("message", "content", "caller", "type"),               # always "direct"
    ("message", "diagnostics", "cache_miss_reason", "type"),
    ("error", "type"),
    ("error", "error", "type"),
    ("error", "error", "error", "type"),
    # The two usage subtrees. Enumerated rather than prefixed: each holds
    # exactly four string leaves and every one is a closed enum (token counts
    # are ints and never reach the transform at all).
    ("message", "usage", "service_tier"),
    ("message", "usage", "speed"),
    ("message", "usage", "inference_geo"),
    ("message", "usage", "iterations", "type"),
    ("toolUseResult", "usage", "service_tier"),
    ("toolUseResult", "usage", "speed"),
    ("toolUseResult", "usage", "inference_geo"),
    ("toolUseResult", "usage", "iterations", "type"),
})

# Everything skipped regardless of ``remap_uuids``.
_FORMAT_PATHS: frozenset[JsonPath] = (
    _PRESERVE_PATHS | _IDENTIFIER_PATHS | _ENUM_PATHS
)


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

    The predicate matches the **whole rooted path**, never its tail. That is
    the #194 fix: a name-, suffix- or parent-keyed rule matches at any depth,
    and ``tool_use.input`` is arbitrary tool-defined JSON, so every such rule
    exempted user data sitting under a colliding key. An unlisted path is now
    visited and scrubbed.

    Two earlier mechanisms are gone, and both failed the same way:

    - ``"usage" in path`` (membership anywhere), already deleted before #194
      for over-skipping any descendant of any ``usage`` key;
    - ``(parent, last)`` "anchored" pairs, which matched the *immediate parent
      name at any depth* rather than a rooted path, so ``input.content.id``
      and ``input.message.model`` collided inside tool payloads. The comment
      on that set reasoned the bug through correctly -- "a bare-name skip
      would also exempt user content like ``tool_use.input.id`` from
      scrubbing, leaking PII" -- and then shipped a mechanism that did not
      achieve it.

    Args:
        remap_uuids: When True, the UUID-graph paths (``uuid``,
            ``parentUuid``, ``sessionId``, ``agentId``, and
            ``toolUseResult.agentId``) are NOT skipped — they're visited so
            the identifier rule layer can remap them consistently. PRD
            section 6b B: "UUID fields (unless ``remap_uuids`` is on)".

    Returns:
        A ``SkipPredicate`` callable that takes a JSON path and returns True
        when the leaf at that path should NOT be scrubbed.
    """
    allowed = _FORMAT_PATHS if remap_uuids else _FORMAT_PATHS | _UUID_PATHS

    def predicate(path: JsonPath) -> bool:
        return path in allowed

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
            # LIST INDICES ARE ELIDED, and the allow-list depends on it:
            # ``("message","content","id")`` is what a tool_use block's ``id``
            # looks like at any position in the content array, so eliding is
            # what lets one entry cover ``message.content[3].id``. Rule layers
            # must not rely on positional addressing of array elements either.
            #
            # This comment used to say "the skip-list is keyed on field names
            # only", which was true of the bare-name design #194 replaced. The
            # comment that DID explain elision lived on
            # ``_ANCHORED_PARENT_LAST_SKIPS`` and was deleted with it, leaving
            # the mechanism the whole allow-list rests on explained only by a
            # sentence describing the mechanism it replaced.
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
