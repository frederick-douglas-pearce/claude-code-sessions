"""`.scrubbed` sidecar emission.

PRD reference: section 10 (the `.scrubbed` sidecar -- redacted-by-design
format, D-2). The sidecar is the auditable record of what changed in a
sanitizer run; it must surface category-level detail without itself
echoing any original sensitive token.

This module is **pure data assembly**: ``build_sidecar`` consumes the
4-tuple from ``sanitize_session`` plus a small ``SidecarMetadata`` record
and returns a YAML string. It performs no file I/O. The CLI (#26) is
responsible for reading the raw input (to compute the SHA-256), choosing
the output path, writing the temp file, and performing the atomic rename
ordering documented in PRD section 11 (sidecar-first-then-output) -- all
of which would force a refactor here if this module also did I/O.

**I-3 emit-time leak guard.** The config loader's ``_check_replacement_leak``
already guarantees that no user ``replace`` value matches any other rule
or any built-in / extra secret pattern (PRD section 10, I-3). The sidecar
re-runs that check at emit time against the *rendered YAML string* as
defense-in-depth: a configured original token should never appear in the
output, and no built-in or extra secret pattern should match. If either
condition fires, ``SidecarLeakError`` is raised and the CLI declines to
write the sidecar (mapping to exit 2). The two checks together pin the
PRD section 14 "sidecar-never-leaks" test (I-3) structurally rather than
disciplinarily.

**Placeholder synthesis (Option A per architect review on #25).** The
PRD section 10 example uses human-friendly placeholders like
``<home-dir>`` and ``<email>``. The YAML rule schema carries no category
field, so we synthesize placeholders from each entry's ``label``:

  - ``"identifiers:gitBranch"`` -> ``"<git-branch>"``
  - ``"identifiers:uuid"``      -> ``"<uuid>"``
  - ``"paths"``                 -> ``"<path-N>"``       (1-based)
  - ``"identifiers"``           -> ``"<identifier-N>"`` (1-based)

Numbering restarts per layer and follows insertion order, so a config
diff that adds a single new rule produces a one-line sidecar diff -- the
existing entries keep their indices.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import yaml

from . import __version__
from .config import Config
from .pipeline import PipelineCounts
from .rules.secrets import SecretCounts, iter_all_secret_patterns
from .subtable import SubstitutionTable

# One registry per label co-locates (rule_layer, placeholder_template). A
# template containing ``{idx}`` is indexed (counter restarts per rule_layer);
# any other template is emitted verbatim. Adding a new label is a single-line
# edit instead of synchronizing three sharded dicts -- the previous shape
# made it possible to register a label in one map but forget the others,
# producing sidecars where _build_substitutions emitted a row that
# _rule_layer_totals refused to count.
_LABEL_REGISTRY: dict[str, tuple[str, str]] = {
    "paths": ("paths", "<path-{idx}>"),
    "identifiers": ("identifiers", "<identifier-{idx}>"),
    "identifiers:gitBranch": ("identifiers", "<git-branch>"),
    "identifiers:uuid": ("identifiers", "<uuid>"),
}


def _resolve_label(label: str) -> tuple[str, str]:
    """Map a substitution-table label to ``(rule_layer, placeholder_template)``.

    Known labels are looked up in ``_LABEL_REGISTRY``. Unknown labels derive
    ``rule_layer`` from the colon-prefix (so a future ``"paths:cwd"`` rolls
    up under ``"paths"`` in ``rules_applied`` automatically, matching the
    existing ``"identifiers:gitBranch"`` / ``"identifiers:uuid"`` convention)
    and fall back to an ``<unknown-{idx}>`` placeholder so the sidecar stays
    well-formed. This keeps ``_build_substitutions`` and the rule-layer
    totals helper consistent for unregistered labels -- the previous shape
    let ``_build_substitutions`` emit a row that the totals helper silently
    excluded from ``rules_applied.{paths,identifiers}.substitutions``.
    """
    if label in _LABEL_REGISTRY:
        return _LABEL_REGISTRY[label]
    rule_layer = label.split(":", 1)[0] if ":" in label else label
    return (rule_layer, "<unknown-{idx}>")


class SidecarLeakError(Exception):
    """Raised when the I-3 emit-time guard finds a sensitive token in the
    rendered sidecar.

    Carries the offending category (``"original"`` or a secret pattern
    ``kind`` label) so the CLI (#26) can map to exit 2 with a tailored
    diagnostic. The matched bytes are not stored on the exception (D-2
    invariant): the sidecar leak guard exists *because* originals must
    never propagate; surfacing the matched bytes in the exception would
    defeat its own purpose.
    """

    def __init__(self, category: str) -> None:
        super().__init__(
            f"sidecar emit-time leak guard fired (category={category!r}); "
            f"sidecar was not produced"
        )
        self.category = category


@dataclass(frozen=True)
class SidecarMetadata:
    """Per-run context the sidecar embeds that does not come from the
    pipeline result.

    The CLI assembles this from its arguments and the raw input file (read
    once for the SHA-256). Keeping the metadata as a typed record rather
    than loose kwargs makes the contract explicit: the sidecar emitter
    does not know the input path, only its basename; does not read the
    file, only its hash; and does not invent the timestamp, so a test can
    pin a known value for byte-stability assertions.

    Field constraints:

      - ``input_filename``: basename only (PRD section 10 -- "never the
        full path"). The CLI must apply ``Path(input).name`` before
        constructing this record.
      - ``input_sha256``: lowercase hex SHA-256 of the raw input bytes.
      - ``config_source``: basename only, for the same reason.
      - ``scrubbed_at``: ISO 8601 UTC ending in ``Z``, e.g.
        ``"2026-05-31T18:30:00Z"``. The CLI typically computes this via
        ``utc_now_iso8601()`` immediately before calling ``build_sidecar``.
    """

    input_filename: str
    input_sha256: str
    config_source: str
    scrubbed_at: str


def utc_now_iso8601() -> str:
    """Return the current UTC time as an ISO 8601 string ending in ``Z``.

    Helper for the CLI; not used by ``build_sidecar`` (which takes the
    timestamp as a parameter so tests can pin it).
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data: bytes) -> str:
    """Compute lowercase hex SHA-256 of ``data``.

    Helper for the CLI to fill ``SidecarMetadata.input_sha256``. The
    sanitizer reads the raw input bytes once for this hash; the hash
    itself is a one-way digest, safe to embed in the sidecar (PRD
    section 10).
    """
    return hashlib.sha256(data).hexdigest()


def build_sidecar(
    *,
    metadata: SidecarMetadata,
    config: Config,
    serialized_lines: Sequence[str],
    counts: PipelineCounts,
    subtable: SubstitutionTable,
    secret_counts: SecretCounts,
) -> str:
    """Build the `.scrubbed` sidecar YAML string for a successful run.

    Callers MUST only invoke this after ``sanitize_session`` returns --
    if that function returns, the residual scan passed and the sidecar
    can unconditionally record ``residual_scan: clean`` (PRD section 10).
    A failed run produces no sidecar.

    Args:
        metadata: per-run context (filename, hash, config source,
            timestamp). The CLI assembles this.
        config: the loaded config -- ``config.version`` becomes
            ``config_version``, and ``config.extra_secret_patterns`` is
            scanned by the I-3 emit-time leak guard.
        serialized_lines: post-scrub output lines, used only to compute
            ``lines_processed = len(out) + sum(stripped) + blank_lines``.
            The blank count comes from ``counts.blank_lines`` so the
            sidecar reports the number of input items the pipeline
            iterated (survivors + stripped + blanks). Without it, a
            file with interior whitespace lines undercounts by the
            number of blanks (#43).
        counts: ``PipelineCounts`` from ``run_pipeline``.
        subtable: the substitution table populated by paths/identifiers.
        secret_counts: ``SecretCounts`` populated by the secrets layer.

    Returns:
        A YAML document as a string, ready to be written to
        ``<output>.scrubbed`` by the CLI.

    Raises:
        SidecarLeakError: a user-derived value in the sidecar payload
            (a replacement, metadata string, or strip-type key) contains
            a configured original token or matches a built-in/extra secret
            pattern (I-3). The exception's ``category`` field names what
            fired; the matched bytes are intentionally not stored.
    """
    totals = _rules_applied_totals(subtable)
    paths_subs, paths_distinct = totals.get("paths", (0, 0))
    identifiers_subs, identifiers_distinct = totals.get("identifiers", (0, 0))

    stripped_lines = dict(counts.stripped_lines)
    # PRD §10: ``lines_processed`` is the audit field that equals the
    # number of items the pipeline iterated -- survivors + stripped-by-
    # type + blank/whitespace-only input lines (#43). A fixture-validator
    # diffing against the input's ``split("\n")`` length sees parity.
    # NOTE: this is not literal ``wc -l`` parity; the CLI splits on "\n"
    # (cli.py), so a file ending in a trailing newline yields one extra
    # empty element vs the newline count. The audit identity we DO
    # maintain (input items iterated) is the one the test suite asserts.
    lines_processed = (
        len(serialized_lines) + sum(stripped_lines.values()) + counts.blank_lines
    )

    substitutions = _build_substitutions(subtable)

    # Ordered dict so the rendered YAML matches PRD section 10's field order
    # one-for-one. ``sort_keys=False`` in ``yaml.safe_dump`` preserves it.
    payload: dict[str, Any] = {
        "sanitizer_version": __version__,
        "scrubbed_at": metadata.scrubbed_at,
        "input_filename": metadata.input_filename,
        "input_sha256": metadata.input_sha256,
        "config_version": config.version,
        "config_source": metadata.config_source,
        "lines_processed": lines_processed,
        "stripped_lines": stripped_lines,
        "rules_applied": {
            "paths": {"substitutions": paths_subs, "distinct": paths_distinct},
            "identifiers": {
                "substitutions": identifiers_subs,
                "distinct": identifiers_distinct,
            },
            "secrets": {"matches": secret_counts.total()},
            "jitter": "disabled",
        },
        "substitutions": substitutions,
        "residual_scan": "clean",
    }

    # Leak guard runs on the payload BEFORE rendering so the YAML
    # scaffolding (keys, fixed placeholders, ``jitter: disabled``,
    # ``residual_scan: clean``) is not part of the scan surface -- those
    # bytes are sanitizer-controlled, never user-derived, so scanning them
    # only produces false positives. Pre-render scanning also avoids the
    # yaml.safe_dump escaping bypass (a multi-line original would not
    # appear literally in the rendered string).
    _check_emit_time_leak(payload, subtable, config)
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)


def _build_substitutions(subtable: SubstitutionTable) -> list[dict[str, Any]]:
    """Emit one row per subtable entry, in insertion order, with the
    synthesized ``rule`` and ``placeholder`` columns the sidecar contract
    requires (PRD section 10).

    Per-rule-layer indices restart at 1 so the placeholder strings are
    stable across runs over the same input: ``<path-1>`` is always the
    first paths entry inserted, regardless of how many identifier rules
    ran first. Indexed counters are kept per ``rule_layer`` (not per raw
    label), so a future ``"paths:cwd"`` sub-label sharing the indexed
    template would advance the same counter as ``"paths"`` and an
    ``<unknown-1>`` produced by an unregistered label does not shift
    when an unrelated registered layer adds entries.
    """
    indices: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for entry in subtable:
        rule_layer, template = _resolve_label(entry.label)
        if "{idx}" in template:
            indices[rule_layer] = indices.get(rule_layer, 0) + 1
            placeholder = template.format(idx=indices[rule_layer])
        else:
            placeholder = template
        out.append(
            {
                "rule": rule_layer,
                "placeholder": placeholder,
                "replacement": entry.replacement,
                "occurrences": entry.occurrences,
            }
        )
    return out


def _rules_applied_totals(
    subtable: SubstitutionTable,
) -> dict[str, tuple[int, int]]:
    """Bucket subtable entries by rule_layer in a single pass.

    Returns ``{rule_layer: (total_occurrences, distinct_entries)}``. The
    rule_layer key matches what ``_build_substitutions`` emits in each
    row's ``rule:`` column, so the two views of the data agree by
    construction -- a row whose ``rule:`` is ``"identifiers"`` is counted
    in ``rules_applied.identifiers``, including the ``identifiers:gitBranch``
    and ``identifiers:uuid`` variants that ``_resolve_label`` collapses
    onto the same rule_layer.
    """
    buckets: dict[str, tuple[int, int]] = {}
    for entry in subtable:
        rule_layer, _ = _resolve_label(entry.label)
        subs, distinct = buckets.get(rule_layer, (0, 0))
        buckets[rule_layer] = (subs + entry.occurrences, distinct + 1)
    return buckets


def _check_emit_time_leak(
    payload: dict[str, Any], subtable: SubstitutionTable, config: Config
) -> None:
    """I-3 defense-in-depth at sidecar emit time.

    Scans only the *leak-prone, user-derived* strings in the payload:

      - ``input_filename`` and ``config_source`` -- CLI-provided basenames
        that could carry sensitive substrings if a user named their file
        ``realuser-session.jsonl`` (etc.).
      - each ``stripped_lines`` key -- comes from the JSONL ``type`` field
        and (under ``--strip-types``) from the CLI.
      - each substitution row's ``replacement`` -- the rule's ``replace:``
        value verbatim; the most likely vector for a misconfiguration to
        smuggle an original through.

    Deliberately NOT scanned:

      - ``input_sha256`` -- one-way digest of opaque bytes; cannot
        legitimately carry an original (false positives on short
        originals coincidentally appearing in the hex are realistic;
        true positives are statistically vanishing).
      - ``scrubbed_at`` -- sanitizer-generated UTC timestamp; same logic.
      - YAML scaffolding (top-level keys, the rule_layer names in
        ``rules_applied``, the synthesized ``<path-N>``/``<git-branch>``/
        ``<uuid>``/``<identifier-N>`` placeholders, the literal
        ``disabled`` and ``clean`` values, numeric counts) -- sanitizer-
        controlled at runtime; cannot contain user data; scanning it
        would only produce false positives, e.g. a short original like
        ``"user"`` matching ``"/home/user"`` in another entry's
        replacement, or an ``extra_secret_patterns`` regex matching the
        sidecar's own placeholder syntax.

    Pre-render scanning (over the payload dict, not the rendered YAML
    string) also avoids the ``yaml.safe_dump`` escaping bypass: a
    multi-line original would not literally appear in the rendered
    output (newlines become ``\\n`` escapes), but the raw Python string
    in the payload does.

    The config loader (``_check_replacement_leak``) already rejects
    configurations where a replacement matches another rule or any
    secret pattern, so in normal operation neither check below fires.
    This is the structural backstop: a future refactor that puts an
    original into the sidecar by mistake (e.g., ``_build_substitutions``
    accidentally emits ``entry.original``) raises here rather than
    landing as a quietly broken sidecar.
    """
    scannable: list[str] = [
        payload["input_filename"],
        payload["config_source"],
    ]
    scannable.extend(payload["stripped_lines"].keys())
    scannable.extend(row["replacement"] for row in payload["substitutions"])

    # Filter empty originals defensively: ``"" in value`` is always True
    # and would make the guard fire on every clean run. The rule layers
    # already short-circuit empty leaves before calling ``record()``, so
    # this branch only protects against a future direct caller that
    # bypasses those guards.
    originals = [entry.original for entry in subtable if entry.original]
    patterns = list(iter_all_secret_patterns(config.extra_secret_patterns))
    for value in scannable:
        for original in originals:
            if original in value:
                raise SidecarLeakError("original")
        for pattern, kind in patterns:
            if pattern.search(value):
                raise SidecarLeakError(kind)


__all__ = [
    "SidecarLeakError",
    "SidecarMetadata",
    "build_sidecar",
    "sha256_hex",
    "utc_now_iso8601",
]
