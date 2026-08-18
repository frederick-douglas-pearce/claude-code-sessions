# Generator — `golden-session.jsonl` and its expected artifacts

**Synthetic. Fabricated by hand for issue #162; never derived from a real session.**

Every value in `golden-session.jsonl` is invented. The home directory
(`/home/goldenuser`), the email (`golden.author@example.net`, RFC 2606
reserved TLD), the GitHub handle (`golden-handle`), the personal name
(`Golden Author`), the AWS-shaped key (`AKIA` + `EXAMPLEKEY000000`), and the
bearer token are all placeholders chosen so that no rule in
`golden-config.yaml` can ever match a real person, host, or credential. The
UUIDs are hand-authored repeating-digit strings, not session UUIDs.

## What this fixture is for

It is the **cross-interpreter determinism artifact**. The sanitizer's public
contract is "same input + same config produces byte-identical output" (see
[Stability and the determinism contract](../../README.md#stability-and-the-determinism-contract)),
and external consumers gate on it. Before #162, every determinism test ran
the same input twice on the *same* interpreter, which proves an interpreter
agrees with itself and nothing more. Consumers do not scrub and validate on
the same host: someone scrubs on 3.11 and the fixture-validator checks on
3.13.

`tests/test_golden_determinism.py` asserts the committed bytes in **every**
matrix cell (3.11 / 3.12 / 3.13), so all three interpreters must match the
same committed artifact rather than merely matching themselves.

## Files

| File                                   | Role                                                    |
| -------------------------------------- | ------------------------------------------------------- |
| `golden-session.jsonl`                 | Input. Fabricated session.                              |
| `golden-config.yaml`                   | Pinned rules. Committed, not gitignored (no real PII).  |
| `golden-session.expected.jsonl`        | Expected scrubbed output, byte for byte.                |
| `golden-session.expected.jsonl.scrubbed` | Expected sidecar, with two fields normalized (below). |

## What the input deliberately exercises

Each element is here because a serialization or ordering regression would
show up in it:

- **Non-ASCII** (`café`, `résumé`, `✅`) pins `ensure_ascii=False`. An
  interpreter or library change that started escaping to `\uXXXX` would
  change the bytes without changing the meaning, which is exactly the class
  of drift this fixture exists to catch.
- **A path plus the project-dir encoding** (`-home-goldenuser-projects-demo`)
  pins the paths layer running before the identifier layer.
- **Four identifier rules** (email, bare username, handle, personal name)
  pin per-layer placeholder numbering (`<identifier-1>` … `<identifier-4>`),
  which is insertion-ordered and therefore order-sensitive.
- **`gitBranch`** pins `scrub_git_branch: true`.
- **A Tier-1 secret** (`aws-access-key-id`) and **a Tier-2 secret**
  (`bearer-token`) pin the built-in floor and the `<REDACTED:kind>` shape.
- **One `file-history-snapshot` and one `attachment` line** pin the
  `--strip-types` default.
- **An interior blank line** pins `lines_processed` counting blanks (#43).

## Two normalized sidecar fields

The expected sidecar carries `<normalized>` for `sanitizer_version` and
`scrubbed_at`. Both are per-run by construction: the version moves on every
release, and the timestamp moves on every run. Baking either into the golden
bytes would make the fixture fail for a reason that has nothing to do with
determinism, and a fixture that fails routinely stops being read.

The test normalizes those two lines on the produced sidecar before
comparing, and asserts them separately: `sanitizer_version` must equal
`ccs_sanitize.__version__`, and `scrubbed_at` must match the ISO-8601-Z
shape. Everything else in the sidecar, including `input_sha256`, the
substitution rows, and the counts, is compared byte for byte.

## Regenerating — read this first

**A change in the golden bytes is a finding, not a chore.** The bytes are the
published determinism promise. If this test goes red, the default assumption
is that the sanitizer changed its output, and the question to answer is
whether that change is intended.

When the change *is* intended, it is a version bump under the
[CHANGELOG policy](../../CHANGELOG.md), not a silent regeneration:

1. Confirm the diff is the change you meant to make, line by line. A
   one-character diff in an unrelated line means something else moved too.
2. Bump the sanitizer version and record the output change in
   `CHANGELOG.md`. Byte-level output changes are what the determinism
   contract versions.
3. Only then regenerate:

   ```bash
   cd tooling/sanitizer
   python -m ccs_sanitize.cli tests/golden/golden-session.jsonl \
     -o /tmp/golden-out.jsonl \
     -c tests/golden/golden-config.yaml \
     --no-check --force
   cp /tmp/golden-out.jsonl tests/golden/golden-session.expected.jsonl
   sed -e 's/^sanitizer_version: .*/sanitizer_version: <normalized>/' \
       -e 's/^scrubbed_at: .*/scrubbed_at: <normalized>/' \
       /tmp/golden-out.jsonl.scrubbed \
       > tests/golden/golden-session.expected.jsonl.scrubbed
   ```

`--no-check` is correct here and only here: `golden-config.yaml` is
committed on purpose because it holds no real PII, so the pre-run gitignore
guard has nothing to protect. It is not the fix for exit 3 on a live config.

Do not edit `golden-session.jsonl` or `golden-config.yaml` to make a failing
test pass. Editing the input changes what the artifact proves.

## Verified against

Authored and first generated against `ccs-sanitize` 0.3.0 on 2026-08-17,
sidecar schema version 1.
