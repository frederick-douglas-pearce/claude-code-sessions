"""Post-scrub residual scans -- the sanitizer's last safety gates.

Two of them as of #195, and they are not the same shape. ``scan_residual``
re-runs the **secret** patterns over the serialized output lines.
``scan_residual_rules`` re-runs the ``paths``/``identifiers`` rules over the
**decoded** output tree -- literals position-agnostically and keys included,
and (as of #198) ``re:`` rules at reachable **value** positions only. Each
function's own docstring carries its contract; the module preamble below
describes the secret scan, which came first.

PRD reference: section 5 (the residual-scan philosophy) and section 11
(fail-closed posture / exit codes). The same ``COMPILED_SECRET_PATTERNS``
that ``rules/secrets.py`` uses to *redact during scrub* is re-applied here
to *verify* the serialized output. A match at this stage means a secret
survived redaction -- a sanitizer bug, a secret split across a transform
boundary, or a planted-in-a-skip-listed-field shape -- and the only safe
response is to refuse to write the output file at all.

The PRD calls out the conceptual split (section 5):

  1. **Detection during scrub** (expected): patterns match in the *input*
     and are redacted-and-counted into the sidecar.
  2. **Residual verification after scrub** (must be clean): the *same*
     patterns run over the *output*; a match is a failure condition.

This module owns step 2. It deliberately re-imports ``COMPILED_SECRET_PATTERNS``
rather than accepting a pattern list from the caller: the D-1 floor (built-in
patterns cannot be weakened from config, PRD section 12) is then structural,
not disciplinary -- there is no API to pass a pruned subset of built-ins.

D-2 invariant ("secrets are redacted, never stored", PRD section 10) extends
to ``ResidualSecretError``: only the matched pattern's ``kind`` label survives
in the error -- never the matched bytes -- so the invariant holds even in
exception messages, tracebacks, and any log output that captures them.

Exit-code mapping (CLI exit 2, PRD section 11) lives in cli.py (#26); this
module raises a distinct exception type so the CLI can emit a tailored
diagnostic distinguishing "input was malformed" (``PipelineError``) from
"a secret slipped past scrub" (``ResidualSecretError``).
"""

from __future__ import annotations

import json
from typing import Iterable, Iterator, Sequence

from .config import ExtraSecretPattern, Rule
from .pipeline import JsonPath, default_skip_predicate
from .rules.secrets import iter_all_secret_patterns


class ResidualSecretError(Exception):
    """Raised when the residual scan finds a secret in the serialized output.

    ``kind`` is the pattern label that matched (e.g. ``"anthropic-key"``);
    the matched bytes are intentionally **not** recorded on the exception
    so the D-2 "no stored originals" invariant survives propagation through
    logs and tracebacks. The CLI (#26) maps this to exit code 2.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(
            f"residual secret scan matched pattern kind={kind!r}; "
            f"output was not written"
        )
        self.kind = kind


def scan_residual(
    lines: Iterable[str], extras: Sequence[ExtraSecretPattern]
) -> None:
    """Scan the serialized sanitizer output lines for surviving secret patterns.

    Returns ``None`` on a clean scan; raises ``ResidualSecretError`` on the
    first match. The orchestrator's contract piggybacks on this: if
    ``sanitize_session`` returns at all, the residual scan passed, and the
    sidecar can record ``residual_scan: clean`` (PRD section 10).

    Scans **per line** rather than over a joined buffer. JSONL guarantees
    one record per line, ``serialize_line`` escapes embedded newlines, and
    every built-in credential pattern matches within a single line --
    including the PEM-armor header, which is one-line by construction. A
    per-line scan keeps the *semantics* of ``re.search`` aligned with what
    ``build_secret_transform`` applies per leaf (so anchored extras like
    ``re:^CORP-...$`` behave consistently between detect-during-scrub and
    verify-after-scrub), and avoids any cross-line spillover from patterns
    using ``\\s+`` (bearer-token, conn-string-pw).

    Pattern ordering reuses ``iter_all_secret_patterns(extras)`` so the
    "built-ins first, extras last" invariant is shared structurally with
    ``build_secret_transform`` -- a single definition of the iteration
    order across detect and verify sites.

    Args:
        lines: serialized output records (one per element). Iterated once.
        extras: ``Config.extra_secret_patterns``. Scanned after built-ins
            (see ``iter_all_secret_patterns``) so the failure label prefers
            the more general built-in kind on overlap. Intra-built-in
            tiebreak follows VENDORED_PATTERNS + BATCH_PATTERNS declaration
            order; reordering those lists silently changes the reported
            ``kind`` on overlapping matches, so the lists themselves are
            the contract.

    Raises:
        ResidualSecretError: a pattern (built-in or extra) matched some
            line. The exception carries only the pattern's ``kind`` label;
            the matched bytes are never recorded (D-2).
    """
    patterns = tuple(iter_all_secret_patterns(extras))
    for line in lines:
        for pattern, kind in patterns:
            if pattern.search(line):
                raise ResidualSecretError(kind)


class ResidualRuleError(Exception):
    """Raised when a literal ``paths``/``identifiers`` value survives into the output.

    Raised by ``scan_residual_rules`` when a literal rule matches the decoded
    output. Carries only ``section`` (``"paths"`` / ``"identifiers"``) and the
    rule's zero-based ``index`` within that section -- never ``Rule.pattern``
    and never the matched span. This is stricter than ``ResidualSecretError``
    needs to be, and deliberately so: a secret pattern's ``kind`` is a
    generic label, but a path/identifier rule's ``match`` value **is** the
    literal PII the config exists to scrub (real home dir, real name, real
    email). That is why the config file itself is gitignored (PRD section 12b).

    This gate fires on runs that otherwise look successful -- the ones that
    execute in CI and inside Claude Code sessions -- so a diagnostic carrying
    the match value would write real PII into exactly the artifact class this
    repo exists to sanitize. ``section[index]`` is enough to find the rule in
    a config the operator already has open.

    The CLI (#26) maps this to exit code 2.
    """

    def __init__(self, section: str, index: int) -> None:
        super().__init__(
            f"residual rule scan matched {section}[{index}]; "
            f"output was not written"
        )
        self.section = section
        self.index = index


def _iter_decoded_strings(
    node: object, path: JsonPath = ()
) -> Iterator[tuple[str, JsonPath, bool]]:
    """Yield ``(text, path, is_key)`` for every string in a decoded record, **keys included**.

    Dict keys are yielded because they are the whole of #190: ``walk_strings``
    recurses into a dict's *values* and copies its keys verbatim
    (``pipeline.py``), so a key is a position the scrub can never reach. A scan
    that visited only values would be blind to exactly the case it exists for.

    Document order, so a caller iterating rules outer and strings inner reports
    a stable ``section[index]``.

    **The path mirrors ``walk_strings``' discipline exactly** (#198), because
    the regex scan compares it against the same skip-list the walk consults and
    a divergence would silently mis-scope the exemption:

    - a dict value under key ``k`` at parent path ``p`` gets ``p + (k,)``;
    - **list indices are elided** -- ``[_walk(item, path) for item in value]``
      in ``pipeline.py`` passes the *parent* path down, which is what lets one
      allow-list entry like ``("message","content","id")`` cover
      ``message.content[3].id``. Eliding here too is not a simplification; the
      allow-list depends on it.

    A dict **key** is attributed **its value's path** (``p + (k,)``) and flagged
    ``is_key=True``. **The flag is load-bearing and the path is NOT sufficient
    on its own**, which is the whole of why this yields three values:

    ``walk_strings`` structurally cannot address a key at any path, so a key is
    never a position the walk "reached and declined to scrub". Worse, the skip
    allow-list cannot exempt one: ``_FORMAT_PATHS`` enumerates the **string
    leaves** the walk must not rewrite, so a format-owned key whose value is an
    int, a dict or null (``input_tokens``, ``stop_reason``, ``cache_creation``)
    has no entry there and never needed one. Treating "not skip-listed" as "user
    data" therefore misreads every one of those keys. Consumers must decide what
    a key means for themselves; ``_literal_rule_survives`` and
    ``_regex_rule_survives`` answer it differently, and the difference is the
    point.
    """
    if isinstance(node, str):
        yield node, path, False
    elif isinstance(node, dict):
        for key, value in node.items():
            child = path + (key,)
            yield key, child, True
            yield from _iter_decoded_strings(value, child)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_decoded_strings(item, path)


def scan_residual_rules(
    lines: Iterable[str],
    paths: Sequence[Rule],
    identifiers: Sequence[Rule],
) -> None:
    """Verify no **literal** ``paths``/``identifiers`` value survived into the output.

    The output-side oracle for the config rule family (#195). ``scan_residual``
    above gives the *secret* layer a position-agnostic guarantee: it re-reads
    the output, so a value the structural walk never reached is still there and
    still aborts the run. (Position-agnostic, **not** encoding-complete -- it
    reads the *serialized* text, so an escapable byte inside a match makes the
    two forms diverge. That is not confined to user-supplied extras: the
    built-in ``bearer-token`` is
    ``(?i)authorization:\\s*bearer\\s+[A-Za-z0-9._-]+`` and ``\\s`` matches a
    newline, which JSON escapes. Tracked in #217, split out of #198.) Paths and
    identifiers had no
    such pass, so
    any traversal gap leaked **silently** -- exit 0, output written, sidecar
    reporting ``residual_scan: clean``. Dict keys are never visited by the walk,
    and this scan refuses them for **literal** rules (#195/#190), which is what
    makes a literal value planted in a key a refusal rather than a leak. For
    ``re:`` rules the key position is **not** covered -- see
    ``_regex_rule_survives`` for the measured reason -- so it remains a silent
    leak for a regex config, tracked on #208 along with making the position
    scrubbable in the first place. (#190, which originally carried both, was
    scoped to detect-only and is closed.) #194, the skip-list exempting user
    data at any depth, is closed for the bare-name MECHANISM -- those positions are now visited
    and scrubbed. Say "the mechanism", not "the class": five of the 29
    allow-listed paths sit inside ``toolUseResult``, which is a tool-shaped
    envelope, so a tool whose result carries a top-level ``agentId`` or a
    ``usage.service_tier`` string still plants a value the walk refuses to
    visit. That residual is deliberate and argued at ``_ENUM_PATHS`` in
    pipeline.py (the runtime owns those keys, and scrubbing them corrupts
    format-owned fields), but it is a residual and this docstring should not
    round it to zero. The position
    space is still not ours to enumerate, which is why this function exists
    rather than a longer skip-list: tool inputs are tool-defined and MCP
    servers define their own schemas.

    **Two rule kinds, two different properties -- and the split is semantic
    rather than pragmatic.** Literals assert *"presence in the output is a leak,
    unconditionally"*. That is true of a literal rule, whose ``match`` **is** a
    specific real-world string the operator wants gone: its appearance at any
    depth, in any position, skip-listed or not, is a leak by definition. It is
    **not** true of a regex rule, whose ``match`` is a *shape*, and shapes
    legitimately survive scrub -- a runtime-synthesized UUID, or a field the
    pipeline preserves on purpose. Running an unconditional abort over a shape
    is a category error, and it is not hypothetical: with the default
    ``remap_uuids: false`` the UUID-graph fields are skip-listed *deliberately*
    so the parent/subagent graph stays linkable, so a UUID-shaped identifier
    rule aborted every session while nothing had been mis-scrubbed.

    Regex rules were therefore scoped out of #195 entirely and covered by the
    in-walk scrub alone. #198 gives them a **position-gated** check instead: a
    match counts at a **value** position the scrub could have acted on.
    ``_regex_rule_survives`` owns that contract -- including why dict keys are
    excluded, why the gate is the ``remap_uuids=False`` predicate rather than
    the run's own, and why the resulting exemption must stay positional rather
    than value-based. Read it before changing anything here.

    **What this does and does not close, stated exactly, because the scope was
    narrowed once already.** For regex rules it adds defense-in-depth over
    reachable value positions: a survivor there means the scrub failed, since
    the walk did reach it. It does **not** cover:

    - **dict keys**, which stay a silent leak for a regex config (#208) --
      gating them on the leaf allow-list false-aborted 8 of 8 fixture files;
    - **skip-listed positions**, #194's documented residual, so the five
      allow-listed paths under ``toolUseResult`` keep the exemption argued at
      ``_ENUM_PATHS``;
    - **the UUID-graph synthesis positions**, where the sanitizer wrote the
      value itself.

    Literals are unaffected throughout and remain position-agnostic, keys
    included. PRD section 10 must state that asymmetry rather than implying
    regex now carries the literal guarantee.

    **Scans the DECODED tree, not the serialized text.** Rules match decoded
    leaf values -- that is the domain ``walk_strings`` applies them in -- while
    a serialized line has JSON escaping applied. Scanning the serialized form
    silently missed every value containing a backslash, a quote or a control
    character: a Windows home directory (``C:\\Users\\name``) is the canonical
    ``paths`` case and serializes with doubled backslashes, so the rule could
    never match it and the value shipped with a clean sidecar.

    **Two limits of walking the decoded tree, neither implied away.** First, one
    level of decoding is not the same as "the domain the rules were authored
    in": a value nested inside a JSON-encoded *string* leaf carries its own
    escaping and is still missed -- by this scan and by the scrub, which has the
    same one-level behavior. That one is pre-existing.

    Second, and this scan's own shape: ``_iter_decoded_strings`` yields
    **strings**, so a configured value appearing as a JSON *number* is invisible
    to it, exactly as it is to the structural walk. The serialized-text scan
    this replaced would have matched it, so moving to the decoded domain closed
    the escaped-byte blind spot and opened a non-string-leaf one. Not a
    regression -- before #195 there was no rule scan at all -- and it matters
    because #126 (numeric GitHub user ids) is that shape. The nested-string limit
    is #220; the numeric-leaf one is recorded on #126 itself, which it blocks.

    **There is deliberately no allow-set.** An earlier version excused a match
    whose span was exactly a replacement the run had recorded, to stop a
    synthesized value tripping the scan. That was **unsafe and produced a real
    leak**: a regex rule's replacement is computed at runtime by
    ``match.expand()`` and is never vetted by I-3, which checks only the literal
    ``replace`` template. With ``paths: /home/realuser -> /home/user`` and
    ``identifiers: re:HOME_(\\w+) -> /home/\\1``, the input ``HOME_realuser``
    makes the identifier layer mint ``/home/realuser`` and record it, and the
    allow-set then excused the paths rule that would have caught it -- exit 0,
    the operator's real home directory in the output, ``residual_scan: clean``.

    Removing it costs nothing the config guard does not already provide.
    Load-time I-3 (``config.py`` ``_check_replacement_leak``) forbids a rule
    from matching any *configured* replacement, the gitBranch placeholder, or
    any ``<REDACTED:kind>`` placeholder, so none of those can trip this scan.

    **What removing it does and does not cost, since the two cases differ and
    conflating them understates one of them.** An allow-set tested *exact span
    membership*, so it only ever covered a **literal** ``match`` value equal to a
    *whole* synthesized value. Losing that is contrived -- it needs a rule whose
    match is a full 36-char UUID. What it never covered, and what removal
    therefore does not change, is a literal ``match`` that is a **substring** of
    one: under ``remap_uuids: true`` a rule like ``match: "dd9cca"`` aborts a
    correctly-scrubbed run, because that span is not itself a recorded
    replacement. Short hex-ish literals (a machine id, a commit-SHA prefix) are
    not exotic, and the remap is deterministic per ``(uuid_seed, original)``, so
    such a config fails on its first run rather than intermittently and keeps
    failing until it is edited. That is **pre-existing, availability-only, and
    recoverable by narrowing the rule** -- never a leak -- and it is tracked in
    **#218** rather than fixed here, because any guard that excuses a match
    falling inside a synthesized value re-introduces the class of mechanism this
    function exists without. (#198 fixed only the *regex* analog, which it
    created; see ``_regex_rule_survives``.)

    ``run_pipeline`` drops strip-types lines before returning, so a configured
    value on a dropped line is correctly **not** an abort -- it never reaches
    the output file.

    Args:
        lines: serialized output records, one per element. Re-parsed here, so
            each must be a JSON object; everything ``run_pipeline`` returns is.
        paths: ``Config.paths``, scanned first. Literal entries are checked
            position-agnostically, keys included; ``re:`` entries are checked
            only at **value** positions the ``remap_uuids=False`` skip predicate
            does not exempt.
        identifiers: ``Config.identifiers``. Same treatment, scanned second.
            Section order and ascending index within a section are part of the
            contract -- they decide which ``section[index]`` a multi-rule match
            reports, so tests can assert on it. Rules are **not** partitioned by
            kind before scanning, precisely so that order survives.

    Raises:
        ResidualRuleError: a literal rule matched anywhere in the decoded
            output, or a regex rule matched at a non-exempt value position. Carries
            the section and index only; neither the rule's ``match`` value nor
            the matched bytes are ever recorded (D-2). The two kinds raise the
            same exception on purpose -- the operator's remedy is the same, and
            distinguishing them in the message would say something about the
            rule the D-2 posture keeps out of diagnostics.
        json.JSONDecodeError: a line was not valid JSON. (A valid non-object --
            ``123``, ``"foo"`` -- does not raise; the walk simply scans or
            ignores it.) Unreachable through
            ``sanitize_session`` -- every element comes from ``serialize_line``
            -- and it fails closed at CLI exit 2 either way. Named here because
            an undocumented raise is how a caller learns the wrong lesson.
    """
    rules = tuple(
        (section, index, rule)
        for section, section_rules in (("paths", paths), ("identifiers", identifiers))
        for index, rule in enumerate(section_rules)
    )
    if not rules:
        return
    for line in lines:
        entries = list(_iter_decoded_strings(json.loads(line)))
        # Rules stay in ONE list in declaration order -- paths then
        # identifiers, ascending index -- rather than being split into a
        # literal pass and a regex pass. The section/index a multi-rule match
        # reports is a documented contract that tests assert on (see Args), and
        # two passes would reorder it: a regex ``paths[0]`` would be reported
        # after a literal ``identifiers[1]``. The dispatch is per rule, so the
        # order is untouched.
        for section, index, rule in rules:
            if rule.is_regex:
                if _regex_rule_survives(rule, entries):
                    raise ResidualRuleError(section, index)
            elif _literal_rule_survives(rule, entries):
                raise ResidualRuleError(section, index)


def _literal_rule_survives(
    rule: Rule, entries: Sequence[tuple[str, JsonPath, bool]]
) -> bool:
    """Position-agnostic literal check: presence anywhere in the output is a leak.

    ``search`` suffices: a literal is compiled ``re.escape``d, so every match of
    it has the same span and a second occurrence could not be classified
    differently from the first. That also makes a zero-width match impossible
    here (an empty ``match`` is rejected in ``_build_rules``), which is why this
    check needs no equivalent of the ``if not original`` guard that
    ``rules/_engine.apply_rule`` carries for regex rules.

    **Both the path and ``is_key`` are deliberately ignored.** A literal
    ``match`` **is** a specific real-world string the operator wants gone, so its
    appearance at any depth, in any position, skip-listed or not, key or value,
    is a leak by definition. This is the #195/#190 guarantee and #198 narrows
    none of it.
    """
    return any(rule.compiled.search(text) is not None for text, _path, _k in entries)


def _regex_rule_survives(
    rule: Rule, entries: Sequence[tuple[str, JsonPath, bool]]
) -> bool:
    """Position-gated regex check (#198): VALUE positions the scrub could have acted on.

    A regex ``match`` is a **shape**, not a value, and shapes legitimately
    survive scrub -- so the unconditional "presence is a leak" property the
    literal check asserts is a category error here. This check gates on position
    instead, and carries the two guards the literal path does not need.

    **Dict keys are NOT scanned, and this is a correction to #198 as first
    written.** The first implementation attributed a key its value's path and
    gated it on the skip predicate, reasoning that a non-skip-listed position is
    user-writable. That reasoning is **false**, and measurably so:
    ``_FORMAT_PATHS`` enumerates the **string leaves** the walk must not rewrite,
    so a format-owned key whose value is an int, a dict or null has no entry and
    never needed one. Against this repo's own ``fixtures/`` corpus an ordinary
    ``re:[a-z]{3,}_[a-z]{3,}`` rule aborted **8 of 8 files** on key names like
    ``input_tokens``, ``stop_reason`` and ``cache_creation`` -- exit 2, nothing
    written, no override, and unfixable by the scrub, since a key cannot be
    addressed. That is "aborted every session with nothing mis-scrubbed" all over
    again, so the key position is out of scope for regex rules and #208 carries
    it, alongside the key-visitation work it belongs with. Literal rules are
    unaffected and still refuse keys.

    **The value-position gate is ``default_skip_predicate`` -- the
    ``remap_uuids=False`` predicate -- and NOT the predicate the current run
    scrubbed with.** That divergence is deliberate, load-bearing, and the single
    most breakable thing in this function, so it is stated here rather than left
    to a call site:

    - Under ``remap_uuids: true`` ``make_skip_predicate`` **drops**
      ``_UUID_PATHS`` from the skip set (``pipeline.py``), so ``uuid``,
      ``parentUuid``, ``sessionId``, ``agentId`` and ``toolUseResult.agentId``
      become *visited* positions.
    - At exactly those visited positions the identifier layer **mints** a value:
      ``_remap_uuid`` returns a canonical 36-char UUID derived from
      ``sha256(seed + b"\\x00" + original)`` (``rules/identifiers.py``).
    - Load-time I-3 (``config.py`` ``_check_replacement_leak``) vets only the
      literal ``replace`` template and the fixed gitBranch / ``<REDACTED:kind>``
      placeholders. It never sees a runtime ``match.expand()`` value.

    So gating on the *run's* predicate would abort on the sanitizer's **own
    synthesized output**: a UUID-shaped identifier rule would exit 2 on every
    run, deterministically, with nothing mis-scrubbed and no override. Using the
    ``remap_uuids=False`` predicate exempts ``_UUID_PATHS`` unconditionally and
    closes it.

    **The exemption is POSITIONAL and must never become value-based.** Do not
    "improve" this by excusing a match whose span equals a recorded replacement
    or a synthesized value -- that is the allow-set described at length in
    ``scan_residual_rules``, and it produced a real leak (the ``/home/realuser``
    layer-order case). A positional exemption cannot excuse that leak, because a
    path leaf is not a UUID position. ``_UUID_PATHS`` is a fixed five-element
    set known at load time; a value allow-set is dynamic and unbounded.

    **Two guards the literal path does not need:**

    - **Zero-width.** ``_reject_zero_width_pattern`` only tests
      ``compiled.match("")``, so an *input-dependent* zero-width pattern
      (``re:(?=hello)``, ``re:\\b``) passes load and reaches here. An empty
      subject is skipped, and a match spanning no characters is skipped: it
      carries no PII, and aborting on one would fail every input containing a
      word boundary. **This mirrors the scrub rather than compensating for it** --
      ``rules/_engine.apply_rule`` also no-ops on a zero-width match -- so a rule
      matching ONLY zero-width scrubs nothing and is reported by neither layer.
      That is a pre-existing silent no-op rather than something this check
      introduced -- before #198 regex rules were not scanned at all, so such a
      rule leaked identically -- and it is tracked as #222. PRD section 10 lists
      it among the things ``residual_scan: clean`` does not attest to.
    - **``finditer``, not ``search``.** A regex's match spans vary within one
      string, so a zero-width first match must not excuse a genuine survivor
      later in the same string.
    """
    for text, path, is_key in entries:
        if is_key or not text:
            continue
        if default_skip_predicate(path):
            continue
        for match in rule.compiled.finditer(text):
            if match.start() == match.end():
                continue
            return True
    return False


__all__ = [
    "ResidualRuleError",
    "ResidualSecretError",
    "scan_residual",
    "scan_residual_rules",
]
