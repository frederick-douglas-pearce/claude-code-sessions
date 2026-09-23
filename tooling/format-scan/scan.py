#!/usr/bin/env python3
"""Local observational scanner for Claude Code JSONL session-format drift.

Walks a Claude Code projects root (default ~/.claude/projects/) and reports the
*shape* of the session data on disk: which top-level `type` values appear, which
envelope keys appear (overall and per type), which content-block types appear,
which session subdirectories exist (e.g. subagents/, tool-results/), the file
shape inside tool-results/, the key set of the per-subagent `meta.json` manifest
sidecars, and which Claude Code `version` values produced the data. Manifest
shape is also bucketed *by* the Claude Code version that produced it, which is
what turns "this key exists somewhere" into "this key appeared at version X" —
the shape most format-drift questions actually need. With --baseline it diffs the
observed taxonomy against a checked-in list of what `reference/` already
documents, so the delta is "undocumented drift" — exactly the input the
jsonl-format-watch queue wants.

SECURITY CONTRACT (read before editing — see CLAUDE.md "Security posture"):

    This tool reads raw, unsanitized session transcripts. It MUST NOT emit their
    contents. Everything this script prints is one of:

      - a structural KEY NAME (a JSON object key, e.g. "toolUseResult", or a
        top-level key of a subagent `meta.json` manifest)
      - a TAXONOMY ENUM that reference/ already publishes as a public value
        (the `type` field, content-block `type`, and the `version` string)
      - a VALUE JSON-TYPE drawn from the fixed, content-free vocabulary
        {str, int, float, bool, list, dict, null} — the *type* of a value, never
        the value itself (mirrors how keys_by_type and meta_json_keys describe
        what a key holds without revealing what it holds)
      - a COUNT, a SIZE in bytes, a file EXTENSION, or a DIRECTORY name
      - a STRUCTURAL COUNTER value from a `meta.json` key on the
        EMITTABLE_META_VALUE_FIELDS whitelist below — a small integer describing
        the runtime's own nesting bookkeeping (`spawnDepth`), never user content
      - a FOLDED ENUM value: one drawn from a fixed set this file declares
        (STOP_REASON_VALUES, TOOL_NAME_ALLOWLIST, TOOL_RESULT_PREFIX_ALLOWLIST,
        SYSTEM_SUBTYPE_ALLOWLIST, TOOL_DENIAL_KIND_ALLOWLIST),
        with everything outside that set replaced by the literal OTHER_BUCKET —
        except that the MCP tool-results family folds to the fixed MCP_BUCKET
        label instead, so the family stays countable without naming a server.
        Folding is what lets an OPEN-ended field be counted without its bytes
        being emitted — see STOP_REASON_VALUES for why `stop_reason` needs it,
        TOOL_NAME_ALLOWLIST for why tool names do, and
        TOOL_RESULT_PREFIX_ALLOWLIST for why a tool-results FILENAME PREFIX does
        (that one was emitting corpus text until #237; the comment that said
        otherwise is the cautionary case for this whole docstring).
        SYSTEM_SUBTYPE_ALLOWLIST and TOOL_DENIAL_KIND_ALLOWLIST are folds of a
        third kind: they exist to TEST A CLAIM rather than to inventory a
        vocabulary, so their allowlists are sized by what a fixture attests, not
        by what the corpus happens to hold. A fold is NOT
        a drop: an unrecognized value still shows up as a count against
        OTHER_BUCKET, which is the drift signal.
      - a FIXED BUCKET LABEL produced by classifying a value the scanner reads
        but must never print (MODEL_BUCKETS, and the `stop_sequence` state
        labels). The classification reads the value; only the label is emitted.

    Note the "file EXTENSION" and "DIRECTORY name" entries above are NOT folded.
    They are emitted as read, on the same kind of assumption that the filename
    prefix turned out to violate. Nothing has shown them to leak, but treat them
    as unverified rather than as cleared — see the open issues on this tool.

    It MUST NEVER emit a message value: no prompt text, no file contents, no
    command output, no tool inputs/results, no paths from inside the data, no
    UUIDs, no filenames-with-arbitrary-content. This bites hardest for the
    `meta.json` probe: its `description` and `worktreePath` keys carry free-text
    and filesystem-path PII, so the probe emits only those keys' NAMES, counts,
    and value JSON-types — never their string values. The two whitelists of
    value-bearing fields are defined once in EMITTABLE_VALUE_FIELDS and
    EMITTABLE_META_VALUE_FIELDS below; if you find yourself wanting to print
    anything else, stop — that is a leak, and it defeats the reason this scanner
    exists instead of `cat`.

    The block_secret_reads.py hook deliberately does NOT block Bash from reading
    ~/.claude/projects/ (so this scanner and the sanitizer CLI work). That makes
    the no-values discipline this script's responsibility, not the hook's. The
    PostToolUse detect_secrets_in_output.py scanner is a backstop for credential
    patterns only — it will not catch arbitrary PII, so do not rely on it.

Cross-platform: stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Scanner build identity, stamped into --json output by build_report(). These are
# tool-STATIC strings — they describe the scanner, not the scanned data — so they
# are content-free and do NOT belong on EMITTABLE_VALUE_FIELDS (that whitelist
# governs values read *from* session data; these are never read from anything).
#
# CROSS-REPO CONTRACT: the Claude Code Data Collective (CCDC) keys each Tier 2
# "structural" contribution by version *attestation* — it does not re-derive the
# profile, it trusts (tool, scan_version) — so its locked SCHEMA.md reads these
# field names directly out of scan.json. Renaming either field, or changing the
# tool id, is a downstream-breaking change. See CCDC SCHEMA.md ("Upstream
# dependencies") and CHANGELOG.md in this directory for the bump policy.
#
# Bump __version__ (semver) on ANY change that alters --json output shape or
# semantics; CCDC gates on it, so it must move when the output does.
__version__ = "0.4.0"
TOOL_ID = "ccs-format-scan"

# The ONLY message fields whose *values* may be emitted. Each is a public
# taxonomy enum already documented in reference/ — not user content. Do not add
# a field here without confirming its value space is a closed, content-free
# vocabulary (and update the SECURITY CONTRACT above if you do). Note that the
# meta.json manifest keys (agentType, description, toolUseId, worktreePath) are
# deliberately ABSENT: the probe reports their key names + value JSON-types, not
# their values — description/worktreePath carry PII and must never be printed.
#
# The last three members are FOLDED rather than closed: `stop_reason` against
# STOP_REASON_VALUES, `subtype` against SYSTEM_SUBTYPE_ALLOWLIST, and
# `toolDenialKind` against TOOL_DENIAL_KIND_ALLOWLIST. A folded field belongs
# here because its VALUES do reach output when allowlisted, which is exactly
# what this whitelist is the single register of. Auditing "what can this tool
# print?" must be answerable by reading this frozenset and nothing else.
EMITTABLE_VALUE_FIELDS = frozenset(
    {"type", "version", "stop_reason", "subtype", "toolDenialKind"}
)

# `stop_reason` is on the whitelist above, but it is the one member whose value
# space is NOT closed, and that is why it gets a constant of its own.
# reference/data-dictionary.md:99 documents these seven values and then says, of
# this exact field: "Treat this as an open enum, not a closed switch: an
# unrecognized value is one you have not seen yet rather than malformed data."
# The whitelist's own bar (see the comment above it) is a CLOSED, content-free
# vocabulary, so emitting whatever string the corpus happens to hold would fail
# the bar the whitelist sets.
#
# The resolution is to FOLD, not to drop: a value in this set is emitted
# verbatim, and anything else is bucketed as OTHER_BUCKET. An unrecognized value
# therefore still surfaces as drift (OTHER_BUCKET > 0 is precisely the signal
# this scanner exists to raise) without its bytes ever reaching output. This is
# also what makes the field testable — a sentinel planted in `stop_reason` must
# come back as OTHER_BUCKET, which test_content_free_contract.py asserts.
STOP_REASON_VALUES = frozenset(
    {
        "end_turn",
        "max_tokens",
        "stop_sequence",
        "tool_use",
        "pause_turn",
        "refusal",
        "model_context_window_exceeded",
    }
)

# Tool names we will emit, for the tool_use -> tool_result join below. Same
# reasoning as EMITTABLE_META_VALUE_FIELDS' rejection of `agentType`: tool names
# are NOT a closed vocabulary. MCP tools carry server-derived names
# (`mcp__<server>__<tool>`) and plugin/user tools carry author-chosen ones, so a
# free histogram over observed names would leak exactly what `agentType` is
# excluded for. NEVER emit an observed tool name — fold to OTHER_BUCKET.
# Extending this set is an output-affecting change: bump __version__.
TOOL_NAME_ALLOWLIST = frozenset({"Edit", "Agent"})

# The ONLY tool-results FILENAME prefixes whose text may be emitted. Same fold
# rule, and it is here because the previous comment on that probe made a claim
# the corpus does not support: it called the prefix "a tool-kind label (toolu,
# mcp-github-list, ...), not content". Against a real corpus that holds for a
# handful of values and fails for hundreds — a run observed 466 distinct
# prefixes, of which only `toolu` and three `mcp-*` forms were tool-kind labels.
# The rest were per-invocation ids (one file each), `webfetch-<epoch_ms>-<token>`
# stems whose timestamps decode to precise wall-clock activity times, and at
# least one fetched document's own filename.
#
# The extraction takes everything before the first `_` or `.`, so it only yields
# a tool-kind label when the filename HAPPENS to be `<kind>_<id>.<ext>`. A
# filename with no underscore returns whole. That is why an allowlist is the
# only safe treatment, and why `mcp-github-list` cannot simply be added to it:
# the server name is inside the string, which is the same author-controlled
# vocabulary TOOL_NAME_ALLOWLIST exists to keep out.
TOOL_RESULT_PREFIX_ALLOWLIST = frozenset({"toolu"})

# An MCP tool-results file is `mcp-<server>-<tool>_...`. That it came from MCP
# at all is structural and worth counting; which server it came from is not, so
# the whole family folds to this one fixed label rather than to OTHER_BUCKET —
# keeping the signal without the vocabulary.
MCP_PREFIX = "mcp-"
MCP_BUCKET = "mcp"

# The ONLY `system`-line subtypes whose text may be emitted, and the ONLY
# `toolDenialKind` values. Both exist to answer a specific question rather than
# to inventory a vocabulary, which is why each is deliberately tiny.
#
# The question for subtypes: Part 6 reads the hook-execution family as
# a general record of hook activity. Three purpose-built sessions
# (fixtures/sanitized/hook-trace-*.jsonl) say otherwise — every line carrying
# that family was `stop_hook_summary`, while a PreToolUse denial and four
# confirmed PostToolUse firings produced no `system` line at all. Three scratch
# sessions cannot settle what 10,864 lines can, and a CROSS-TAB settles it
# without a vocabulary: fold every subtype to this allowlist or to OTHER_BUCKET,
# then count hook records against the fold.
#
# The allowlist holds every subtype a committed fixture attests, not only the
# three the hook question needs. Leaving `api_error`, `away_summary` and
# `local_command` off it would fold thousands of ordinary lines into
# OTHER_BUCKET, and OTHER_BUCKET's entire job is to be a drift signal: a bucket
# that already holds attested traffic cannot raise one, because a genuinely new
# subtype arriving would move it by a few counts and look like noise.
#
# The question for `toolDenialKind`: its name promises a discriminator between a
# hook block, a user rejection, and a classifier denial. The one value a fixture
# attests is `permission-rule`, on a denial that came from a PreToolUse HOOK.
# Folding against that single value asks whether the corpus holds anything else,
# and the 2026-09-23 scan answers yes. So the field DOES discriminate something.
# What it discriminates is not yet known, which is why this allowlist stays at
# one member: a value no fixture attests has not met the bar to be emitted.
#
# Each member is a harness-supplied label, not user content, and each is
# attested by a committed fixture. That is the bar EMITTABLE_VALUE_FIELDS sets.
# Adding a member is an output-affecting change: bump __version__.
SYSTEM_SUBTYPE_ALLOWLIST = frozenset(
    {
        "stop_hook_summary",
        "turn_duration",
        "informational",
        "api_error",
        "away_summary",
        "local_command",
    }
)
TOOL_DENIAL_KIND_ALLOWLIST = frozenset({"permission-rule"})

# The top-level key whose presence defines "this `system` line carries the
# hook-execution family". SIX keys co-occur on exactly the same 4,159 lines in
# the 2026-09-23 scan — `hookCount`, `hookInfos`, `hookErrors`, `hasOutput`,
# `stopReason`, `preventedContinuation` — so any of those six would serve as the
# anchor; this one is named in reference/data-dictionary.md and reads as it.
#
# The family is NOT seven keys, which an earlier version of this comment
# asserted and the shape probe below disproved on its first run.
# `hookAdditionalContext` is present on 3,176 of those lines and absent from the
# other 983, so it is an OPTIONAL member. `toolUseID` is on 6,906 lines, more
# than the family has, so it is a general key that merely co-occurs. Anchoring
# on either would have counted a different population than the one intended,
# which is the argument for naming the anchor rather than inferring it.
HOOK_FAMILY_KEY = "hookCount"

# Every top-level key that marks a `system` line as a record of hook activity.
# HOOK_FAMILY_KEY alone is too narrow to answer the question it was added for:
# fixtures/sanitized/hook-trace-prompt-hook-refusal.jsonl carries three
# `informational` lines with `preventContinuation` and no `hookCount`, so a
# probe anchored on the family is blind to them BY CONSTRUCTION. It would report
# "the family only ever lands on stop_hook_summary" whatever the corpus held,
# which is not a finding. Anchoring on the union is what makes it falsifiable.
#
# Membership is deliberately conservative. Every key here is `hook`-prefixed or
# a `prevent*Continuation`, both of which reference/ documents as hook-specific.
# The generic co-travellers on those same lines (`hasOutput`, `level`,
# `stopReason`, `toolUseID`) are NOT members: they occur on non-hook lines too,
# so including them would pad the denominator with lines recording no hook.
HOOK_RECORD_KEYS = frozenset(
    {
        "hookCount",
        "hookInfos",
        "hookErrors",
        "hookAdditionalContext",
        "preventContinuation",
        "preventedContinuation",
    }
)

# The fold target for any value outside a whitelist above. A string WE supply,
# so it is content-free by construction.
OTHER_BUCKET = "<other>"

# Distinguishes "key missing" from "key present with a JSON null". Every field
# below needs that distinction and `.get()` alone cannot make it:
# reference/data-dictionary.md:99 treats a null `stop_reason` as a real
# observation ("lines recording an incomplete turn... not safe to discard"),
# not as an absence, and :100 says the same of `stop_sequence`. Collapsing the
# two would merge counts reference/ is going to cite separately.
_MISSING = object()

# Fixed hypothesis marker for the synthetic-vs-real split. As with
# PERSISTED_MARKERS and SUBAGENT_TOKENS_MARKER, this is a string WE supply, so
# testing for it leaks nothing — the report carries only the fixed bucket label,
# never the observed `message.model` string. scan.py's EMITTABLE_META_VALUE_FIELDS
# comment already names `model` as non-qualifying, and that stands: this reads
# the field to CLASSIFY it and never to emit it.
SYNTHETIC_MODEL_MARKER = "<synthetic>"

# The three fixed labels the model field is classified into. `absent` is
# explicit rather than folded into "real": a missing or null model is an
# ambiguous case, and defaulting an ambiguous case to "real" would overstate the
# real-traffic denominator.
MODEL_BUCKETS = ("real", "synthetic", "absent")

# The ONLY `meta.json` manifest keys whose *values* may be emitted, as a value
# histogram in the per-version buckets. The bar for adding one is higher than for
# EMITTABLE_VALUE_FIELDS above, because manifest values are where the PII lives:
# a key qualifies only if its value space is a small, closed set the *runtime*
# writes about its own bookkeeping, with no path through it for user content.
#
# `spawnDepth` qualifies: it is the subagent's nesting level, a small
# non-negative integer capped by the runtime's own depth limit. Knowing it is 2
# reveals nothing about what the agent was doing. `agentType` does NOT qualify
# despite looking enum-ish — user-defined agents put arbitrary author-chosen names
# in it. `description`, `worktreePath`, `toolUseId`, `name`, `model` do not
# qualify. If you add a key here, bump __version__ and say so in CHANGELOG.md.
EMITTABLE_META_VALUE_FIELDS = frozenset({"spawnDepth"})

# Fixed hypothesis marker for the --probe-nesting rollup check: the inline
# per-subagent token trailer that the Agent tool_result carries in place of a
# `toolUseResult` rollup sibling in some runtimes (see F-017). As with
# PERSISTED_MARKERS, this is a string WE supply, so testing for it leaks nothing —
# the probe reports only whether it was present, never the text around it.
SUBAGENT_TOKENS_MARKER = "subagent_tokens"


def json_type(value) -> str:
    """Name the JSON type of a value, drawn from a fixed content-free vocabulary.

    Returns one of: null, bool, int, float, str, list, dict (or "<unknown>" for
    anything else). This is the ONLY thing the meta.json probe records about a
    value — never the value itself. bool is checked before int because Python's
    bool is an int subclass.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "<unknown>"


def version_sort_key(version: str) -> tuple:
    """Order a Claude Code `version` string numerically, not lexically.

    "2.1.99" must sort before "2.1.150"; plain string sort gets that backwards,
    which would silently scramble every per-version table. Non-numeric segments
    sort after numeric ones at the same position, and an unparseable version
    still gets a total order (it lands at the end) rather than raising.
    """
    parts = []
    for seg in str(version).split("."):
        if seg.isdigit():
            parts.append((0, int(seg), ""))
        else:
            parts.append((1, 0, seg))
    return tuple(parts)

# --probe-tool-results hypothesis markers. The probe reports only how many
# tool_result contents CONTAIN each of these fixed strings (presence + count) —
# it never emits the content around a match. This lets us confirm the shape of
# the tool-results/ externalization wrapper (candidate F-001) without reading the
# spilled output (the wrapper carries a preview of real tool output, which IS
# content and must not be surfaced). Add hypotheses freely; they are strings WE
# supply, so testing for them leaks nothing.
PERSISTED_MARKERS = (
    "<persisted-output",
    "</persisted-output>",
    "persisted-output",
    "persisted_output",
    "Preview (first",
    "Preview of",
    "tool-results/",
    "characters truncated",
    "truncated",
    "saved to",
    "output exceeds",
    "[Tool",
)


def default_root() -> Path:
    """Claude Code projects root, honoring CLAUDE_CONFIG_DIR like Claude Code."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(cfg) if cfg else Path.home() / ".claude"
    return base / "projects"


# Bucket labels occupy a `<...>` namespace no allowlist member may enter. If a
# real field ever held the string `<other>`, an emitted-verbatim allowlist
# member would be indistinguishable from a fold result, and every count derived
# from the fold would be ambiguous. That is not hypothetical shape-wise:
# fixtures/synthetic/anatomy-hook-trace.jsonl carries `"subtype": "<unread>"`,
# fabricated in exactly this namespace. Nothing observed collides today; this
# assertion is what keeps that true as the allowlists grow.
BUCKET_LABELS = frozenset({OTHER_BUCKET, MCP_BUCKET, "<absent>", "<null>"})
assert not (
    STOP_REASON_VALUES | SYSTEM_SUBTYPE_ALLOWLIST | TOOL_DENIAL_KIND_ALLOWLIST
) & BUCKET_LABELS, "an allowlist member collides with a bucket label"


def _fold(value, allowlist: frozenset) -> str:
    """Fold a value to `allowlist`, or to a bucket label.

    The one fold contract this file has: an allowlisted string verbatim,
    `<null>` for an explicit JSON null, `<absent>` for a missing key, and
    OTHER_BUCKET for everything else — including a non-string, which is
    malformed rather than a new enum member but is not worth a bucket of its
    own. `<null>` and `<absent>` stay apart because "key present, value null"
    and "key not there" are different observations.

    A fold is NOT a drop: an unrecognized value still lands in OTHER_BUCKET,
    which is the drift signal. Every fold in this file delegates here so a
    change to the contract cannot reach some folds and miss others.
    """
    if value is _MISSING:
        return "<absent>"
    if value is None:
        return "<null>"
    if isinstance(value, str) and value in allowlist:
        return value
    return OTHER_BUCKET


def stop_reason_label(value) -> str:
    """Fold a `stop_reason` to STOP_REASON_VALUES.

    See STOP_REASON_VALUES for why a field reference/ documents as an OPEN enum
    needs a fold rather than a plain whitelist entry.
    """
    return _fold(value, STOP_REASON_VALUES)


def system_subtype_label(value) -> str:
    """Fold a `system` line's `subtype` to SYSTEM_SUBTYPE_ALLOWLIST.

    `<absent>` is a real observation here rather than a malformed one: a
    `system` line carrying no subtype at all is a distinct shape.
    """
    return _fold(value, SYSTEM_SUBTYPE_ALLOWLIST)


def tool_denial_kind_label(value) -> str:
    """Fold a `toolDenialKind` to TOOL_DENIAL_KIND_ALLOWLIST.

    Counted per LINE by the caller, never per `tool_result` block. See
    Observation.tool_denial_result_lines for why the two differ and what makes
    them comparable.
    """
    return _fold(value, TOOL_DENIAL_KIND_ALLOWLIST)


def folded_histogram(counter, *always: str) -> dict:
    """Emit a folded counter with its falsification buckets made explicit.

    `dict(counter.most_common())` omits a bucket that never fired, so a zero
    arrives as a MISSING KEY and "the fold found nothing outside the allowlist"
    is indistinguishable from "this build did not compute it". CCDC attests a
    contributed row by (tool, scan_version) without re-deriving it, so that
    distinction is the only handle a consumer has. Seed every bucket that
    carries a claim, and a negative result stays visible as `0`.
    """
    out = dict(counter.most_common())
    for label in always:
        out.setdefault(label, 0)
    return out


def has_tool_result_block(obj: dict) -> bool:
    """True if this line's message carries at least one `tool_result` block.

    Reads block TYPES only, never a block's content. Exists so the denial probe
    can say which of its lines are comparable with the block-weighted
    tool_result_line_keys counter, instead of assuming every one of them is.
    """
    message = obj.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def model_bucket(message: dict) -> str:
    """Classify `message.model` into one of MODEL_BUCKETS. Never emits it.

    `absent` covers both a missing key and an explicit null. Both are ambiguous
    about whether the line is real traffic, and folding an ambiguous case into
    `real` would overstate the real-traffic denominator — which is the number
    reference/ will end up citing.
    """
    model = message.get("model", _MISSING)
    if model is _MISSING or model is None:
        return "absent"
    if model == SYNTHETIC_MODEL_MARKER:
        return "synthetic"
    return "real"


def stop_sequence_state(message: dict) -> str:
    """Classify `message.stop_sequence` by SHAPE, never by value.

    Four fixed labels. This exists because reference/data-dictionary.md:100
    stakes a claim about the FIELD rather than about `stop_reason`: "the key is
    normally present with a literal `null`, and the only non-`null` instance in
    this repo's fixtures is an empty string on a `message.model == "<synthetic>"`
    line." A `stop_reason` histogram cannot check that claim; this can, and it
    does so without emitting the value — which is exactly why `stop_sequence`
    stays OFF EMITTABLE_VALUE_FIELDS. The value carries the caller-supplied
    matched sequence (data-dictionary.md:100) and must never be printed.
    """
    value = message.get("stop_sequence", _MISSING)
    if value is _MISSING:
        return "absent"
    if value is None:
        return "null"
    if not isinstance(value, str):
        # Malformed, or a future format change. It must NOT land in
        # `non_empty_string`: that is the one label whose presence contradicts
        # data-dictionary.md:100's claim about this field, so absorbing a
        # non-string there would read as a substantive format finding when it is
        # nothing of the kind. stop_reason_label folds non-strings for the same
        # reason.
        return "non_string"
    if value == "":
        return "empty_string"
    return "non_empty_string"


def tool_name_label(name) -> str:
    """Fold a tool name to the allowlist. See TOOL_NAME_ALLOWLIST."""
    if isinstance(name, str) and name in TOOL_NAME_ALLOWLIST:
        return name
    return OTHER_BUCKET


def tool_result_prefix_label(stem: str) -> str:
    """Fold a tool-results filename prefix. See TOOL_RESULT_PREFIX_ALLOWLIST.

    The prefix is NOT reliably a tool-kind label — it is whatever precedes the
    first `_` or `.` in a filename the runtime chose, which for most real files
    is a per-invocation id or the document's own name. So only a declared prefix
    is emitted verbatim, the MCP family collapses to a single fixed label that
    carries no server name, and everything else folds.
    """
    if stem in TOOL_RESULT_PREFIX_ALLOWLIST:
        return stem
    if stem.startswith(MCP_PREFIX):
        return MCP_BUCKET
    return OTHER_BUCKET


class FileJoin:
    """Per-file buffer for the `tool_use` -> `tool_result` join.

    Deliberately NOT state on Observation, whose docstring is "across all
    scanned files": per-file mutable state hung off that object is a state-bleed
    bug between files that no assertion about totals would catch.

    Per-file is also the CORRECT scope, not merely the convenient one.
    reference/tool-invocation.md:83 documents that subagent traces carry their
    own `tool_use_id` space, so a cross-file join would resolve ids that a real
    parser — which only ever has one file open — cannot. That is why this is not
    built like probe_nesting, whose join is genuinely global (a manifest in one
    place, its spawn site in another) and therefore two-phase.

    Ids are used ONLY as join keys here and are never emitted, matching
    probe_nesting's discipline. Memory is bounded by one file's `tool_use` count.
    """

    def __init__(self) -> None:
        # tool_use id -> folded tool-name label. The label, not the raw name, so
        # an unallowlisted name is discarded at the point of capture rather than
        # carried around waiting to be leaked by a later edit.
        self.tool_use_labels: dict[str, str] = {}
        # One entry per tool_result block: (tool_use_id, is_sidechain,
        # toolUseResult shape, key-presence flags). Resolved at EOF, once every
        # tool_use in the file has been seen — a tool_result can only be judged
        # an orphan against the COMPLETE id set, never against a partial one.
        self.results: list[tuple] = []


class Observation:
    """Accumulates content-free structural facts across all scanned files."""

    def __init__(self) -> None:
        self.files_scanned = 0
        self.lines_scanned = 0
        self.parse_errors = 0
        self.top_level_types: Counter[str] = Counter()
        self.top_level_keys: Counter[str] = Counter()
        self.keys_by_type: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.content_block_types: Counter[str] = Counter()
        self.versions: Counter[str] = Counter()
        # Top-level keys seen on user lines that carry a tool_result block.
        # A new key here is the prime suspect for a tool-results/ sidecar pointer.
        self.tool_result_line_keys: Counter[str] = Counter()
        # Hook records, as a three-level cross-tab over `system` lines:
        #   system_subtypes       every `system` line, folded
        #   hook_record_subtypes  those carrying ANY HOOK_RECORD_KEYS member
        #   hook_family_subtypes  those carrying HOOK_FAMILY_KEY specifically
        # The middle level is the honest denominator for "which subtypes does
        # hook activity land on". The inner one answers the narrower question
        # about the hook-execution family. Reporting both stops the narrow
        # answer from being read as the broad one, which is the mistake the
        # family-only version of this probe invited.
        self.system_subtypes: Counter[str] = Counter()
        self.hook_record_subtypes: Counter[str] = Counter()
        self.hook_family_subtypes: Counter[str] = Counter()
        # Which HOOK_RECORD_KEYS co-occur on a line, as a joined sorted string
        # of key NAMES. Content-free by construction: every component is drawn
        # from an allowlist this file declares, so no corpus byte can reach it.
        # This is the probe that says how many SHAPES of hook record exist.
        self.hook_record_shapes: Counter[str] = Counter()
        # `toolDenialKind`, folded and counted per LINE; the line total is
        # derived from this counter rather than tracked alongside it, so the two
        # cannot drift apart. `tool_denial_result_lines` is the subset also
        # carrying a `tool_result` block, which is the only subset comparable
        # with the block-weighted tool_result_line_keys probe.
        self.tool_denial_kinds: Counter[str] = Counter()
        self.tool_denial_result_lines = 0
        # Directory shape.
        self.session_subdirs: Counter[str] = Counter()
        self.tool_results_extensions: Counter[str] = Counter()
        self.tool_results_sizes: list[int] = []
        self.tool_results_name_prefixes: Counter[str] = Counter()
        self.sessions_with_subdir_dir = 0
        # Per-subagent meta.json manifest sidecars (subagents/*.meta.json).
        # Key NAMES + counts, and value JSON-TYPES per key — never values.
        self.meta_json_files = 0
        self.meta_json_parse_errors = 0
        self.meta_json_keys: Counter[str] = Counter()
        self.meta_json_key_types: defaultdict[str, Counter[str]] = defaultdict(Counter)
        # Manifest shape bucketed by the CC version that produced it. Populated in
        # two passes: scan() records the versions seen on each subagent trace file
        # (keyed by that file's path), then _ingest_subagent_meta() attributes each
        # manifest to its own trace's version. See _attribute_version() for why the
        # *earliest* version on the trace is the right bucket.
        self.trace_versions: dict[str, set[str]] = {}
        self.meta_by_version: defaultdict[str, dict] = defaultdict(
            lambda: {"manifests": 0, "keys": Counter(), "values": defaultdict(Counter)}
        )
        self.meta_manifests_unattributed = 0
        self.traces_spanning_multiple_versions = 0
        # --- message_shape: families 1, 1b and 2 (issue #237) -----------------
        # Family 1's denominator is assistant lines with a dict `message`, NOT
        # "assistant lines" — and the presence split is three-way because a
        # 60-file sample of a real corpus found 27% of assistant lines carrying
        # no `stop_reason` at all, which would otherwise silently renormalize
        # the distribution reference/ cites.
        self.assistant_lines = 0
        self.assistant_api_error_lines = 0
        # scan() walks root.rglob("*.jsonl"), which includes
        # <session>/subagents/agent-*.jsonl, so every message_shape figure POOLS
        # subagent-trace lines with parent-transcript ones. That is stated in
        # the denominators and quantified by these two counts: without them a
        # reader of the artifact cannot tell how much of a figure is subagent
        # traffic, and tool-invocation.md:524 warns that mixing the two is what
        # puts "a subagent's parallelism into the parent's numbers".
        self.assistant_lines_sidechain = 0
        self.user_lines_sidechain = 0
        self.stop_reason_presence: Counter[str] = Counter()
        self.stop_reason_by_model: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.stop_sequence_by_model: defaultdict[str, Counter[str]] = defaultdict(Counter)
        # Family 2: `user` lines with a dict `message`, split by content shape.
        self.user_lines = 0
        self.user_content_shape: Counter[str] = Counter()
        # --- tool_cycle: families 3, 4 and 5, resolved per file --------------
        self.tool_result_blocks = 0
        self.files_dropped_mid_read = 0
        self.tool_results_resolved = 0
        self.tool_results_orphaned: Counter[str] = Counter()
        self.tool_cycle_by_tool: defaultdict[str, Counter[str]] = defaultdict(Counter)

    # --- line-level ingestion -------------------------------------------------

    def ingest_line(self, obj: dict, join: FileJoin | None = None) -> None:
        """Record one JSONL line.

        ``join`` is the caller's per-file buffer (see FileJoin). It is optional
        so that callers which only want line-shape facts — and the existing
        tests, which predate the join — keep working unchanged; when it is None
        the tool_cycle families simply do not accumulate.
        """
        if not isinstance(obj, dict):
            return
        self.lines_scanned += 1

        line_type = obj.get("type")
        type_label = line_type if isinstance(line_type, str) else "<no-type>"
        self.top_level_types[type_label] += 1

        for key in obj.keys():
            self.top_level_keys[key] += 1
            self.keys_by_type[type_label][key] += 1

        if type_label == "system":
            subtype_label = system_subtype_label(obj.get("subtype", _MISSING))
            self.system_subtypes[subtype_label] += 1
            # Sorted so the shape string is stable across lines that carry the
            # same keys in a different order.
            hook_keys = sorted(HOOK_RECORD_KEYS & obj.keys())
            if hook_keys:
                self.hook_record_subtypes[subtype_label] += 1
                self.hook_record_shapes["+".join(hook_keys)] += 1
                if HOOK_FAMILY_KEY in obj:
                    self.hook_family_subtypes[subtype_label] += 1

        # Line-weighted, so a line carrying two tool_result blocks counts once.
        if "toolDenialKind" in obj:
            self.tool_denial_kinds[
                tool_denial_kind_label(obj.get("toolDenialKind", _MISSING))
            ] += 1
            if has_tool_result_block(obj):
                self.tool_denial_result_lines += 1

        if isinstance(line_type, str) and "type" in EMITTABLE_VALUE_FIELDS:
            pass  # type already recorded as the label above

        version = obj.get("version")
        if isinstance(version, str):
            self.versions[version] += 1

        message = obj.get("message")
        if isinstance(message, dict):
            bucket = model_bucket(message)

            if type_label == "assistant":
                self.assistant_lines += 1
                if obj.get("isSidechain") is True:
                    self.assistant_lines_sidechain += 1
                # data-dictionary.md:108 — an API-error record is not a real
                # model turn and "should be excluded from token and turn
                # metrics". It is the leading hypothesis for a share of the
                # absent-stop_reason lines, so counting it is what turns "N
                # absent" into an explainable number rather than a puzzle.
                if obj.get("isApiErrorMessage") is True:
                    self.assistant_api_error_lines += 1
                raw_stop = message.get("stop_reason", _MISSING)
                if raw_stop is _MISSING:
                    self.stop_reason_presence["absent"] += 1
                elif raw_stop is None:
                    self.stop_reason_presence["present_null"] += 1
                else:
                    self.stop_reason_presence["present_non_null"] += 1
                self.stop_reason_by_model[bucket][stop_reason_label(raw_stop)] += 1
                self.stop_sequence_by_model[bucket][stop_sequence_state(message)] += 1

            elif type_label == "user":
                self.user_lines += 1
                if obj.get("isSidechain") is True:
                    self.user_lines_sidechain += 1
                raw_content = message.get("content", _MISSING)
                if raw_content is _MISSING:
                    self.user_content_shape["absent"] += 1
                elif raw_content is None:
                    # Explicit null kept distinct from both `absent` and the
                    # `other` catch-all, per _MISSING. Collapsing it would
                    # repeat, on this family, the exact mistake the three-way
                    # `stop_reason` split exists to avoid.
                    self.user_content_shape["null"] += 1
                elif isinstance(raw_content, list):
                    self.user_content_shape["list"] += 1
                elif isinstance(raw_content, str):
                    self.user_content_shape["str"] += 1
                else:
                    self.user_content_shape["other"] += 1

            content = message.get("content")
            if isinstance(content, list):
                # `toolUseResult` is ONE key on the line, but a line may carry
                # several `tool_result` blocks — tool-invocation.md:526 records
                # that the results of a parallel turn "may arrive in one `user`
                # line or across several". So the envelope is attributable to a
                # specific result only when there is exactly one block to
                # attribute it to; with more, crediting each block would both
                # inflate the count and hand one tool's keys to another.
                tool_result_blocks_on_line = (
                    sum(
                        1
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "tool_result"
                    )
                    if join is not None
                    else 0
                )
                for block in content:
                    if isinstance(block, dict):
                        bt = block.get("type")
                        if isinstance(bt, str):
                            self.content_block_types[bt] += 1
                        # Detect tool_result-bearing user lines for pointer hunt.
                        if bt == "tool_result":
                            for key in obj.keys():
                                self.tool_result_line_keys[key] += 1
                        if join is not None:
                            self._capture_join(
                                obj, block, bt, join, tool_result_blocks_on_line
                            )

    def _capture_join(
        self, obj: dict, block: dict, bt, join: FileJoin, blocks_on_line: int = 1
    ) -> None:
        """Buffer one content block for the per-file tool-cycle join.

        Nothing is decided here — a tool_result cannot be judged resolved or
        orphaned until every tool_use in the file has been seen. See
        resolve_file_join().
        """
        if bt == "tool_use":
            tuid = block.get("id")
            if isinstance(tuid, str):
                # Fold at the point of capture, so an unallowlisted name is
                # discarded here rather than carried around waiting for a later
                # edit to emit it.
                join.tool_use_labels[tuid] = tool_name_label(block.get("name"))
            return

        if bt != "tool_result":
            return

        # NOT counted here: the running total is taken off the buffer in
        # resolve_file_join(), so that `tool_result_blocks == resolved +
        # orphaned` holds by construction. Counting at capture time would break
        # that identity for any file that dies mid-read, whose buffer is dropped.
        #
        # `toolUseResult` is a TOP-LEVEL key on the line, sibling to `message`.
        # Its shape is three-way on purpose: tool-invocation.md:195 records it
        # as a bare string on a minority of results (240 on `Edit` alone), and a
        # dict-only denominator would silently drop every one of them.
        tur = obj.get("toolUseResult", _MISSING)
        # Ambiguity requires something to BE ambiguous about. A multi-block line
        # whose envelope is missing or null has nothing to misattribute — no
        # block carries a body — so those keep their own precise labels rather
        # than being absorbed here. Testing block-count first would label them
        # ambiguous, under-counting `absent`/`null` and over-counting a shape
        # that is supposed to mean "an envelope exists but belongs to no one
        # result".
        if blocks_on_line > 1 and tur is not _MISSING and tur is not None:
            shape = "ambiguous_multi_block"
        elif tur is _MISSING:
            shape = "absent"
        elif tur is None:
            # An explicit null is not the same fact as a missing key, and not
            # the same as a string body either — see _MISSING.
            shape = "null"
        elif isinstance(tur, dict):
            shape = "dict"
        else:
            shape = "non_dict"
        is_dict = shape == "dict"
        join.results.append(
            (
                block.get("tool_use_id"),
                obj.get("isSidechain") is True,
                shape,
                is_dict and "structuredPatch" in tur,
                is_dict and "prompt" in tur,
                # Presence only, never a key histogram. `toolStats` is keyed by
                # tool CATEGORY, not tool name — data-dictionary.md:224 records
                # exactly seven observed keys, and :243 records that the
                # tool-name form was "a documentation error rather than a
                # variant". So the reason for presence-only is not that its keys
                # are unbounded; it is that this scanner has no need to
                # enumerate the contents of a nested result object at all, and
                # the narrow rule is the one that survives a format change.
                is_dict and "toolStats" in tur,
            )
        )

    def resolve_file_join(self, join: FileJoin) -> None:
        """Fold one file's buffered tool-cycle facts into the running totals.

        Called at EOF, which is the earliest point an orphan can be judged: a
        `tool_result` is an orphan only against the COMPLETE set of `tool_use`
        ids in its own file, never against a partial one.
        """
        self.tool_result_blocks += len(join.results)
        for tuid, is_sidechain, shape, has_patch, has_prompt, has_stats in join.results:
            label = join.tool_use_labels.get(tuid) if isinstance(tuid, str) else None
            if label is None:
                # Family 4. Split on the LINE's isSidechain, which is what says
                # whether the unmatched half sits in a parent transcript or a
                # subagent trace.
                self.tool_results_orphaned["sidechain" if is_sidechain else "parent"] += 1
                continue
            self.tool_results_resolved += 1
            row = self.tool_cycle_by_tool[label]
            row["results"] += 1
            row["toolUseResult_" + shape] += 1
            if has_patch:
                row["structuredPatch"] += 1
            if has_prompt:
                row["prompt"] += 1
            if has_stats:
                row["toolStats"] += 1

    # --- directory-level ingestion -------------------------------------------

    def ingest_session_dir(self, session_dir: Path) -> None:
        """Record the child directories of a <session-uuid>/ directory."""
        self.sessions_with_subdir_dir += 1
        for child in session_dir.iterdir():
            if child.is_dir():
                self.session_subdirs[child.name] += 1
                if child.name == "tool-results":
                    self._ingest_tool_results(child)
                elif child.name == "subagents":
                    self._ingest_subagent_meta(child)

    def _ingest_tool_results(self, tr_dir: Path) -> None:
        for f in tr_dir.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lstrip(".") or "<none>"
            self.tool_results_extensions[ext] += 1
            try:
                self.tool_results_sizes.append(f.stat().st_size)
            except OSError:
                pass
            # Prefix = chars before the first underscore or dot, then FOLDED.
            # The extraction alone does not make this content-free: a filename
            # with no underscore comes back whole, which against a real corpus
            # means per-invocation ids, `webfetch-<epoch_ms>-<token>` stems with
            # decodable activity timestamps, and fetched documents' own names.
            # See TOOL_RESULT_PREFIX_ALLOWLIST.
            stem = f.name
            for sep in ("_", "."):
                idx = stem.find(sep)
                if idx != -1:
                    stem = stem[:idx]
            self.tool_results_name_prefixes[tool_result_prefix_label(stem)] += 1

    def _ingest_subagent_meta(self, subagents_dir: Path) -> None:
        """Probe each subagents/*.meta.json manifest for its top-level key shape.

        Records key NAMES + counts and value JSON-TYPES per key only. The values
        (notably `description` and `worktreePath`) are PII and are never read
        into anything that gets emitted — see the SECURITY CONTRACT.
        """
        for f in sorted(subagents_dir.glob("*.meta.json")):
            if not f.is_file():
                continue
            self.meta_json_files += 1
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    manifest = json.load(fh)
            except (OSError, json.JSONDecodeError):
                self.meta_json_parse_errors += 1
                continue
            if not isinstance(manifest, dict):
                continue
            for key, value in manifest.items():
                self.meta_json_keys[key] += 1
                self.meta_json_key_types[key][json_type(value)] += 1
            self._ingest_meta_by_version(f, manifest)

    def _attribute_version(self, meta_path: Path) -> str | None:
        """Which CC version produced this manifest, from its own trace file.

        A manifest has no `version` of its own, so it inherits the version from
        the sibling `<agent-id>.jsonl` trace it describes. When a trace spans a CC
        upgrade we take the EARLIEST version on it: the manifest is written when
        the subagent is spawned, so the spawn-time version is the one whose
        behavior the manifest's shape reflects. Multi-version traces are counted
        so the caveat stays visible in the report rather than being smoothed away.
        """
        trace = meta_path.with_name(meta_path.name[: -len(".meta.json")] + ".jsonl")
        versions = self.trace_versions.get(str(trace))
        if not versions:
            return None
        if len(versions) > 1:
            self.traces_spanning_multiple_versions += 1
        return min(versions, key=version_sort_key)

    def _ingest_meta_by_version(self, meta_path: Path, manifest: dict) -> None:
        version = self._attribute_version(meta_path)
        if version is None:
            self.meta_manifests_unattributed += 1
            return
        bucket = self.meta_by_version[version]
        bucket["manifests"] += 1
        for key, value in manifest.items():
            bucket["keys"][key] += 1
            # Values only for the tightly-scoped structural-counter whitelist —
            # everything else contributes its key name and nothing more.
            if key in EMITTABLE_META_VALUE_FIELDS:
                bucket["values"][key][str(value)] += 1


def scan(root: Path, obs: Observation, max_files: int | None = None) -> None:
    if not root.exists():
        print(f"error: projects root does not exist: {root}", file=sys.stderr)
        sys.exit(2)

    # 1) Parse every .jsonl (parent sessions + subagent traces) for line shape.
    for jsonl_path in sorted(root.rglob("*.jsonl")):
        if max_files is not None and obs.files_scanned >= max_files:
            break
        obs.files_scanned += 1
        # A subagent trace is the version anchor for its meta.json sidecar, which
        # carries no version of its own. Collect per-file so pass 2 can attribute.
        is_trace = jsonl_path.parent.name == "subagents"
        file_versions: set[str] = set()
        # Per-file join buffer, created and resolved inside this loop body for
        # the same reason file_versions is: both are facts ABOUT one file that
        # only become facts about the corpus once the file is fully read. See
        # FileJoin for why this is not state on Observation.
        join = FileJoin()
        try:
            with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        obs.parse_errors += 1
                        continue
                    obs.ingest_line(obj, join)
                    if is_trace and isinstance(obj, dict):
                        v = obj.get("version")
                        if isinstance(v, str):
                            file_versions.add(v)
        except OSError:
            # The file was opened but died mid-read, so the join buffer holds a
            # partial id set. Resolving it would manufacture orphans out of
            # tool_use lines that were simply never reached — drop it instead.
            #
            # Dropping keeps the tool_cycle identity true, but it does NOT undo
            # the lines already ingested: content_block_types["tool_result"] has
            # counted blocks that tool_cycle now never will. Counting the drop
            # is what lets a reader of the artifact explain that gap instead of
            # finding two figures that disagree for no stated reason.
            obs.files_dropped_mid_read += 1
            continue
        obs.resolve_file_join(join)
        if is_trace and file_versions:
            obs.trace_versions[str(jsonl_path)] = file_versions

    # 2) Inventory <session-uuid>/ directories for subdir shape. A session dir
    #    is a directory whose name matches a sibling "<name>.jsonl" parent file.
    for slug_dir in root.iterdir() if root.is_dir() else []:
        if not slug_dir.is_dir():
            continue
        for child in slug_dir.iterdir():
            if child.is_dir() and (slug_dir / f"{child.name}.jsonl").exists():
                obs.ingest_session_dir(child)


# --- baseline diff -----------------------------------------------------------


def load_baseline(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# (Observation attribute / baseline key, report_removals?). Each name is both
# the Observation attribute holding the observed set AND the baseline key holding
# the documented set. `report_removals` categories are closed vocabularies, so a
# documented item that goes unobserved is a candidate removal worth surfacing.
# `versions` is additive-only: an open, ever-growing set, so a documented version
# missing from a scan is not drift (you'd never expect a scan to contain every
# version reference/ has ever seen).
_DIFF_CATEGORIES = (
    ("top_level_types", True),
    ("top_level_keys", True),
    ("content_block_types", True),
    ("session_subdirs", True),
    ("meta_json_keys", True),
    ("versions", False),
)


def diff_against_baseline(obs: Observation, baseline: dict) -> dict:
    def new_items(observed, known):
        # Observed in the data but absent from the baseline — a hard signal: this
        # item exists in real sessions and reference/ hasn't documented it.
        known_set = set(known or [])
        return sorted(k for k in observed if k not in known_set)

    def removed_items(observed, known):
        # Documented in the baseline but absent from the data — a softer signal:
        # a candidate removal, or just absent from this corpus / --max-files sample.
        observed_set = set(observed)
        return sorted(k for k in (known or []) if k not in observed_set)

    # Per category: new_* then (where applicable) removed_*, so a diff reads as
    # additions then candidate removals.
    diff: dict = {}
    for name, report_removals in _DIFF_CATEGORIES:
        observed, known = getattr(obs, name), baseline.get(name)
        diff[f"new_{name}"] = new_items(observed, known)
        if report_removals:
            diff[f"removed_{name}"] = removed_items(observed, known)
    return diff


# --- tool-results pointer probe ----------------------------------------------

# A bounded, vocabulary-anchored tag matcher: an angle-bracket tag of <=40 chars
# that contains "persist" or "output". This only ever yields the wrapper tag
# itself (e.g. "<persisted-output>"), never the content inside it.
_TAG_RE = re.compile(r"<[^>\n]{1,40}>")


def _iter_tool_result_strings(root: Path, max_files: int | None):
    """Yield the string content of each tool_result block. Content is consumed
    only for fixed-marker membership tests in probe_tool_results — never emitted.
    """
    files = 0
    for jsonl_path in sorted(root.rglob("*.jsonl")):
        if max_files is not None and files >= max_files:
            break
        files += 1
        try:
            with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message") if isinstance(obj, dict) else None
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            c = block.get("content")
                            if isinstance(c, str):
                                yield c
                            elif isinstance(c, list):
                                for part in c:
                                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                                        yield part["text"]
        except OSError:
            continue


def probe_tool_results(root: Path, max_files: int | None = None) -> dict:
    marker_counts: Counter[str] = Counter()
    persist_tags: Counter[str] = Counter()
    total = 0
    for text in _iter_tool_result_strings(root, max_files):
        total += 1
        for marker in PERSISTED_MARKERS:
            if marker in text:
                marker_counts[marker] += 1
        if "persist" in text or "Preview (first" in text:
            for tag in _TAG_RE.findall(text):
                low = tag.lower()
                if "persist" in low or "output" in low:
                    persist_tags[tag] += 1
    return {
        "tool_result_string_contents": total,
        "marker_counts": dict(marker_counts.most_common()),
        "persist_anchored_tags": dict(persist_tags.most_common()),
    }


# --- nesting probe -----------------------------------------------------------


def _iter_session_dirs(root: Path):
    """Yield each `<slug>/<session-uuid>/` directory (one with a sibling .jsonl)."""
    if not root.is_dir():
        return
    for slug_dir in sorted(root.iterdir()):
        if not slug_dir.is_dir():
            continue
        for child in sorted(slug_dir.iterdir()):
            if child.is_dir() and (slug_dir / f"{child.name}.jsonl").exists():
                yield child


def probe_nesting(root: Path, max_files: int | None = None) -> dict:
    """Answer the multi-level-subagent layout questions from observation (#169).

    Three things the per-version manifest table can't tell you on its own:

      1. Is the `subagents/` layout still FLAT once subagents spawn subagents, or
         does a depth-2 trace land in `subagents/<parent>/subagents/`? Counted
         directly as nested `subagents/` directories.
      2. At depth >= 2, does the spawning `Agent` tool_result still carry a
         `toolUseResult` rollup sibling, or only an inline `subagent_tokens`
         trailer (the SDK behavior in F-017)? Cost attribution depends on this.
      3. Where does the spawning tool_result LIVE — in the parent session
         transcript, or inside the depth-1 subagent's own trace file? That is what
         a parser has to walk to rebuild the tree.

    Depth-1 manifests are probed the same way as a control, so "depth >= 2 behaves
    differently" is a measured contrast and not an assumption. Content-free: the
    probe emits counts, the fixed SUBAGENT_TOKENS_MARKER's presence, and the
    structural container label — never the tool_result text or any id.
    """
    nested_dirs = 0
    session_dirs = 0
    for session_dir in _iter_session_dirs(root):
        session_dirs += 1
        subagents = session_dir / "subagents"
        if subagents.is_dir():
            # Any `subagents/` dir below the session's own one means the layout
            # is not flat. rglob covers arbitrary nesting depth, not just one level.
            nested_dirs += sum(1 for d in subagents.rglob("subagents") if d.is_dir())

    # toolUseId -> spawnDepth, for every manifest that carries both. The id is used
    # ONLY as a join key here; it is never emitted.
    targets: dict[str, int] = {}
    depth_histogram: Counter[str] = Counter()
    manifests = 0
    for session_dir in _iter_session_dirs(root):
        for meta in sorted((session_dir / "subagents").glob("*.meta.json")):
            try:
                with meta.open("r", encoding="utf-8", errors="replace") as fh:
                    manifest = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            manifests += 1
            depth = manifest.get("spawnDepth")
            depth_histogram[str(depth) if isinstance(depth, int) else "<absent>"] += 1
            tuid = manifest.get("toolUseId")
            if isinstance(depth, int) and isinstance(tuid, str):
                targets[tuid] = depth

    # One pass over every transcript, joining tool_result blocks to the target ids.
    # Bucketed by the spawned agent's depth, so depth 1 reads as the control row.
    by_depth: defaultdict[str, Counter[str]] = defaultdict(Counter)
    matched: set[str] = set()
    files = 0
    for jsonl_path in sorted(root.rglob("*.jsonl")):
        if max_files is not None and files >= max_files:
            break
        files += 1
        container = "subagent-trace" if jsonl_path.parent.name == "subagents" else "parent-session"
        try:
            with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    msg = obj.get("message")
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        tuid = block.get("tool_use_id")
                        depth = targets.get(tuid) if isinstance(tuid, str) else None
                        if depth is None:
                            continue
                        matched.add(tuid)
                        row = by_depth[str(depth)]
                        row["spawn_sites"] += 1
                        row[f"container:{container}"] += 1
                        row[
                            "has_toolUseResult_sibling"
                            if "toolUseResult" in obj
                            else "no_toolUseResult_sibling"
                        ] += 1
                        text = block.get("content")
                        if isinstance(text, list):
                            text = " ".join(
                                p.get("text", "") for p in text if isinstance(p, dict)
                            )
                        if isinstance(text, str) and SUBAGENT_TOKENS_MARKER in text:
                            row["has_subagent_tokens_trailer"] += 1
        except OSError:
            continue

    return {
        "session_dirs": session_dirs,
        "nested_subagent_dirs": nested_dirs,
        "manifests": manifests,
        "spawn_depth_histogram": dict(
            sorted(depth_histogram.items(), key=lambda kv: version_sort_key(kv[0]))
        ),
        "joinable_manifests": len(targets),
        "spawn_sites_located": len(matched),
        "spawn_sites_not_located": len(targets) - len(matched),
        "by_spawn_depth": {
            d: dict(sorted(c.items())) for d, c in sorted(by_depth.items(), key=lambda kv: version_sort_key(kv[0]))
        },
    }


# --- reporting ---------------------------------------------------------------


def size_summary(sizes: list[int]) -> dict:
    if not sizes:
        return {}
    return {
        "count": len(sizes),
        "min": min(sizes),
        "median": int(statistics.median(sizes)),
        "max": max(sizes),
    }


def build_report(obs: Observation, diff: dict | None, max_files: int | None = None) -> dict:
    return {
        # Tool-static build identity (see __version__/TOOL_ID above). Output uses
        # sort_keys=True, so these sort alphabetically in the emitted JSON — CCDC
        # reads them by name, not position.
        "scan_version": __version__,
        "tool": TOOL_ID,
        "summary": {
            "files_scanned": obs.files_scanned,
            "lines_scanned": obs.lines_scanned,
            "parse_errors": obs.parse_errors,
            "session_dirs_with_subdirectories": obs.sessions_with_subdir_dir,
            # The --max-files cap in force for this run (null = uncapped). Part
            # of the corpus fingerprint: files_scanned alone cannot distinguish
            # a full scan of 60 files from a --max-files 60 sample of thousands,
            # and a retained artifact that cannot say which is not comparable
            # against a later re-run. A tool-invocation parameter, so it is
            # content-free, and deterministic for a given invocation — it does
            # not reintroduce the wall-clock non-determinism CCDC's
            # sha256(scan.json) addressing rules out.
            "max_files": max_files,
        },
        "top_level_types": dict(obs.top_level_types.most_common()),
        "top_level_keys": dict(obs.top_level_keys.most_common()),
        "keys_by_type": {t: dict(c.most_common()) for t, c in sorted(obs.keys_by_type.items())},
        "content_block_types": dict(obs.content_block_types.most_common()),
        "tool_result_line_keys": dict(obs.tool_result_line_keys.most_common()),
        "hook_records": {
            "system_lines": obs.top_level_types.get("system", 0),
            "by_subtype": folded_histogram(
                obs.system_subtypes, OTHER_BUCKET, "<absent>", "<null>"
            ),
            "hook_record_lines": sum(obs.hook_record_subtypes.values()),
            "hook_record_by_subtype": folded_histogram(
                obs.hook_record_subtypes, OTHER_BUCKET
            ),
            "hook_record_shapes": dict(obs.hook_record_shapes.most_common()),
            "hook_family_lines": sum(obs.hook_family_subtypes.values()),
            "hook_family_by_subtype": folded_histogram(
                obs.hook_family_subtypes, OTHER_BUCKET
            ),
            "tool_denial_lines": sum(obs.tool_denial_kinds.values()),
            "tool_denial_result_lines": obs.tool_denial_result_lines,
            "tool_denial_by_kind": folded_histogram(
                obs.tool_denial_kinds, OTHER_BUCKET
            ),
            "denominators": {
                "by_subtype": (
                    "every `system` line, folded to SYSTEM_SUBTYPE_ALLOWLIST or "
                    "OTHER_BUCKET. `<absent>` and `<null>` are kept apart: a "
                    "`system` line with no subtype is a real observation"
                ),
                "hook_record_by_subtype": (
                    "the subset of those lines carrying ANY HOOK_RECORD_KEYS "
                    "member, folded the same way. THIS is the denominator for "
                    "'which subtypes does hook activity land on'. A probe "
                    "anchored on the hook-execution family alone cannot "
                    "answer it: "
                    "a hook record using a different key set is excluded by "
                    "construction, so the family-only answer is guaranteed "
                    "regardless of what the corpus holds"
                ),
                "hook_record_shapes": (
                    "HOOK_RECORD_KEYS present on each hook record, sorted and "
                    "joined with `+`. Key NAMES only, every one drawn from an "
                    "allowlist this file declares, so the string is "
                    "content-free by construction. The number of entries is "
                    "the number of distinct hook-record shapes in the corpus"
                ),
                "hook_family_by_subtype": (
                    "the narrower subset carrying HOOK_FAMILY_KEY "
                    f"(`{HOOK_FAMILY_KEY}`). Read against "
                    "`hook_record_by_subtype`, NOT against `by_subtype`: the "
                    "claim it tests is about the family specifically, and it "
                    "says nothing about hook records that omit the family. "
                    "Any count under OTHER_BUCKET falsifies the narrow claim"
                ),
                "tool_denial_by_kind": (
                    "counted per LINE carrying `toolDenialKind`, NOT per "
                    "`tool_result` block. `tool_result_line_keys` counts the "
                    "same key block-weighted over a DIFFERENT population "
                    "(lines with at least one `tool_result` block), so the two "
                    "figures are not comparable on their own. "
                    "`tool_denial_result_lines` is the overlap, and only that "
                    "figure against the block-weighted one says whether any "
                    "denial line carried a second `tool_result`"
                ),
            },
        },
        "session_subdirs": dict(obs.session_subdirs.most_common()),
        "tool_results": {
            "extensions": dict(obs.tool_results_extensions.most_common()),
            "name_prefixes": dict(obs.tool_results_name_prefixes.most_common()),
            "size_bytes": size_summary(obs.tool_results_sizes),
        },
        "meta_json_keys": {
            "files": obs.meta_json_files,
            "parse_errors": obs.meta_json_parse_errors,
            "keys": dict(obs.meta_json_keys.most_common()),
            "key_types": {
                k: dict(c.most_common()) for k, c in sorted(obs.meta_json_key_types.items())
            },
        },
        "meta_json_by_version": {
            "attribution": (
                "earliest `version` observed on the subagent's own trace file "
                "(spawn time); manifests carry no version of their own"
            ),
            "manifests_attributed": sum(
                b["manifests"] for b in obs.meta_by_version.values()
            ),
            "manifests_unattributed": obs.meta_manifests_unattributed,
            "traces_spanning_multiple_versions": obs.traces_spanning_multiple_versions,
            "versions": {
                v: {
                    "manifests": b["manifests"],
                    "keys": dict(b["keys"].most_common()),
                    "values": {
                        k: dict(sorted(c.items(), key=lambda kv: version_sort_key(kv[0])))
                        for k, c in sorted(b["values"].items())
                    },
                }
                for v, b in sorted(obs.meta_by_version.items(), key=lambda kv: version_sort_key(kv[0]))
            },
        },
        "message_shape": {
            # Denominators are carried IN the report, not just in the code, so
            # that a reader of the retained artifact can check a figure without
            # reading scan.py. The 2026-08-25 pass stated none of these, which
            # is why its numbers could not be re-derived (issue #237).
            "denominators": {
                "scope": (
                    "every figure in this section POOLS subagent-trace lines "
                    "with parent-transcript ones — the scan walks both. "
                    "`assistant_lines_sidechain` / `user_lines_sidechain` "
                    "quantify how much is subagent traffic; there is no "
                    "per-bucket split"
                ),
                "stop_reason": (
                    "assistant lines carrying a dict `message`; the three-way "
                    "presence split below is over that same denominator, and a "
                    "null `stop_reason` is a real observation (an incomplete "
                    "turn), not an absence"
                ),
                "user_content_shape": (
                    "user lines carrying a dict `message`, by the shape of "
                    "`message.content`: `list` / `str` / `null` (key present, "
                    "explicitly null) / `absent` (key missing) / `other` (any "
                    "other JSON type). `null` and `absent` are separate facts "
                    "and are never merged"
                ),
                "stop_sequence_state": (
                    "the SHAPE of `message.stop_sequence`, never its value, "
                    "over the same assistant-line denominator: `absent` (key "
                    "missing) / `null` / `empty_string` / `non_empty_string` / "
                    "`non_string` (malformed or a format change). The value is "
                    "the caller-supplied matched sequence and is never emitted, "
                    "which is why only the shape is reported"
                ),
                "model_bucket": (
                    "`synthetic` = message.model is the fixed marker; `absent` "
                    "= key missing or null; `real` = anything else. The "
                    "observed model string is never emitted"
                ),
                "stop_reason_values": (
                    "documented values emitted verbatim; any other value folds "
                    "to the fixed `<other>` bucket, which is a drift signal "
                    "rather than a discard"
                ),
            },
            "assistant_lines": obs.assistant_lines,
            "assistant_lines_sidechain": obs.assistant_lines_sidechain,
            "assistant_api_error_lines": obs.assistant_api_error_lines,
            "stop_reason_presence": dict(sorted(obs.stop_reason_presence.items())),
            "stop_reason_by_model_bucket": {
                b: dict(sorted(obs.stop_reason_by_model[b].items()))
                for b in MODEL_BUCKETS
                if obs.stop_reason_by_model.get(b)
            },
            # Family 1b: the shape of the `stop_sequence` FIELD, which is a
            # different question from the `stop_sequence` stop_reason VALUE.
            # data-dictionary.md:100 stakes its claim on the field.
            "stop_sequence_state_by_model_bucket": {
                b: dict(sorted(obs.stop_sequence_by_model[b].items()))
                for b in MODEL_BUCKETS
                if obs.stop_sequence_by_model.get(b)
            },
            "user_lines": obs.user_lines,
            "user_lines_sidechain": obs.user_lines_sidechain,
            "user_content_shape": dict(sorted(obs.user_content_shape.items())),
        },
        "tool_cycle": {
            "denominators": {
                "tool_result_blocks": (
                    "every `tool_result` content block observed IN A FILE READ "
                    "TO COMPLETION; equals `resolved` + the `orphaned` totals "
                    "by construction. A file this scan could not open, or that "
                    "failed partway through, has its whole join buffer dropped "
                    "and is counted in `files_dropped_mid_read`. When that is "
                    "non-zero this figure MAY be lower than "
                    "`content_block_types.tool_result` — by however many blocks "
                    "those files had already contributed before failing, which "
                    "is zero for a file that never opened"
                ),
                "by_tool_envelope": (
                    "`toolUseResult` shape per resolved result: `dict` / "
                    "`non_dict` (a bare string body) / `null` (key present, "
                    "explicitly null) / `absent` (key missing) / "
                    "`ambiguous_multi_block`. The last one exists because "
                    "`toolUseResult` is one key on the LINE: when a line "
                    "carries several `tool_result` blocks the envelope belongs "
                    "to no single result, so those contribute NO "
                    "conditional-key counts rather than crediting the same "
                    "envelope to each block. A multi-block line whose envelope "
                    "is missing or null is recorded as `absent`/`null` instead "
                    "— there is nothing to misattribute"
                ),
                "resolution": (
                    "a `tool_result` resolves when its `tool_use_id` matches a "
                    "`tool_use` id IN THE SAME FILE. Per-file is the correct "
                    "scope: subagent traces carry their own tool_use_id space"
                ),
                "orphaned": (
                    "a `tool_result` whose `tool_use_id` matches no `tool_use` "
                    "in its own file, split on the line's `isSidechain`"
                ),
                "by_tool": (
                    "keyed by the resolved tool name, folded to the fixed "
                    "allowlist; `<other>` covers every unallowlisted name. "
                    "`structuredPatch`/`prompt`/`toolStats` are presence counts "
                    "within `toolUseResult_dict`, NOT within `results` — "
                    "`toolUseResult` is a bare string on a minority of results "
                    "and those carry no keys to test"
                ),
            },
            "tool_result_blocks": obs.tool_result_blocks,
            "files_dropped_mid_read": obs.files_dropped_mid_read,
            "resolved": obs.tool_results_resolved,
            "orphaned": dict(sorted(obs.tool_results_orphaned.items())),
            "by_tool": {
                t: dict(sorted(c.items()))
                for t, c in sorted(obs.tool_cycle_by_tool.items())
            },
        },
        "versions": dict(obs.versions.most_common()),
        "baseline_diff": diff,
    }


def print_human(report: dict) -> None:
    s = report["summary"]
    print("# JSONL format scan\n")
    print(f"_{report['tool']} v{report['scan_version']}_\n")
    print(
        f"Scanned {s['files_scanned']} files / {s['lines_scanned']} lines "
        f"({s['parse_errors']} parse errors). "
        f"{s['session_dirs_with_subdirectories']} session dirs have subdirectories.\n"
    )

    def table(title: str, mapping: dict, value_label: str = "count") -> None:
        print(f"## {title}\n")
        if not mapping:
            print("_none observed_\n")
            return
        for k, v in mapping.items():
            print(f"- `{k}` — {v} {value_label}")
        print()

    table("Top-level `type` values", report["top_level_types"], "lines")
    table("Top-level envelope keys", report["top_level_keys"], "lines")
    table("Content-block `type` values", report["content_block_types"], "blocks")
    # BLOCK-weighted, despite the section title: a line carrying two
    # tool_result blocks contributes its top-level keys twice. Left that way on
    # purpose. Re-weighting it per line would silently break comparison with
    # every retained scan, which is the one job this tool has. The unit label
    # says blocks so the figure is not read as a line count, and hook_records
    # carries the line-weighted figure for `toolDenialKind` alongside it.
    table(
        "Top-level keys on tool_result-bearing user lines",
        report["tool_result_line_keys"],
        "tool_result blocks",
    )
    table("Session subdirectories", report["session_subdirs"], "sessions")

    # Every histogram below goes through table(), which backticks its keys.
    # That is load-bearing, not cosmetic: this report is Markdown, so a raw
    # `<other>` would be parsed as an HTML tag and render as nothing at all —
    # and OTHER_BUCKET is the drift bucket a reader most needs to find.
    hr = report["hook_records"]
    print("## Hook records\n")
    print(
        f"{hr['system_lines']} `system` lines. {hr['hook_record_lines']} record "
        f"hook activity, of which {hr['hook_family_lines']} carry the "
        f"hook-execution family.\n"
    )
    table("`system` subtypes, all lines", hr["by_subtype"], "lines")
    table("`system` subtypes, hook records only", hr["hook_record_by_subtype"], "lines")
    table(
        "`system` subtypes, hook-execution family only",
        hr["hook_family_by_subtype"],
        "lines",
    )
    table("Hook-record key shapes", hr["hook_record_shapes"], "lines")
    print(
        f"{hr['tool_denial_lines']} lines carry `toolDenialKind`; "
        f"{hr['tool_denial_result_lines']} of those also carry a `tool_result` "
        f"block.\n"
    )
    table("`toolDenialKind` values", hr["tool_denial_by_kind"], "lines")

    tr = report["tool_results"]
    print("## tool-results/ file shape\n")
    if tr["size_bytes"]:
        sz = tr["size_bytes"]
        print(f"- files: {sz['count']}  |  size bytes: min={sz['min']} median={sz['median']} max={sz['max']}")
        print(f"- extensions: {tr['extensions']}")
        print(f"- name prefixes: {tr['name_prefixes']}\n")
    else:
        print("_no tool-results/ files observed_\n")

    mj = report["meta_json_keys"]
    print("## subagents/ meta.json manifest keys\n")
    if mj["files"]:
        print(f"_{mj['files']} manifest(s) scanned, {mj['parse_errors']} parse error(s)._\n")
        for k, v in mj["keys"].items():
            types = mj["key_types"].get(k, {})
            type_str = ", ".join(f"{t}×{n}" for t, n in types.items())
            print(f"- `{k}` — {v} manifests ({type_str})")
        print()
    else:
        print("_no subagents/*.meta.json manifests observed_\n")

    mv = report["meta_json_by_version"]
    print("## subagents/ meta.json manifest shape by Claude Code version\n")
    if mv["versions"]:
        print(
            f"_{mv['manifests_attributed']} manifest(s) attributed, "
            f"{mv['manifests_unattributed']} unattributed (no version on the trace); "
            f"{mv['traces_spanning_multiple_versions']} trace(s) span more than one "
            f"version. Attribution: {mv['attribution']}._\n"
        )
        print("| version | manifests | keys present | whitelisted values |")
        print("| --- | --- | --- | --- |")
        for v, b in mv["versions"].items():
            keys = ", ".join(f"{k}×{n}" for k, n in b["keys"].items()) or "—"
            vals = (
                "; ".join(
                    f"{k}=" + ",".join(f"{val}×{n}" for val, n in counts.items())
                    for k, counts in b["values"].items()
                )
                or "—"
            )
            print(f"| `{v}` | {b['manifests']} | {keys} | {vals} |")
        print()
    else:
        print("_no manifests could be attributed to a version_\n")

    ms = report["message_shape"]
    print("## Message shape: `stop_reason` and `user` content\n")
    print(
        f"_{ms['assistant_lines']} assistant line(s) with a dict `message`, of which "
        f"{ms['assistant_api_error_lines']} are API-error records (not real turns) and "
        f"{ms['assistant_lines_sidechain']} are sidechain. "
        f"{ms['user_lines']} user line(s), {ms['user_lines_sidechain']} sidechain. "
        f"**Subagent and parent traffic are POOLED in every figure below.**_\n"
    )
    # Derive the header, the separator and every row from ONE column list.
    # Hand-deriving the separator width kept them in step only by coincidence,
    # so adding a label to the fold (or a bucket to stop_reason_label) would
    # have silently produced a malformed table. Labels are backticked because
    # `<other>`, `<null>` and `<absent>` are otherwise parsed as HTML tags and
    # render as blank headers — `<other>` being the drift column a reader most
    # needs to find.
    columns = sorted(
        set(STOP_REASON_VALUES) | {OTHER_BUCKET, "<null>", "<absent>"}
    )
    print("| model bucket | " + " | ".join(f"`{c}`" for c in columns) + " |")
    print("| --- " * (len(columns) + 1) + "|")
    for b, row in ms["stop_reason_by_model_bucket"].items():
        cells = " | ".join(str(row.get(v, 0)) for v in columns)
        print(f"| `{b}` | {cells} |")
    print()
    table("`stop_reason` presence", ms["stop_reason_presence"], "assistant lines")
    print("## `stop_sequence` field state by model bucket\n")
    for b, row in ms["stop_sequence_state_by_model_bucket"].items():
        print(f"- `{b}`: " + ", ".join(f"{k}={v}" for k, v in row.items()))
    print()
    table("`user` `message.content` shape", ms["user_content_shape"], "user lines")

    tc = report["tool_cycle"]
    print("## Tool cycle: `tool_use` -> `tool_result` join (per file)\n")
    orphan_total = sum(tc["orphaned"].values())
    print(
        f"_{tc['tool_result_blocks']} `tool_result` block(s): {tc['resolved']} resolved, "
        f"{orphan_total} orphaned ("
        + (", ".join(f"{k}={v}" for k, v in tc["orphaned"].items()) or "none")
        + f"). {tc['files_dropped_mid_read']} file(s) dropped mid-read._\n"
    )
    if tc["by_tool"]:
        for t, row in tc["by_tool"].items():
            print(f"- `{t}`: " + ", ".join(f"{k}={v}" for k, v in row.items()))
    else:
        print("_no tool_result resolved to a tool_use_")
    print()

    table("Claude Code `version` values", report["versions"], "lines")

    if report["baseline_diff"] is not None:
        print("## Drift vs. baseline\n")
        diff = report["baseline_diff"]
        any_drift = any(diff.values())
        if not any_drift:
            print("_no drift — observed taxonomy matches the baseline (both directions)_\n")
        else:
            for label, items in diff.items():
                if items:
                    pretty = label.replace("_", " ")
                    print(f"- **{pretty}:** {', '.join('`' + i + '`' for i in items)}")
            if any(items for label, items in diff.items() if label.startswith("removed_")):
                print(
                    "\n_`removed` = documented in the baseline but not seen in this scan; "
                    "could be a real removal/deprecation, or just absent from this "
                    "corpus or --max-files sample._"
                )
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=default_root(),
        help="Claude Code projects root (default: ~/.claude/projects or $CLAUDE_CONFIG_DIR/projects)",
    )
    parser.add_argument("--baseline", type=Path, help="JSON baseline to diff observed taxonomy against")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a human report")
    parser.add_argument("--max-files", type=int, help="stop after N jsonl files (sampling)")
    parser.add_argument(
        "--probe-tool-results",
        action="store_true",
        help="probe tool_result contents for the tool-results/ externalization wrapper "
        "(fixed-marker presence + counts only — no content emitted)",
    )
    parser.add_argument(
        "--probe-nesting",
        action="store_true",
        help="probe multi-level subagent layout: nested subagents/ dirs, spawnDepth "
        "histogram, and whether the spawning Agent tool_result carries a "
        "toolUseResult rollup at each depth (counts only — no content emitted)",
    )
    args = parser.parse_args(argv)

    if args.probe_nesting:
        result = probe_nesting(args.root, max_files=args.max_files)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("# multi-level subagent nesting probe\n")
            print(
                f"{result['session_dirs']} session dir(s), {result['manifests']} manifest(s). "
                f"**Nested `subagents/` directories: {result['nested_subagent_dirs']}** "
                f"(0 == the layout is flat at every observed depth).\n"
            )
            print("## `spawnDepth` histogram\n")
            for d, n in result["spawn_depth_histogram"].items():
                print(f"- depth `{d}` — {n} manifests")
            print(
                f"\n## Spawn-site rollup shape\n\n"
                f"_{result['spawn_sites_located']} of {result['joinable_manifests']} "
                f"joinable manifests located their spawning tool_result "
                f"({result['spawn_sites_not_located']} not located)._\n"
            )
            if result["by_spawn_depth"]:
                for d, row in result["by_spawn_depth"].items():
                    print(f"- depth `{d}`: " + ", ".join(f"{k}={v}" for k, v in row.items()))
            else:
                print("_no spawn sites located_")
            print()
        return 0

    if args.probe_tool_results:
        result = probe_tool_results(args.root, max_files=args.max_files)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("# tool-results pointer probe\n")
            print(f"tool_result string contents scanned: {result['tool_result_string_contents']}\n")
            print("## Fixed-marker presence (count of tool_result contents containing each)\n")
            if result["marker_counts"]:
                for m, c in result["marker_counts"].items():
                    print(f"- `{m}` — {c}")
            else:
                print("_none of the hypothesis markers matched_")
            print("\n## Distinct persist/output-anchored tags observed\n")
            if result["persist_anchored_tags"]:
                for t, c in result["persist_anchored_tags"].items():
                    print(f"- `{t}` — {c}")
            else:
                print("_none_")
        return 0

    obs = Observation()
    scan(args.root, obs, max_files=args.max_files)

    diff = None
    if args.baseline:
        diff = diff_against_baseline(obs, load_baseline(args.baseline))

    report = build_report(obs, diff, max_files=args.max_files)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
