# Plan — Publish `ccs-sanitize` to PyPI

**Status:** Approved 2026-08-15. All §7 decisions ruled; issues filed under `epic:sanitizer-pypi`.
**Author:** PM agent (scoping), amended by the parent thread after verification and sign-off
**Created:** 2026-08-15
**Owner:** Fred Pearce
**Scope of this doc:** the work to take the in-repo sanitizer (`tooling/sanitizer/`,
`claude-code-sessions-sanitizer` v0.2.0) to a first safe public release on PyPI.
**Reverses:** PRD [Decision D-5](prd-sanitizer.md#packaging--in-repo-only-for-v0)
("in-repo only for v0; not published to PyPI") and `roadmap-v0.md:178`.

The issue breakdown is in §6; the decisions and their rulings are in §7.

---

## 1. Why now (the trigger)

D-5 deferred publishing "until a standalone audience materializes." The probable
audience is the **CCDC initiative** (public sanitized Claude Code session corpus,
issue #75, docs in the separate `claude-code-data-collective` repo). External
contributors to a public corpus need a `pip install`-able scrubber; telling them to
clone this monorepo and run an in-tree tool is a much higher barrier and a worse
security story (people improvise their own scrubbing when the sanctioned tool is
inconvenient).

**Confirmed 2026-08-15 (Decision Q1): CCDC contributors are the audience.** That is the
trigger the PRD amendment should cite.

A second consequence follows from *who* uses a scrubber. Anyone evaluating this tool is,
by definition, deciding whether to trust it with data they cannot afford to leak. They
will want to verify the claim before relying on it, and some will want to fork it and
adapt the rules to their own environment rather than run it as shipped. Both behaviors
are healthy and should be designed for, and both raise the bar on things that are easy
to treat as optional: signed provenance, an explicit and quotable stability contract, an
honest statement of what the tool does *not* catch, and configuration documented well
enough that a fork is a fifteen-minute job rather than a code-reading exercise. This is
the reason issue F is promoted from "Should" to a hard blocker in §5.

Reversing D-5 is itself a work item. The PRD is canonical ("where it differs from
the package READMEs, the PRD wins"), so the reversal must be a **dated amendment
that records what changed and why**, not a silent override. That is issue A.

---

## 2. Framing: this is a security tool, so publishing is a supply-chain event

The dominant risk is not "the package fails to install." It is: **a compromised or
malformed release ships a sanitizer that appears to work and silently under-scrubs**,
and every user of that release is by definition handling raw session data that
contains secrets. A bad `ccs-sanitize` release leaks other people's credentials.

That reframes the whole plan. The packaging-correctness items (§ issue C) are table
stakes. The parts that actually matter are:

- **Provenance of the artifact** (nobody but the release workflow can publish).
- **Integrity of what goes into the artifact** (tests green on the exact commit that
  is published; the residual-scan security floor is exercised in CI).
- **A public, load-bearing determinism/version contract** that strangers can gate on.
- **A disclosure path** for when someone finds a scrubbing hole.

The MoSCoW split in §5 and the sequencing in §8 are driven by that framing, not by
packaging mechanics.

---

## 3. Current state (verified 2026-08-15)

**Good — already done:**

- `tooling/sanitizer/pyproject.toml` is a working hatchling build: src layout under
  `src/ccs_sanitize/`, console script `ccs-sanitize = "ccs_sanitize.cli:main"`,
  `dynamic = ["version"]` from `src/ccs_sanitize/__init__.py` (currently `0.2.0`),
  `requires-python = ">=3.11"`, runtime dep `PyYAML>=6`, dev extra `pytest>=8`,
  classifiers + project URLs populated, explicit wheel + sdist targets.
- 13 pytest modules under `tooling/sanitizer/tests/`; the security-critical paths
  (residual scan, fail-closed, sidecar-never-leaks, pattern-sync) are covered.
- Both PyPI names `claude-code-sessions-sanitizer` and `ccs-sanitize` are unclaimed
  (both 404 on 2026-08-15).
- Repo root has `LICENSE` (MIT, "Copyright (c) 2026 Frederick Douglas Pearce") and
  `LICENSE-prose.md`.

**Gaps that block or shadow a first publish:**

1. **License metadata is the deprecated pre-PEP-639 form** (`license = { text = "MIT" }`)
   and **no license file is shipped in the sdist/wheel**. A published security tool with
   no LICENSE in the artifact is a real compliance gap.
2. **README will render broken on PyPI.** It uses repo-relative links
   (`../../.claude/specs/prd-sanitizer.md`, `tests/`, `CHANGELOG.md`) that resolve to
   nothing for a pip user who never cloned the repo. `long_description_content_type` is
   not pinned. (In-page `#anchor` links are fine on PyPI; the `../../` and bare-path
   links are the problem.)
4. **No Python CI at all.** `.github/workflows/` has only `og-card-guard.yml`,
   `pages-sync.yml`, `prettier.yml`. Nothing runs pytest, builds the wheel, or runs
   `twine check`. There is no test matrix and no release workflow.
5. **The version to publish is ambiguous.** `__init__.py` says `0.2.0`, but the
   CHANGELOG has a populated **`[Unreleased]`** section (issues #45, #26, #38: `--init`,
   the gitignore guard, the I-3 leak-guard extension) sitting on top of `0.2.0`. You
   cannot publish `[Unreleased]`. A version must be cut first.
6. **No SECURITY.md / disclosure path** anywhere in the repo.
7. **The §4 free-text limitation is stated in the PRD but not loudly in the README.**
   To this repo's own author, "prompts and outputs are not scrubbed for arbitrary PII"
   is understood. To a stranger who `pip install`s a thing called "sanitizer," it must
   be stated loudly, or the tool over-promises.

**Deliberately fine to leave as-is (non-issues):**

- The vendored Tier-1 secret-pattern duplication between the sanitizer and
  `.claude/hooks/` is guarded by `test_secret_patterns_in_sync.py`. Publishing does
  **not** force resolving it. See issue G / Decision Q5.
- `requires-python = ">=3.11"`, the dependency surface (stdlib + PyYAML), and the src
  layout are all publish-ready.

---

## 4. Areas worked through

### 4.1 Supply-chain security (highest stakes) — issues B1, B2

**Recommendation: PyPI Trusted Publishing (OIDC), no long-lived API token.**

- **Trusted Publishing over API tokens.** A long-lived `PYPI_API_TOKEN` in repo
  secrets is a standing credential that, if leaked, lets an attacker publish a
  poisoned sanitizer. Trusted Publishing (OIDC) mints a short-lived token per run,
  scoped to this repo + workflow + environment, with nothing at rest to steal.
  For a security tool this is the correct default, not a nice-to-have.
- **Tag-triggered, environment-gated release workflow.** The publish job triggers only
  on a version tag (`v*`), runs in a GitHub Environment (`pypi`) that has a required
  reviewer, and depends on the test-matrix job passing on that exact ref. So a publish
  requires: a signed-off-able tag + green tests + a human approving the environment.
  No path publishes from an arbitrary branch or a red build.
- **Build provenance / attestations.** `pypa/gh-action-pypi-publish` emits PEP 740
  attestations by default under Trusted Publishing. Keep that on; it is free provenance
  and exactly the "prove this artifact came from this workflow" property this tool wants.
- **2FA** on the PyPI account is a hard prerequisite (PyPI now requires it), and the
  project should be created with Trusted Publishing configured before the first upload
  (or use PyPI's "pending publisher" flow so the first upload itself is OIDC, never a
  manual token upload).
- **Compromise response** (document in SECURITY.md, issue F): if a bad release ships,
  the play is `yank` the affected version on PyPI (keeps it installable by exact pin for
  forensics but removes it from resolution), publish a fixed version, and post an
  advisory via the GitHub Security Advisory path. Deletion is not the tool; yank is.

### 4.2 Packaging correctness — issue C

- **PEP 639:** switch to `license = "MIT"` (SPDX expression) and
  `license-files = ["LICENSE"]` so the artifact carries the license. Drop the
  deprecated `License ::` classifier once the SPDX field is in (PEP 639 makes the
  classifier redundant and setuptools/hatchling will warn on the mix).
- **Ship LICENSE:** hatchling picks up `license-files` into wheel + sdist metadata.
  Confirm LICENSE appears in both artifacts.
- **README links:** rewrite every repo-relative link to an absolute
  `https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/...`
  URL so the PyPI project page renders correctly. Pin
  `long_description_content_type = "text/markdown"` (hatchling infers from the `.md`
  extension, but pin it to be explicit and future-proof).
- **`tests/` in the sdist:** currently included. **Recommendation: keep them in the
  sdist** (they document the security guarantees and let a downstream packager or a
  security auditor re-run the fail-closed suite against the exact published source),
  **but exclude them from the wheel** (already the case — the wheel target is
  `packages = ["src/ccs_sanitize"]`). Low stakes either way; the only cost of shipping
  tests in the sdist is a slightly larger tarball.
- **Local gate:** `python -m build` + `twine check --strict` must pass. This becomes a
  CI step (issue B1), not just a local habit.

### 4.3 CI — issue B1

No Python CI exists. Add a workflow that, on PR and push touching
`tooling/sanitizer/**`, runs the pytest suite on a **3.11 / 3.12 / 3.13** matrix, plus
`python -m build` and `twine check --strict`. This is the always-on gate; the release
workflow (B2) depends on it. Note the repo convention: anything under `.github/` or
`tooling/` requires a PR, so all of this lands via PR.

### 4.4 First-run UX for a pip user with no clone — issue D (mostly already solved)

This section was scoped as an open design question. Reading the implementation
(`cli.py` `_check_config_gitignored`, lines 336-442) and the shipped template closes
both halves of it. **Decision Q4 is largely moot.** Verified 2026-08-15.

**The non-repo path already degrades correctly.** The guard's behavior table is
explicit, and the code matches it:

| Condition | Behavior |
|---|---|
| Config file absent | Skip silently; `load_config` raises the accurate error instead |
| `git` not on PATH | Warn to stderr, proceed |
| `check-ignore` exit 0 (ignored) | Proceed silently |
| `check-ignore` exit 1 (not ignored) | `ConfigError` -> **exit 3** |
| Any other exit, incl. 128 = not a repo | Warn to stderr, proceed |

So exit 3 fires **only** when the user is inside a git repo and the config is not
ignored, which is exactly the `git add .` threat and nothing else. A pip user scrubbing
in a scratch directory gets a one-line warning and their scrub runs. That is the right
design, and it was reached deliberately rather than by accident: the guard also scrubs
ambient `GIT_*` env vars so a wrapper's `GIT_DIR` cannot redirect the check, and it
passes the bare basename with `cwd` set to the config's unresolved parent so a
symlinked-in config is checked against the repo the user actually stages in, not the
symlink target's repo.

**The template is already generic.** `_templates/ccs-sanitize.example.yaml` ships
placeholder rules only (`/home/REAL_USERNAME`, `real.author@example.com`,
`real-github-handle`, `Real Name`), with no `-home-fdpearce-` slug and no repo-specific
paths. A stranger's `--init` seeds obviously-fill-me-in values, which is the desired
shape. The CHANGELOG confirms this was designed for extraction: the template is package
data read via `importlib.resources` specifically so the single source of truth
"survives `pip install` and eventual extraction from the monorepo."

**What actually remains is a stale-message bug, not a design question.** The exit-3
error text advises passing `--no-check` for "CI environments without a `.git` directory
only" (`cli.py:428`), but a directory without `.git` cannot produce exit 3 in the first
place; it takes the warn-and-proceed branch. The advice names a scenario that cannot
reach the message. `CLAUDE.md` repeats the same stale framing. For a stranger hitting
exit 3, the correct instruction is "add it to `.gitignore`," and `--no-check` should be
described as the deliberate-override escape hatch it actually is.

Issue **D** therefore shrinks from a `feat` with an open design question to a small
`fix(sanitizer)`: correct the exit-3 message and the `--help` text for `--no-check`, and
correct the matching sentence in `CLAUDE.md`. It stays a fast-follow rather than a
blocker, but it is now cheap enough to fold into the first release.

### 4.5 Version, release, and the public determinism contract — issue E

The CHANGELOG bump policy exists because the sidecar's `sanitizer_version` is what
downstream consumers gate on: "same input + same config → byte-identical output" holds
only **within** a version. Publishing makes that contract public and load-bearing for
strangers (the planned fixture-validator, AgentFluent, CodeFluent, and now external
CCDC contributors).

Implications to scope:

- **Cut a real version.** The `[Unreleased]` section must become a dated release
  heading before publish. **Recommendation: first public version is `0.3.0`** (not
  `0.2.0`, which is already claimed by unreleased-then-superseded state, and not
  `1.0.0`). Rationale: the package is `Development Status :: 3 - Alpha`; the CLI surface
  and template may still move (see issue D); `1.0.0` signals a stability guarantee that
  is premature. `0.3.0` cleanly packages the `[Unreleased]` `--init`/guard/leak-guard
  work as the first public cut. (Decision Q2.)
- **Make the bump policy externally-facing.** Today it lives in the CHANGELOG head as
  an internal note. For public consumers it needs to be a short, quotable **stability /
  versioning policy**: what a PATCH/MINOR/MAJOR means for the determinism contract, and
  the explicit statement that **byte-stability is only promised within a version** so
  consumers must record the `sanitizer_version` they scrubbed under. This can live in
  the README (a "Stability and the determinism contract" section) linking to the
  CHANGELOG for detail.
- **Deprecation policy.** State plainly that a MAJOR bump may require re-running the
  sanitizer on previously scrubbed sessions, and that old versions are yanked only for
  security reasons, not for routine supersession.

### 4.6 Vendored secret patterns — issue G

**Recommendation: defer. Publishing does not force this.** The `.claude/hooks/` copy is
not shipped in the package; only the sanitizer's `rules/secrets.py` copy is. The
in-repo `test_secret_patterns_in_sync.py` keeps the two Tier-1 copies element-wise
identical, so the published artifact cannot silently drift below the hook's floor
without a red test in this repo. The §17 "shared secret-pattern source" cleanup remains
future work and is orthogonal to the publish. File a short decision issue (G) recording
"defer, in-sync test holds" so the question is closed rather than left dangling, or fold
it into the PRD amendment (A). (Decision Q5, recommendation = defer.)

### 4.7 Naming and discoverability — folded into issue A

**Recommendation: keep the distribution name `claude-code-sessions-sanitizer`.** It is
descriptive, clearly namespaced to this project family, and searchable. The console
script stays `ccs-sanitize` (short, already the entry point). Renaming the distribution
is cheap now and breaking later, but there is no strong reason to rename: the long name
is a feature for discoverability, not a bug.

**Optional, cheap, defensive:** reserve `ccs-sanitize` as a PyPI project name too
(publish a stub or a same-content alias) so a squatter cannot claim the obvious short
name and ship a lookalike. Low effort, real supply-chain value. Flag as Decision Q3;
recommendation = keep long name, optionally reserve the short one.

### 4.8 Post-publication burden — issue F

- **SECURITY.md + disclosure path.** The repo has none. A security tool must tell people
  where to report a scrubbing hole (private disclosure via GitHub Security Advisories,
  not a public issue that broadcasts the bypass). This should exist **before** the first
  publish.
- **Loud limitation notice.** Surface the PRD §4 free-text limitation at the top of the
  README and on the PyPI page: **this tool reduces risk, it does not guarantee zero
  leakage; free-text prompts and tool output are not scrubbed for arbitrary PII; human
  review of the sidecar is still required.** This matters far more to a stranger than to
  the repo author.
- **Issue triage.** External issues will arrive. No new process needed for v1 beyond the
  disclosure path; note it as an accepted ongoing cost.

---

## 5. Prioritization (MoSCoW, relative to the first `twine upload`)

**Must (hard blockers on the first upload):**

- A — PRD amendment reversing D-5 (the mandate; nothing should ship without it).
- C — packaging correctness (license metadata + shipped LICENSE + PyPI-safe README).
- E — cut the first public version + public determinism/stability policy.
- B1 — Python CI (tests must be green on the published ref).
- B2 — Trusted Publishing release workflow (the only sanctioned upload path).

- F — SECURITY.md + loud limitation notice. **Promoted from "Should" to "Must" on
  2026-08-15.** The asymmetry decides it: if this ships without an honest statement of
  the §4 free-text gap, the person who gets hurt is a stranger who trusted the word
  "sanitizer," not the author who already knows the limitation. A security tool with no
  disclosure path is also a gap the first time somebody finds a hole, and the absence
  reads as a maturity signal to anyone evaluating the tool.

**Could (fast-follow; can land after v1 with a documented caveat):**

- D — correct the stale exit-3 message and the matching `CLAUDE.md` sentence.
- G — record the "defer secret-pattern dedup" decision.
- H — defensive reservation of the `ccs-sanitize` PyPI name (Q3, approved).

**Won't (explicitly out of scope for this initiative):**

- Collapsing the vendored secret-pattern duplication (PRD §17; the in-sync test holds).
- Jitter / session-bundle mode (PRD §9b, v1 feature work, unrelated to publishing).
- Signing beyond the automatic PEP 740 attestations Trusted Publishing provides.
- Publishing to any index other than PyPI (no TestPyPI-as-a-product; TestPyPI is fine as
  a rehearsal target inside B2).

---

## 6. Proposed issue breakdown

Filed 2026-08-15 under the new epic label **`epic:sanitizer-pypi`**.

| Plan ID | Issue | Title | Priority | Blocker on first upload |
|---|---|---|---|---|
| A | [#158](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/158) | amend PRD to reverse D-5 and mandate PyPI publish | high | Must (gates all) |
| C | [#159](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/159) | make packaging PyPI-correct | high | Must |
| E | [#160](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/160) | cut `0.3.0` + publish the determinism contract | high | Must |
| F | [#161](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/161) | SECURITY.md + limitation notice | high | Must |
| B1 | [#162](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/162) | Python test matrix + build/twine-check | high | Must |
| B2 | [#163](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/163) | Trusted-Publishing release workflow | high | Must (performs the upload) |
| D | [#164](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/164) | stale exit-3 message | high | **Must** (promoted 2026-08-15, see §9) |
| G | [#165](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/165) | record the dedup deferral | low | fast-follow |
| H | [#166](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/166) | reserve `ccs-sanitize` on PyPI | low | fast-follow |

Titles below are conventional-commit style and match the filed issues.

### A — `chore(specs): amend PRD to reverse D-5 and mandate PyPI publish`
- **Labels:** `documentation`, `epic:sanitizer-pypi`, `priority:high`
- **Depends on:** nothing (this is the mandate; everything else depends on it)
- **Acceptance criteria:**
  - PRD §12 D-5 gains a **dated amendment** entry (do not rewrite the original decision;
    add a superseding note) recording the reversal, the CCDC-audience justification, and
    a link to this plan.
  - PRD §18 decision-history table gets a 2026-08-15 row.
  - `roadmap-v0.md:178` non-goal is annotated as superseded with a pointer to the
    amendment.
  - The naming decision (Q3) and first-version decision (Q2) are recorded in the PRD once
    the human rules on them.
  - The secret-pattern-dedup deferral (Q5) is recorded here or in issue G, not left open.

### B1 — `chore(ci): add Python test matrix + build/twine-check for the sanitizer`
- **Labels:** `enhancement`, `epic:sanitizer-pypi`, `priority:high`
- **Depends on:** A
- **Acceptance criteria:**
  - Workflow runs the `tooling/sanitizer/` pytest suite on Python 3.11, 3.12, 3.13.
  - Triggers on PRs and pushes that touch `tooling/sanitizer/**`.
  - Runs `python -m build` and `twine check --strict` on the built artifacts; job fails
    if either does.
  - The security-critical tests (residual scan, fail-closed, pattern-sync,
    sidecar-never-leaks) run in the matrix, not just locally.
  - Lands via PR (repo convention for `.github/`).

### B2 — `chore(ci): add Trusted-Publishing release workflow (tag + environment gated)`
- **Labels:** `enhancement`, `epic:sanitizer-pypi`, `priority:high`
- **Depends on:** B1, C, E
- **Acceptance criteria:**
  - Publish job uses PyPI **Trusted Publishing (OIDC)**; no long-lived API token is
    stored in repo secrets.
  - Triggers only on a version tag and runs in a protected GitHub Environment
    (`pypi`) with a required reviewer. **Note: the repo has zero git tags today**
    (verified 2026-08-15), so the tagging convention is being invented here, not
    inherited. Use a component-scoped prefix (`sanitizer-v0.3.0`), not a bare `v*`:
    this is a monorepo holding posts, reference docs, and three tools, and a bare
    `v*` filter would fire the publish job on any future repo-level or Pages tag.
  - Depends on the B1 matrix passing on the tagged ref; a red build cannot publish.
  - PEP 740 attestations are emitted (default of `gh-action-pypi-publish`).
  - A rehearsal path against TestPyPI is documented or wired (dry run before the real
    first upload).
  - PyPI project is created with a pending/configured Trusted Publisher so the **first**
    upload is OIDC, never a manual token upload.

### C — `fix(sanitizer): make packaging PyPI-correct (PEP 639 license, README links)`
- **Labels:** `bug`, `epic:sanitizer-pypi`, `priority:high`
- **Depends on:** A
- **Acceptance criteria:**
  - `pyproject.toml` uses `license = "MIT"` (SPDX) + `license-files = ["LICENSE"]`; the
    deprecated `license = { text = ... }` form and redundant `License ::` classifier are
    removed.
  - `python -m build` produces a wheel and sdist that both contain LICENSE.
  - Every repo-relative link in `tooling/sanitizer/README.md` becomes an absolute
    `github.com/.../blob/main/...` URL; the rendered PyPI page has no broken links.
  - `long_description_content_type = "text/markdown"` is pinned.
  - `twine check --strict` passes on both artifacts.
  - Decision on `tests/` in sdist recorded (recommendation: keep in sdist, exclude from
    wheel — already the wheel behavior).

### E — `chore(sanitizer): cut first public version + publish the determinism contract`
- **Labels:** `documentation`, `epic:sanitizer-pypi`, `priority:high`
- **Depends on:** A
- **Acceptance criteria:**
  - The CHANGELOG `[Unreleased]` section is cut to a dated release heading at the agreed
    first public version (recommendation: `0.3.0`); `__init__.py` matches.
  - README gains a "Stability and the determinism contract" section stating byte-
    stability holds **only within a version** and consumers must record the
    `sanitizer_version` they scrubbed under.
  - The PATCH/MINOR/MAJOR bump policy is restated in externally-facing terms (currently
    an internal CHANGELOG note).
  - A deprecation statement is included (MAJOR may require re-scrubbing; old versions
    yanked only for security).

### F — `docs: add SECURITY.md and a loud "reduces risk, not zero leakage" notice`
- **Labels:** `documentation`, `epic:sanitizer-pypi`, `priority:high`
- **Depends on:** A
- **Acceptance criteria:**
  - Repo has a `SECURITY.md` with a private disclosure path (GitHub Security Advisories),
    a scope statement, and the yank-and-advisory compromise-response play.
  - The sanitizer README opens with a prominent limitation notice: reduces risk, does not
    guarantee zero leakage; free-text prompts/outputs are not scrubbed for arbitrary PII;
    sidecar review is still required (surfacing PRD §4).
  - The notice also renders at the top of the PyPI project description.

### D — `fix(sanitizer): exit-3 message advises --no-check for a case that cannot reach it`
- **Labels:** `bug`, `epic:sanitizer-pypi`, `priority:low`
- **Depends on:** A
- **Rescoped 2026-08-15.** Originally a `feat` with an open design question. Reading
  `cli.py:336-442` and the shipped template showed the non-repo path already
  warns-and-proceeds correctly and the template is already generic (see §4.4), so only
  a stale message remains. No behavior change, so no version bump is required.
- **Acceptance criteria:**
  - The exit-3 `ConfigError` text stops advising `--no-check` for "CI environments
    without a `.git` directory," since that case takes the warn-and-proceed branch and
    cannot produce exit 3. It instead leads with "add it to `.gitignore`" and describes
    `--no-check` as a deliberate override.
  - The `--no-check` `--help` text (`cli.py:165`) is corrected to match.
  - The matching sentence in `CLAUDE.md` ("use `--no-check` only in CI environments
    without a `.git` directory") is corrected.
  - A short "first run without a clone" section is added to the README, stating plainly
    that outside a git repo the guard warns and the scrub proceeds.
  - No behavior change: existing `test_init_and_check.py` cases still pass unmodified,
    and any message assertion is updated in the same commit.

### G — `research: record decision to defer secret-pattern dedup for publish`
- **Labels:** `research`, `epic:sanitizer-pypi`, `priority:low`
- **Depends on:** A (or folded into A)
- **Acceptance criteria:**
  - A short written decision records that publishing does **not** force collapsing the
    vendored Tier-1 duplication, because the shipped artifact carries only the
    sanitizer's copy and `test_secret_patterns_in_sync.py` guards drift.
  - PRD §17 "shared secret-pattern source" is annotated as still-future, not blocked by
    publish.
  - Closes the dangling question rather than leaving it implicit.

### H — `chore(sanitizer): defensively reserve the ccs-sanitize name on PyPI`
- **Labels:** `enhancement`, `epic:sanitizer-pypi`, `priority:low`
- **Depends on:** B2 (do the real project first; this is a placeholder, not a product)
- **Added 2026-08-15** per the Q3 ruling.
- **Acceptance criteria:**
  - `ccs-sanitize` is claimed on PyPI as a reserved placeholder so a squatter cannot
    ship a lookalike under the name users actually type.
  - The placeholder's description states plainly that it is a name reservation, is not
    the package to install, and points at `claude-code-sessions-sanitizer`.
  - The placeholder does **not** install a `ccs-sanitize` console script. Two
    distributions competing for the same entry-point name would shadow each other
    depending on install order, which is exactly the confusion this is meant to prevent.
  - The reservation is noted in the plan and the PRD amendment so a future maintainer
    knows the second name is deliberate and inert.

---

## 7. Decisions (ruled 2026-08-15)

| # | Decision | Ruling |
|---|---|---|
| Q1 | Is the standalone audience CCDC (issue #75) contributors? | **Yes.** CCDC contributors are the audience of record. Cite this in the PRD amendment. |
| Q2 | First public version: `0.3.0` vs `1.0.0`? | **`0.3.0`.** Alpha; the CLI surface may still move; `1.0.0` would over-promise against a determinism contract that only holds within a version. |
| Q3 | Distribution name: keep `claude-code-sessions-sanitizer`? Reserve `ccs-sanitize` defensively? | **Keep the long name, and reserve `ccs-sanitize`.** The reservation becomes issue H. |
| Q4 | ~~Non-repo first-run UX: distinct calm message for no-`.git`, and generic template?~~ | **Closed 2026-08-15, no ruling needed.** Verified against `cli.py:336-442` and the shipped template: the non-repo path already warns and proceeds, and the template is already generic. Only a stale error message remains (issue D, now a low-priority `fix`). See §4.4. |
| Q5 | Force the secret-pattern dedup now, or defer? | **Defer.** The in-sync test holds and the hook copy is not shipped. Recorded as issue G. |
| Q6 | New epic label `epic:sanitizer-pypi`, or file under existing `epic:sanitizer` (#1)? | **New label.** A coherent multi-issue initiative, distinct from epic #1 whose v0 implementation scope is complete. |
| Q7 | Trusted Publishing (OIDC) vs API token? | **Trusted Publishing.** No standing credential to leak. Taken as settled, not a genuine trade-off for a tool in this category. |

### Still open (not blocking the filed issues)

| # | Question | Recommendation |
|---|---|---|
| Q8 | Is the supported public surface the **CLI only**, or is there also a documented **library API** (importing `ccs_sanitize` and calling the pipeline in-process)? | **CLI only for `0.3.0`, stated explicitly.** Someone adapting this to their own environment may well want to embed it rather than shell out, and today nothing says whether `orchestrator`/`pipeline` are public or internal. Silence is the worst answer: it invites imports against internals that are then expensive to change. Declare the CLI and the sidecar format as the supported contract for now, note the module surface is private and may move, and revisit if anyone actually asks. Cheap to state, expensive to retrofit. |

---

## 8. Sequencing and the minimum viable safe publish

**Minimum viable safe publish** (all "Must", F now included):

```
A (mandate / PRD amendment)
├── C  (packaging correctness)
├── E  (version cut + public contract)
├── F  (SECURITY.md + limitation notice)   [Must as of 2026-08-15]
└── B1 (Python CI: tests green on the ref)
        └── B2 (Trusted-Publishing release workflow)  ── first `twine upload`
                └── H (reserve the ccs-sanitize name)   [fast-follow]
```

- **A first.** It is the mandate and it unblocks everything; also settles Q2/Q3/Q5,
  which C, E, and G consume.
- **C, E, F in parallel** after A. They touch different surfaces (pyproject/README,
  CHANGELOG/version, SECURITY.md) and do not conflict.
- **B1 before B2.** The release workflow must depend on a green matrix.
- **B2 last.** It performs the actual upload and depends on C (correct artifact), E
  (real version), and B1 (green tests). Rehearse against TestPyPI inside B2 before the
  real tag.

**Can land after the first publish (fast-follow):**

- **G** — a paperwork decision; close it whenever, not on the critical path.
- **H** — defensive `ccs-sanitize` name reservation, anytime after B2.

**Do not publish until:** A, C, E, F, and D are merged, B1 is green on the release ref,
and B2 is wired with Trusted Publishing.

---

## 9. Architecture review (2026-08-15)

Reviewed by the architect agent before implementation began. Verdict: **no structural
objections.** Sequencing is correct, declared dependencies match reality, and the
supply-chain framing was judged proportionate rather than inflated. The over-engineering
check came back clean, with one note: the `pypi` environment's required reviewer on a
solo-maintainer repo is a human checkpoint rather than peer review, and should be
documented as such rather than trimmed.

Findings applied to the issues:

| Finding | Applied to |
|---|---|
| Cross-interpreter byte-identity is untested. All existing determinism tests run twice on one interpreter; nothing asserts 3.11/3.12/3.13 agree. Needs a committed golden fixture asserted in every matrix cell. | #162, #160 |
| **#164 was scheduled on the wrong axis.** Promoted to a first-release blocker. | #164 |
| README sidecar example contradicts PRD §10 (`input_hash` vs `input_sha256`, wrong storage claim); README inverts the provenance of the secret-pattern floor; "not yet published" goes stale on upload. | #159 |
| Version-lifecycle policy was split across two issues. SECURITY.md owns lifecycle; README owns the determinism contract. | #160, #161 |
| `config_source` basename-safety was reasoned against this repo's naming. A custom `-c acme-prod.yaml` lands verbatim in a supposedly-safe-to-commit sidecar. Document, do not engineer around it. | #161 |
| Sanitized fixtures pin to their scrub-time version. The future fixture-validator's "recognized version" must mean a maintained allowlist. | #160 |

### Why #164 moved

I scheduled it as a fast-follow because it changes no output bytes and needs no version
bump. That is the correct test for the CHANGELOG policy and the wrong test for a security
tool's first public release. Both the exit-3 message and the `--no-check` help advertise
a flag that disables the gitignore guard, to a user who has just hit an error they do not
yet understand. The question that should have decided it is whether shipped text steers a
stranger toward turning off a safety control.

### Forward compatibility

Publishing `0.3.0` does not constrain the deferred PRD §17 work. Jitter evolves the
sidecar's `jitter` scalar into a structured value, which the schema-version decision
below is the clean seam for. Session-bundle mode (`--session-dir`) is additive to the CLI
and MINOR under the stated policy. Q8 (CLI-only contract, modules private) was affirmed:
the fork-and-customize path is served by YAML config and additive `extra_secret_patterns`,
which is data rather than code, so no consumer needs to import `orchestrator` or
`pipeline` in-process.

### Q9 — open, needs a ruling before #160 is worked

Should the sidecar carry a `sidecar_schema_version` independent of `sanitizer_version`?
Today it does not, so the tool version doubles as the schema key and consumers must map
versions to shapes. **Recommendation: add `sidecar_schema_version: 1` at `0.3.0`.** The
asymmetry decides it: added now, every public-era sidecar carries it; added at `0.4.0`,
consumers handle its absence forever. Recorded as an open decision in #160.
