# Releasing `claude-code-sessions-sanitizer`

The machine half of a release is
[`.github/workflows/sanitizer-release.yml`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.github/workflows/sanitizer-release.yml).
This file is the human half: the account setup, the approval, and the checks no
workflow can perform for you. Issue
[#163](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/163)
is the origin.

Two things this file deliberately does not restate, because they are owned
elsewhere and duplicating them would let them drift:

- **What a version bump promises a consumer.** That is
  [Stability and the determinism contract](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/README.md#stability-and-the-determinism-contract)
  in the README.
- **What happens when someone finds a scrubbing hole.**  That is
  [SECURITY.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/SECURITY.md),
  which owns disclosure, supported versions, and the yank-not-delete response.

## One-time setup

Nothing below is in the repo. It is all console state, and none of it is done
yet as of the PR that added this file. Do it in this order, because the pending
publisher has to exist before the first upload for that upload to be OIDC.

1. **Accounts with 2FA.** A PyPI account and a TestPyPI account, both with 2FA
   enabled. PyPI requires it for uploads.

2. **Two GitHub environments,** under Settings, Environments:

   | Environment          | Gates                                                       |
   | -------------------- | ----------------------------------------------------------- |
   | `pypi-sanitizer`     | required reviewer; deployment tag rule limited to `sanitizer-v*` |
   | `testpypi-sanitizer` | deployment tag rule limited to `sanitizer-v*`                |

   The names are component-scoped for the same reason the tags are. GitHub
   environments are repo-global and a trusted publisher binds to the triple
   (repo, workflow, environment), so a generic `pypi` would be spent on the
   first tool that published, and the second one would need a new name and a
   re-registered publisher.

   The deployment tag rule is worth more than it looks. The trigger filter and
   the `if:` conditions in the workflow live in a file, so a tag that carries a
   tampered workflow carries tampered conditions too. The environment rule is
   repo settings and survives that.

3. **Pending trusted publishers,** on PyPI and on TestPyPI. Use the *pending*
   publisher flow (Your projects, Publishing) rather than creating the project
   first. A project bootstrapped with an API token leaves a credential that
   existed, which is the thing this whole setup is avoiding. Register on both
   indexes:

   | Field       | Value                                            |
   | ----------- | ------------------------------------------------ |
   | PyPI project| `claude-code-sessions-sanitizer`                 |
   | Owner       | `frederick-douglas-pearce`                        |
   | Repository  | `claude-code-sessions`                            |
   | Workflow    | `sanitizer-release.yml`                           |
   | Environment | `pypi-sanitizer` / `testpypi-sanitizer`           |

   No `PYPI_API_TOKEN` is ever added to repo secrets. If you find one there,
   that is a finding, not a convenience.

## Cutting a release

Steps 1 and 2 are ordinary PR work. Step 3 onward is the release proper.

Steps 3 through 7 are driven by
[`release.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/release.py)
(issue [#181](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/181)).
It takes no version argument: `__version__` is already the source of truth and the
tag is mechanically `sanitizer-v<version>`, so it derives both. The raw commands
are kept below each step on purpose. A runbook that only works when the wrapper
works has a bootstrapping problem, and the night of a security release is the
wrong time to find that out.

The driver cannot publish, never approves a deployment, and never deletes or
force-updates anything on `origin`. Its only outward write is pushing one tag.

```bash
python3 tooling/sanitizer/release.py preflight   # read-only; run before step 3
```

Preflight checks the same things the workflow's gates do, plus a few the workflow
cannot: on `main`, clean, level with `origin/main`, CHANGELOG entry present, tag
free, `sanitizer-ci` green on `HEAD`, and the version not already spent on either
index. It fails on your laptop in two seconds instead of in CI in ninety.

It writes nothing, but it is a **pre-tag** gate rather than a status command. Once
step 4 has rehearsed a version onto TestPyPI, preflight for that version reports
it as spent, which is correct and expected. Do not read that as the release having
gone wrong; it means you are past this step.

One caveat worth keeping straight: preflight's CI check is **advisory**. It reads
the existing `sanitizer-ci` check run on `main@HEAD`, which is a different
question from the workflow's re-run on the tagged ref. The workflow's `ci` job is
the authority. Nothing should ever skip it because preflight was green.

1. **Bump and document.** Update `__version__` in
   `src/ccs_sanitize/__init__.py` and add the matching `## [x.y.z]` heading to
   [`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md),
   following that file's "bump on any byte-affecting change" policy. The
   release workflow fails closed if either is missing or if they disagree with
   the tag, so a mismatch costs a run, not a version number.

2. **Merge it.** Normal PR, `sanitizer-ci` green.

3. **Tag the merged commit** and push the tag:

   ```bash
   python3 tooling/sanitizer/release.py tag        # add --dry-run to see it first
   ```

   It runs preflight, prints the version, tag, target commit and its subject,
   and requires you to type the tag before it pushes anything.

   **This subcommand needs a real terminal.** The confirmation reads from stdin,
   so anywhere without a TTY (a CI step, an agent session, a piped invocation) it
   prints `confirmation needs an interactive terminal; nothing was pushed` and
   exits non-zero. That is the gate working, not a failed release. It is easy to
   misread as one, though, because it arrives after eight green preflight lines.
   `tag` is the only subcommand with this constraint, which is not a coincidence:
   it is also the only one that writes to `origin`. Without a terminal, use the
   equivalent by hand:

   ```bash
   git checkout main && git pull
   git tag sanitizer-v0.3.0
   git push origin sanitizer-v0.3.0
   ```

   The tag is `sanitizer-v<version>`, never a bare `v<version>`. Rationale is
   in the README's
   [Releases and tagging](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/README.md#releases-and-tagging)
   section.

   The push starts the release workflow. It re-runs the full test matrix and
   the packaging job on the tagged commit, builds with the pinned backend,
   smoke-tests the artifact it just built, and then **stops** at the
   `pypi-sanitizer` environment waiting for approval. Nothing has been uploaded
   yet. That pause is where the rehearsal happens.

4. **Rehearse against TestPyPI.**

   ```bash
   python3 tooling/sanitizer/release.py rehearse
   ```

   Equivalently by hand: from the Actions tab, run the Sanitizer Release
   workflow manually and select the tag `sanitizer-v0.3.0` as the ref. A manual
   run routes to TestPyPI and cannot reach PyPI, so there is no field to get
   wrong. It builds from the same tagged bytes, so what lands on TestPyPI is
   what PyPI will receive.

   This happens **while the tag-push run is parked** at the `pypi-sanitizer`
   gate, which only works because the workflow's concurrency group is keyed by
   event as well as ref. A ref-only group put the two runs in contention, and a
   run awaiting approval holds its slot, so the rehearsal queued behind the very
   thing it was supposed to gate (issue
   [#180](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/180)).

   This step is load-bearing, not ceremonial. `twine check --strict` validates
   the metadata it understands; it never asks the server whether the metadata
   version is acceptable. `hatchling` emits `Metadata-Version: 2.5`, and
   Warehouse rejected 2.5 outright until 2026-02-17. The rehearsal is the only
   gate in the chain that catches a server-side rejection, and it catches it
   before a version number is spent.

5. **Verify the rehearsal,** in a clean environment. `release.py rehearse` does
   this for you once the run goes green. By hand:

   ```bash
   python3 -m venv /tmp/rehearsal && /tmp/rehearsal/bin/pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     claude-code-sessions-sanitizer==0.3.0
   /tmp/rehearsal/bin/ccs-sanitize --version     # expect: ccs-sanitize 0.3.0
   mkdir -p /tmp/rehearsal-run && cd /tmp/rehearsal-run
   /tmp/rehearsal/bin/ccs-sanitize --init        # outside any git repo
   ```

   `--extra-index-url` is needed because PyYAML is not on TestPyPI. **Pin the
   version.** Unpinned, pip resolves the highest version across both indexes, so
   a candidate that has not yet propagated to TestPyPI would quietly install the
   previous release from real PyPI and the rehearsal would validate the wrong
   bytes.

   `--init` run outside a git repository is the first-run shape for someone who
   installed from PyPI with no clone: it should write both config files, print
   the gitignore reminder to stderr, and exit 0.

6. **Approve the PyPI deployment.** Back in the parked run from step 3, approve
   the `pypi-sanitizer` environment. The upload happens with a short-lived OIDC
   token and PEP 740 attestations.

   **This step has no `release.py` subcommand, deliberately.** The API to
   approve a deployment exists and is not called. Approval is the one
   irreversible act in the whole sequence, and it is worth keeping in a
   different context, in front of a different screen, from the script that
   pushed the tag.

7. **Verify the real thing,** same shape as step 5 but from PyPI:

   ```bash
   python3 tooling/sanitizer/release.py verify
   ```

   By hand:

   ```bash
   python3 -m venv /tmp/verify && /tmp/verify/bin/pip install claude-code-sessions-sanitizer==0.3.0
   /tmp/verify/bin/ccs-sanitize --version
   mkdir -p /tmp/verify-run && cd /tmp/verify-run && /tmp/verify/bin/ccs-sanitize --init
   ```

   The driver also checks that both the wheel and the sdist published PEP 740
   attestations, and **fails** if either is missing: `sanitizer-release.yml`
   sets `attestations: true` explicitly and anticipates the action's default
   flipping, so absent provenance is a regression rather than a footnote. Check
   the project page renders while you are there.

## Things that will bite you

- **TestPyPI will not take the same version twice.** If a rehearsal fails on
  something that needs a code change, you cannot re-rehearse that version.
  Bump to the next patch version and start over from step 1. Treat a burned
  rehearsal version as normal, not as a mistake to work around.
- **A tag on the wrong commit is silent on GitHub and loud in the workflow.**
  `sanitizer-ci` has no tag trigger, so a tag by itself carries no verified
  status. Any green check you see on a tagged commit belongs to the commit,
  not to the tag. The release workflow re-runs everything for exactly this
  reason. Do not read a green tick as proof.
- **The required reviewer is you.** With a single maintainer holding admin,
  environment approval is a deliberate pause, not independent review. The
  defenses that do not depend on a second person are the OIDC scoping, the 2FA
  on the account, the deployment tag rule, and the attestations. Describe it
  that way rather than as four-eyes.
- **Attestations prove origin, not quality.** A PEP 740 attestation says these
  bytes came out of this workflow in this repo. It says nothing about whether
  the sanitizer scrubs correctly. That claim rests on the test suite, and on
  the honest limits stated in
  [SECURITY.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/SECURITY.md).
- **Bumping the pinned build backend** is a normal PR against
  [`.github/constraints/release-build.txt`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.github/constraints/release-build.txt).
  It is not cosmetic: the backend version determines the artifact's
  `Metadata-Version`, and that is a field the index can reject.

## If a bad release ships

Yank the affected version on PyPI, publish a fixed version, and open a GitHub
Security Advisory. Yank rather than delete, so the version stays installable by
exact pin for anyone reconstructing what happened while dropping out of
dependency resolution. The full policy, including who to tell and in what
order, is
[SECURITY.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/SECURITY.md).
