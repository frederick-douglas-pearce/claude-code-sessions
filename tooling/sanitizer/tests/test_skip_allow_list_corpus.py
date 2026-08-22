"""Drift detection for the skip allow-list (issue #194, AC-10).

The allow-list in ``pipeline.py`` enumerates the FORMAT's own string-leaf
positions by rooted path; everything else is visited and scrubbed. That
inverts the failure direction -- a position the list forgets is over-scrubbed
(visible) rather than user data being silently skipped -- but it makes the
list only as current as the corpus behind it, and this repo's corpus is a
handful of files. ``.claude/specs/research/jsonl-format-watch.md`` already
tracks line types with zero fixture coverage, so the format demonstrably grows
positions the list would not know about.

These tests are what turn that drift into a red test instead of a silent
change in behavior. They fail in different directions, deliberately, because
no single one of them covers a removal AND an addition AND a predicate that
stops honoring an entry:

  1. **Dead entries.** An allow-list path that matches nothing in the corpus
     is either a typo or a position that no longer exists. Either way it is
     not doing the job it claims to, and nothing else would ever say so.

  2. **New collisions.** A corpus path whose LEAF NAME is allow-listed but
     whose full path is not. Each one is a place where a name-keyed skip-list
     would have exempted data and the path-keyed one does not -- which is the
     whole of #194 -- so the set is pinned rather than merely reported. A new
     member is either a genuine new format position (add it) or a new
     user-data collision (leave it, and the pin records that the call was
     made deliberately).

  3. **A removal.** Pinned literally, below, because each test above has a
     blind spot for one: the ablation control parametrizes over the list, so
     deleting an entry deletes its own case.

  4. **An entry the predicate does not honor.** Ablation-tested per entry
     against a config whose rule matches the value at that position.

What NONE of them catches is a genuinely new format position whose name is
not already on the list -- the format-watch queue and human review are what
cover that, and no test here should be read as covering it.

No test here reads session data outside ``fixtures/`` -- per CLAUDE.md the
repo's own fixtures are the only corpus anything here may read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccs_sanitize.orchestrator import sanitize_session
from ccs_sanitize.pipeline import (  # noqa: PLC2701 — pinning the contract is the point
    _ENUM_PATHS,
    _FORMAT_PATHS,
    _IDENTIFIER_PATHS,
    _PRESERVE_PATHS,
    _UUID_PATHS,
    JsonPath,
    default_skip_predicate,
    serialize_line,
)

from ._helpers import write_config as _config

_ALLOW_LIST: frozenset[JsonPath] = _FORMAT_PATHS | _UUID_PATHS

# Repo root: tests/ -> sanitizer/ -> tooling/ -> <root>.
_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"

# Corpus paths carrying an allow-listed leaf NAME at a position the allow-list
# deliberately does not cover. Every member is a decision, not an oversight:
#
#   message.content.content.type  content-block `type` discriminators nested
#   toolUseResult.content.type    inside a tool_result payload. Enum-shaped, so
#                                 scrubbing them is a no-op today, but left OFF
#                                 on purpose: they sit on the tool-controlled
#                                 side of the format boundary, so exempting a
#                                 `type` key here would widen the exempt surface
#                                 into tool-shaped data -- #194 one level
#                                 deeper. The deciding line is that boundary,
#                                 NOT nesting depth: the outer sibling
#                                 `message.content.type` discriminates the rigid
#                                 Anthropic-API block and IS allow-listed. The
#                                 sibling text/payload is scrubbed regardless.
#   toolUseResult.task.id         a TodoWrite task id -- genuine user data,
#                                 and the concrete proof that `id` cannot be
#                                 allow-listed by name.
#   toolUseResult.type            allow-listed in the first cut of this PR and
#                                 REMOVED during review. The data dictionary
#                                 calls it a tool-specific subtype indicator on
#                                 a tool-dependent envelope, so the TOOL picks
#                                 the value -- the #194 shape one level in. The
#                                 deciding test is ownership, not how many
#                                 values it takes; `_ENUM_PATHS` in pipeline.py
#                                 carries the full argument and the `version` /
#                                 `message.model` counterexamples that rule out
#                                 the cardinality reading.
_KNOWN_NAME_COLLISIONS: frozenset[JsonPath] = frozenset({
    ("message", "content", "content", "type"),
    ("toolUseResult", "content", "type"),
    ("toolUseResult", "task", "id"),
    ("toolUseResult", "type"),
})


def _corpus_files() -> list[Path]:
    if not _FIXTURES.is_dir():
        return []
    return sorted(_FIXTURES.rglob("*.jsonl"))


def _string_leaf_paths(files: list[Path]) -> set[JsonPath]:
    """Every rooted string-leaf path in the corpus, list indices elided.

    Index elision matches ``walk_strings``: the skip-list is keyed on field
    names, so a path must be comparable to what the predicate actually sees.
    """
    found: set[JsonPath] = set()

    def walk(node: object, path: JsonPath) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + (key,))
        elif isinstance(node, list):
            for item in node:
                walk(item, path)
        elif isinstance(node, str):
            found.add(path)

    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                walk(json.loads(line), ())
            except json.JSONDecodeError:  # pragma: no cover - corpus is valid
                pytest.fail(f"unparseable JSONL in the corpus: {f}")

    return found


@pytest.fixture(scope="module")
def corpus_paths() -> set[JsonPath]:
    files = _corpus_files()
    if not files:
        pytest.skip(
            "fixtures/ is absent -- this runs from a repo checkout, not from "
            "the packaged sdist, whose contents stop at tooling/sanitizer/"
        )
    return _string_leaf_paths(files)


def test_every_allow_list_entry_exists_in_the_corpus(corpus_paths: set[JsonPath]) -> None:
    """A dead entry is a claim about the format that nothing backs.

    It fails silently in the worst way: it looks like coverage, so a reader
    checking "is `message.usage.speed` protected?" gets yes, while the real
    position may have moved. Every entry was verified present when the list
    was written; this keeps that true."""
    dead = _ALLOW_LIST - corpus_paths
    assert dead == set(), (
        "allow-list entries that match nothing in fixtures/ -- typo, or the "
        f"format moved: {sorted('.'.join(p) for p in dead)}"
    )


def test_name_collisions_in_the_corpus_are_the_known_set(
    corpus_paths: set[JsonPath],
) -> None:
    """The drift detector proper.

    A corpus path whose leaf name is allow-listed but whose rooted path is
    not is exactly the shape #194 is about: under the old bare-name rules it
    was skipped, under the allow-list it is scrubbed. Pinning the set means a
    new one has to be looked at and classified rather than silently absorbed
    in either direction."""
    allowed_names = {p[-1] for p in _ALLOW_LIST}
    collisions = {
        p for p in corpus_paths
        if p and p[-1] in allowed_names and p not in _ALLOW_LIST
    }
    assert collisions == _KNOWN_NAME_COLLISIONS, (
        "the set of allow-listed NAMES appearing at non-allow-listed PATHS "
        "changed. New members are either a format position to add to the "
        "allow-list or a user-data collision to leave scrubbed -- decide "
        f"which, then update _KNOWN_NAME_COLLISIONS.\n"
        f"  added:   {sorted('.'.join(p) for p in collisions - _KNOWN_NAME_COLLISIONS)}\n"
        f"  removed: {sorted('.'.join(p) for p in _KNOWN_NAME_COLLISIONS - collisions)}"
    )


def test_known_collisions_are_actually_visited(corpus_paths: set[JsonPath]) -> None:
    """The pinned collisions must be SCRUBBED, not merely unlisted.

    Without this the set above could be satisfied by a path the predicate
    skips for some other reason, which would make the pin describe something
    other than what it claims."""
    for path in _KNOWN_NAME_COLLISIONS:
        assert default_skip_predicate(path) is False, ".".join(path)


def test_allow_list_tiers_are_disjoint() -> None:
    """Runs without the corpus, so the packaged sdist still checks something.

    An entry in two tiers is harmless to the predicate -- it is a set union --
    but means the tier split has stopped describing the list, and that split
    is what tells a future reader which entries deserve scrutiny (a
    load-bearing preserve does; an enum discriminator is a no-op today).

    This checks all FOUR tiers pairwise. An earlier version asserted only
    ``_FORMAT_PATHS & _UUID_PATHS``, which is the union against one member and
    cannot see the case its own docstring named: a path duplicated between
    ``_IDENTIFIER_PATHS`` and ``_ENUM_PATHS`` passed."""
    tiers = {
        "_UUID_PATHS": _UUID_PATHS,
        "_PRESERVE_PATHS": _PRESERVE_PATHS,
        "_IDENTIFIER_PATHS": _IDENTIFIER_PATHS,
        "_ENUM_PATHS": _ENUM_PATHS,
    }
    names = sorted(tiers)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert tiers[a] & tiers[b] == frozenset(), f"{a} and {b} overlap"
    # And the tiers must actually account for the whole list.
    union: frozenset[JsonPath] = frozenset().union(*tiers.values())
    assert union == _ALLOW_LIST
    for path in _ALLOW_LIST:
        assert isinstance(path, tuple) and path, f"not a non-empty tuple: {path!r}"
        assert all(isinstance(seg, str) for seg in path), path


# ---------------------------------------------------------------------------
# The ablation control.
#
# The tests above check the allow-list against the CORPUS. Neither checks that
# an entry does anything, and the obvious candidate for that job does not do
# it: `test_golden_determinism.py` cannot detect a dropped entry. Removing any
# single entry leaves the golden output byte-identical, because the golden
# config holds only literal PII rules and no format-marker value contains one
# -- the same reason the Tier C comment in `pipeline.py` says visiting those
# positions is a no-op today. An earlier draft of this change claimed the
# golden test was the safety net for the inverted failure direction. It is
# not, and the claim was removed rather than weakened.
#
# This is the test that does the job: it makes each entry's protection
# OBSERVABLE by using a config whose rule actually matches the value sitting
# at that position. Delete an entry, and its cell goes red.
#
# The rule is a regex, and that is not incidental: with a literal rule the
# marker survives (which is the point) and the #195 output-side oracle then
# finds the configured literal in the output and fail-closes, so every cell
# would abort. A `re:` rule is not re-verified by the oracle.

_MARKER = "ALLOWLISTED-MARKER-VALUE"

_ABLATION_CONFIG = """
version: 1
identifiers:
  - match: "re:ALLOWLISTED-MARKER-VALUE"
    replace: "[scrubbed]"
"""


def _record_with(path: JsonPath, value: str) -> dict:
    """Build a line placing ``value`` at ``path``, plus a control leaf.

    Every allow-listed path is a chain of dict keys (``walk_strings`` elides
    list indices, so a dict chain reproduces the path the predicate sees for
    an element inside an array).
    """
    # ``run_pipeline`` requires a line-level ``type``; supply one unless the
    # path under test IS ``type``, in which case the marker takes its place
    # (the marker is not a stripped type, so the line still survives).
    root: dict = {"type": "assistant", "controlLeaf": value}
    node = root
    for segment in path[:-1]:
        node = node.setdefault(segment, {})
    node[path[-1]] = value
    return root


@pytest.mark.parametrize(
    "path", sorted(_ALLOW_LIST), ids=lambda p: ".".join(p)
)
def test_each_allow_list_entry_actually_protects_its_position(
    tmp_path: Path, path: JsonPath
) -> None:
    """One cell per entry: the value at an allow-listed path survives a rule
    that matches it, while the same value at ``controlLeaf`` is scrubbed.

    The control leaf is what stops this passing for the wrong reason. Without
    it a broken config, an unmatched regex or a transform that never ran
    would leave the marker in place everywhere and read as 30 protected
    positions."""
    config = _config(tmp_path, _ABLATION_CONFIG)
    out, _, _, _ = sanitize_session(
        [serialize_line(_record_with(path, _MARKER))], config
    )
    assert _MARKER in out[0], (
        f"{'.'.join(path)} is allow-listed but its value was scrubbed"
    )
    assert '"controlLeaf":"[scrubbed]"' in out[0], (
        "the control leaf was not scrubbed, so this cell proves nothing"
    )


# ---------------------------------------------------------------------------
# The exact-contents pin.
#
# The three tests above each have a blind spot for a REMOVED entry, and the
# ablation control has the worst one: it parametrizes over the allow-list, so
# deleting an entry deletes its own test case. That is the self-satisfying
# shape a drift test must not have, and it was found by ablating
# ``("message", "usage", "speed")`` -- the collision test caught it only
# because ``speed`` survived at the other usage parent, and dropping BOTH
# would have gone green.
#
# So the contents are pinned literally. Any add or remove turns this red and
# has to be answered deliberately, which is the one guarantee the other tests
# cannot give. Regenerate it only when you MEAN to change the scrub boundary,
# and say so in the CHANGELOG when you do -- this list is the boundary.
_EXPECTED_ALLOW_LIST: frozenset[JsonPath] = frozenset({
    # _UUID_PATHS
    ('agentId',),
    ('parentUuid',),
    ('sessionId',),
    ('toolUseResult', 'agentId'),
    ('uuid',),
    # _FORMAT_PATHS
    ('error', 'error', 'error', 'type'),
    ('error', 'error', 'type'),
    ('error', 'type'),
    ('message', 'content', 'caller', 'type'),
    ('message', 'content', 'id'),
    ('message', 'content', 'signature'),
    ('message', 'content', 'tool_use_id'),
    ('message', 'content', 'type'),
    ('message', 'diagnostics', 'cache_miss_reason', 'type'),
    ('message', 'id'),
    ('message', 'model'),
    ('message', 'role'),
    ('message', 'type'),
    ('message', 'usage', 'inference_geo'),
    ('message', 'usage', 'iterations', 'type'),
    ('message', 'usage', 'service_tier'),
    ('message', 'usage', 'speed'),
    ('requestId',),
    ('toolUseResult', 'usage', 'inference_geo'),
    ('toolUseResult', 'usage', 'iterations', 'type'),
    ('toolUseResult', 'usage', 'service_tier'),
    ('toolUseResult', 'usage', 'speed'),
    ('type',),
    ('version',),
})


def test_allow_list_contents_are_pinned() -> None:
    """The scrub boundary does not move without someone saying so."""
    assert _ALLOW_LIST == _EXPECTED_ALLOW_LIST, (
        "the skip allow-list changed. This IS the scrub boundary, so confirm "
        "the change is intended, then update this pin and the CHANGELOG.\n"
        f"  added:   {sorted('.'.join(p) for p in _ALLOW_LIST - _EXPECTED_ALLOW_LIST)}\n"
        f"  removed: {sorted('.'.join(p) for p in _EXPECTED_ALLOW_LIST - _ALLOW_LIST)}"
    )
