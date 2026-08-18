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

1. **Bump and document.** Update `__version__` in
   `src/ccs_sanitize/__init__.py` and add the matching `## [x.y.z]` heading to
   [`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md),
   following that file's "bump on any byte-affecting change" policy. The
   release workflow fails closed if either is missing or if they disagree with
   the tag, so a mismatch costs a run, not a version number.

2. **Merge it.** Normal PR, `sanitizer-ci` green.

3. **Tag the merged commit** and push the tag:

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

4. **Rehearse against TestPyPI.** From the Actions tab, run the Sanitizer
   Release workflow manually and select the tag `sanitizer-v0.3.0` as the ref.
   A manual run routes to TestPyPI and cannot reach PyPI, so there is no field
   to get wrong. It builds from the same tagged bytes, so what lands on
   TestPyPI is what PyPI will receive.

   This step is load-bearing, not ceremonial. `twine check --strict` validates
   the metadata it understands; it never asks the server whether the metadata
   version is acceptable. `hatchling` emits `Metadata-Version: 2.5`, and
   Warehouse rejected 2.5 outright until 2026-02-17. The rehearsal is the only
   gate in the chain that catches a server-side rejection, and it catches it
   before a version number is spent.

5. **Verify the rehearsal,** in a clean environment:

   ```bash
   python3 -m venv /tmp/rehearsal && /tmp/rehearsal/bin/pip install \
     --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     claude-code-sessions-sanitizer
   /tmp/rehearsal/bin/ccs-sanitize --version     # expect: ccs-sanitize 0.3.0
   mkdir -p /tmp/rehearsal-run && cd /tmp/rehearsal-run
   /tmp/rehearsal/bin/ccs-sanitize --init        # outside any git repo
   ```

   `--extra-index-url` is needed because PyYAML is not on TestPyPI. `--init`
   run outside a git repository is the first-run shape for someone who
   installed from PyPI with no clone: it should write both config files, print
   the gitignore reminder to stderr, and exit 0.

6. **Approve the PyPI deployment.** Back in the parked run from step 3, approve
   the `pypi-sanitizer` environment. The upload happens with a short-lived OIDC
   token and PEP 740 attestations.

7. **Verify the real thing,** same shape as step 5 but from PyPI:

   ```bash
   python3 -m venv /tmp/verify && /tmp/verify/bin/pip install claude-code-sessions-sanitizer
   /tmp/verify/bin/ccs-sanitize --version
   mkdir -p /tmp/verify-run && cd /tmp/verify-run && /tmp/verify/bin/ccs-sanitize --init
   ```

   Also check the project page renders, and that the release shows its
   attestations on PyPI.

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
