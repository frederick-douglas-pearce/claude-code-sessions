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
change in behavior. Two directions, because they fail differently:

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

Neither test reads session data outside ``fixtures/`` -- per CLAUDE.md the
repo's own fixtures are the only corpus anything here may read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccs_sanitize.pipeline import (  # noqa: PLC2701 — pinning the contract is the point
    _FORMAT_PATHS,
    _UUID_PATHS,
    JsonPath,
    default_skip_predicate,
)

_ALLOW_LIST: frozenset[JsonPath] = _FORMAT_PATHS | _UUID_PATHS

# Repo root: tests/ -> sanitizer/ -> tooling/ -> <root>.
_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"

# Corpus paths carrying an allow-listed leaf NAME at a position the allow-list
# deliberately does not cover. Every member is a decision, not an oversight:
#
#   message.content.content.type  the tool_result content array. The data
#   toolUseResult.content.type    dictionary documents both as arbitrary
#                                 tool output, so exempting a `type` key
#                                 inside them would be #194 one level deeper.
#   toolUseResult.task.id         a TodoWrite task id -- genuine user data,
#                                 and the concrete proof that `id` cannot be
#                                 allow-listed by name.
_KNOWN_NAME_COLLISIONS: frozenset[JsonPath] = frozenset({
    ("message", "content", "content", "type"),
    ("toolUseResult", "content", "type"),
    ("toolUseResult", "task", "id"),
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


def test_allow_list_tiers_do_not_overlap() -> None:
    """Runs without the corpus, so the packaged sdist still checks something.

    An entry in two tiers is harmless to the predicate (it is a set union)
    but means the tier split -- load-bearing preserves vs enum discriminators
    -- has stopped describing the list, and that split is what tells a future
    reader which entries deserve scrutiny."""
    assert _FORMAT_PATHS & _UUID_PATHS == frozenset()
    for path in _ALLOW_LIST:
        assert isinstance(path, tuple) and path, f"not a non-empty tuple: {path!r}"
        assert all(isinstance(seg, str) for seg in path), path
