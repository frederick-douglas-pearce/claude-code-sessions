# sanitizer/

CLI tool that scrubs raw Claude Code session JSONL files for safe publication.

> ### Read this before you trust it
>
> **This tool reduces the risk of disclosure. It does not guarantee zero leakage.**
>
> - It catches **structured** leaks: filesystem paths, the identifiers you configure
>   (name, email, usernames, hostnames, project slugs), and secrets that match a known
>   pattern library.
> - It does **not** read prose. **Free-text prompts and tool output are not scrubbed for
>   arbitrary PII.** "My name is Jane and I work at AcmeCorp", typed into a prompt, comes
>   through the sanitizer untouched, because no rule describes it.
> - **Human review is still required.** Read the `.scrubbed` sidecar, and read the scrubbed
>   file, before publishing anything. The sidecar exists to make that review possible, not
>   to replace it.
> - If you point `-c` at a config of your own, **its filename is recorded verbatim** in the
>   sidecar (`config_source`, basename only). `acme-prod.yaml` or `jsmith-laptop.yaml` puts
>   your employer or your name into the one file the docs call safe to commit, and no rule
>   will catch it, because it is not in your match list. Name config files generically.
>
> The full statement of this limitation is [PRD §4](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#4-non-goals).
> To report a scrubbing hole, use the private channel in
> [SECURITY.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/SECURITY.md),
> not a public issue.

**Status:** Implemented and in use. All transform layers (path → identifier → secret-pattern, with the statistical-jitter stub) ship behind the `ccs-sanitize` CLI, covered by the `pytest` suite under [`tests/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/sanitizer/tests). See [`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md) for release history and the current version.

**Design:** [`prd-sanitizer.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md) is the canonical
design. Where this README differs from the PRD, the PRD wins. The PRD is kept current;
this README is a high-level pointer.

## Design goals

- **Standalone CLI** — usable independent of any sibling project, and installable on its own from PyPI
- **Layered rules** — path scrub → identifier scrub → secret-pattern scrub → optional statistical jitter
- **Versioned output** — every scrubbed file carries the sanitizer version in its `.scrubbed` sidecar; downstream consumers can trust or distrust by version
- **Testable** — bad scrubs fail tests, not slip through to publication. Known-bad input fixtures drive the test suite.
- **Fail-closed** — if any rule errors, the file is not produced. No partial scrubs.
- **No silent transforms** — the `.scrubbed` sidecar enumerates every substitution made, so a reviewer can audit

## Layout

```
sanitizer/
├── pyproject.toml          # entry point: ccs-sanitize
├── LICENSE                 # verbatim copy of the repo-root LICENSE, shipped in the artifacts
├── CHANGELOG.md
├── src/
│   └── ccs_sanitize/
│       ├── __init__.py     # __version__
│       ├── cli.py          # argument parsing, --init, --no-check
│       ├── config.py       # resolve + validate the .ccs-sanitize.yaml rule set
│       ├── orchestrator.py # fail-closed driver: scrub or produce nothing
│       ├── pipeline.py     # per-line transform pipeline
│       ├── residual.py     # post-scrub residual-leak scans (secrets + rules)
│       ├── sidecar.py      # emit the .scrubbed audit sidecar
│       ├── subtable.py     # substitution bookkeeping
│       ├── rules/
│       │   ├── _engine.py
│       │   ├── paths.py
│       │   ├── identifiers.py
│       │   ├── secrets.py
│       │   └── jitter.py   # statistical jitter (stub for v0)
│       └── _templates/     # --init config templates
└── tests/                  # pytest suite — one module per rule + orchestration
    └── golden/             # committed cross-interpreter determinism artifact
```

## Install

```bash
pip install claude-code-sessions-sanitizer   # installs the `ccs-sanitize` console script
```

The distribution is `claude-code-sessions-sanitizer`; the command it installs is
`ccs-sanitize`. `0.3.0` is the first public release.

**There is no `ccs-sanitize` distribution on PyPI, and this project does not publish one.**
`ccs-sanitize` is a console script, not a package name. If you find a PyPI project under that
name, it is not this tool, whatever its description claims. The short name is left unclaimed
deliberately rather than by oversight; the reasoning is
[D-9](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#decision-d-9--ccs-sanitize-is-deliberately-not-reserved-on-pypi).
Install by the long name, or from this repository.

The supported public surface is the **CLI** and the **`.scrubbed` sidecar format**. The
Python module surface (`orchestrator`, `pipeline`, `rules`, …) is private and may change
without a MAJOR bump. Customization is meant to happen through the YAML config and
additive `extra_secret_patterns`, which is data rather than code.

## Rule sources

- **Path/identifier scrubbing** — bespoke to this project; rules configurable per-project via a yaml file
- **Secret-pattern detection** — the pattern library lives here, in
  [`rules/secrets.py`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/src/ccs_sanitize/rules/secrets.py)
  (Anthropic API keys, GitHub PATs, AWS keys, Google API keys, PEM blocks, etc.). That
  copy is the one that ships in this package. This repo is upstream of
  [AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent), whose
  `detect_secrets_in_output.py` hook is a peer consumer of the same Tier-1 set, not its
  source; a sync test in this repo keeps the two element-wise identical so the shipped
  artifact cannot drift below the hook's floor. See
  [PRD D-6](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#decision-d-6--vendor-the-secret-pattern-library).
  Config may **add** patterns via `extra_secret_patterns`; it can never remove a built-in.

## Sidecar format

Every scrubbed output file gets a `<filename>.scrubbed` sidecar. It is an audit record,
not a second copy of the data: it names the *kind* of thing that changed and how often,
and never records an original value. Secrets contribute a count only.

```yaml
sidecar_schema_version: 1 # the shape of THIS document; see the stability section below
sanitizer_version: <version> # the version that produced this file; consumers gate on it
scrubbed_at: 2026-05-31T18:30:00Z
input_filename: real-subagent-trace.jsonl # basename only, never the full path
input_sha256: 9f2c... # one-way hash of the raw input; the hash is stored, the input is not
config_version: 1
config_source: .ccs-sanitize.yaml # basename only
lines_processed: 512 # survivors + stripped + blank lines
stripped_lines: # whole lines dropped by --strip-types
  file-history-snapshot: 8
  attachment: 1
rules_applied:
  paths: { substitutions: 14, distinct: 3 }
  identifiers: { substitutions: 6, distinct: 2 }
  secrets: { matches: 2 } # COUNT ONLY, never the matched bytes
  jitter: disabled
substitutions: # placeholder + replacement, never the original
  - { rule: paths, placeholder: "<home-dir>", replacement: "/home/user", occurrences: 9 }
  - { rule: identifiers, placeholder: "<email>", replacement: "user@example.com", occurrences: 6 }
residual_scan: clean # post-scrub re-scans: secret patterns (position-agnostic
                     # over the serialized output), the LITERAL paths/identifiers
                     # rules (decoded output, position-agnostic, keys included,
                     # #195), AND the REGEX ones at reachable VALUE positions
                     # (#198 -- NOT dict keys). See PRD section 10 for what this
                     # does NOT attest to. Not clean is never written.
```

The field-level contract is [PRD §10](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#10-the-scrubbed-sidecar).

## Stability and the determinism contract

**The promise: the same input, scrubbed with the same config under the same sanitizer
version, produces byte-identical output.** That is what makes a scrubbed artifact
reviewable and re-checkable: anyone can re-run the scrub and diff. The sidecar is
identical too, apart from `scrubbed_at`, which is a wall-clock timestamp.

**The promise holds only *within* a sanitizer version.** A different version may legally
produce different bytes from the same input. That is the whole reason the version is
stamped into every sidecar.

> **If you consume scrubbed artifacts, record the `sanitizer_version` you scrubbed under
> and compare against that.** Assuming byte-stability across versions does not raise an
> error. It silently gives you a wrong answer, which is the worst failure shape available.

Byte-identity also holds **across supported Python versions**, currently **3.11, 3.12,
and 3.13** (the `requires-python` floor is 3.11). Scrubbing on one and validating on
another is a supported workflow. This is enforced, not asserted: a committed golden
fixture ([`tests/golden/`](https://github.com/frederick-douglas-pearce/claude-code-sessions/tree/main/tooling/sanitizer/tests/golden))
holds a synthetic session, a pinned config, and the exact expected output and sidecar
bytes, and every cell of the CI matrix must reproduce them. All three interpreters match
the same artifact on disk rather than merely matching themselves
([#162](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/162)).
When those bytes change, that is a version bump under the CHANGELOG policy, not a
regeneration.

### What each bump level means for your bytes

Versions are semver, `MAJOR.MINOR.PATCH`. Read them as statements about output bytes:

| Bump | What changed | What it means for you |
|---|---|---|
| **PATCH** | A bug fix that changes which inputs a rule matches. No rule added or removed, no config-surface change. | Output bytes may differ from the previous version on affected inputs. Re-scrub if you need the fix. |
| **MINOR** | A new rule, a new pattern, a new CLI flag, or an *additive* sidecar field. Backward compatible at the config surface. | Your existing config keeps working. Output may scrub *more* than before. A consumer that ignores unknown sidecar keys is unaffected. |
| **MAJOR** | A *breaking* sidecar change (a field removed, renamed, or retyped), a config schema break, removal of a built-in pattern, or any change that requires re-running the sanitizer on previously scrubbed sessions. | Read the CHANGELOG before upgrading. Previously scrubbed artifacts may need re-scrubbing. |

Any change to the sidecar's shape, additive or breaking, also bumps
`sidecar_schema_version`. The two levers are separate on purpose: the semver level tells
you what the *tool* did to your bytes, the schema version tells you what the *document*
looks like.

The maintainer-facing checklist of what counts as a byte-affecting change lives in
[`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md). This
section is the authoritative statement of what a bump *promises*; the CHANGELOG defers
to it rather than restating it.

### `sidecar_schema_version`

The sidecar leads with `sidecar_schema_version`, currently **`1`**. It versions the
*shape* of the sidecar document and nothing else: fields added, removed, renamed, or
changed in type. It is independent of `sanitizer_version`, so a consumer branches on one
integer instead of maintaining a table mapping every sanitizer release to a layout. A new
sanitizer version does not imply a new schema version. Every public-era sidecar
(`0.3.0` onward) carries the field.

### Scrubbed artifacts are pinned to the version that produced them

A `.scrubbed` sidecar records the version that made *that* file. It does not move when the
tool does, and nothing re-scrubs it automatically. **Re-scrubbing after a MAJOR bump is a
deliberate manual act**, decided by whoever owns the artifact. The sanitized fixtures in
this repo behave exactly that way: they keep the version they were scrubbed under, which
is why some of them predate `0.3.0`.

The corollary for anything that validates artifacts: **"a recognized `sanitizer_version`"
has to mean a maintained allowlist of historical versions, not "the current one."**
Publishing accelerates release churn, so a validator that only accepts the newest version
starts rejecting valid archived artifacts almost immediately.

### Deprecation, yanking, and support

A MAJOR bump may require re-running the sanitizer on previously scrubbed sessions. That is
the strongest thing a release can ask of you, and the CHANGELOG will say so explicitly.

**Old versions are yanked from PyPI only for security reasons, never for routine
supersession.** A superseded release stays installable. Which versions receive security
fixes, and what happens when a scrubbing hole is found, are stated in
[SECURITY.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/SECURITY.md), which owns that policy.

### Releases and tagging

Releases are tagged with a **component-scoped** tag, not a bare `v*`:

```
sanitizer-v0.3.0
```

This repo is a monorepo holding posts, reference docs, and three tools, so a bare `v0.3.0`
would be ambiguous, and a `v*` tag filter in the release workflow
([#163](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/163))
would fire the PyPI publish job on any future repo-level or Pages tag. The tag is
`sanitizer-v<version>`, matching `__version__` and the CHANGELOG heading exactly.

Pushing that tag starts [`sanitizer-release.yml`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.github/workflows/sanitizer-release.yml),
which publishes to PyPI through Trusted Publishing (OIDC, no stored API token) with
[PEP 740](https://peps.python.org/pep-0740/) attestations. It re-runs the full test
matrix and the packaging job against the tagged commit rather than inheriting a status
from `main`, builds with a pinned backend, smoke-tests the artifact it is about to
upload, and then waits on a protected environment for a human. The maintainer-facing
runbook, including the TestPyPI rehearsal that has to happen before a real upload, is
[RELEASING.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/RELEASING.md).

## Getting started

The live `.ccs-sanitize.yaml` holds the literal PII strings the sanitizer
will scrub (real home dir, real email, real name, etc.) and is gitignored.
The committed `.ccs-sanitize.example.yaml` is a schema-only template. New
users (or forks) bootstrap with three steps:

```bash
ccs-sanitize --init                 # writes .ccs-sanitize.example.yaml +
                                    # .ccs-sanitize.yaml in the cwd from the
                                    # bundled template. Does NOT mutate .gitignore.
$EDITOR .ccs-sanitize.yaml          # fill in your real match values
ccs-sanitize <input> -o <output>    # the pre-run gitignore guard refuses
                                    # to scrub unless .ccs-sanitize.yaml is
                                    # gitignored, when inside a git repo
```

The pre-run gitignore guard is built in and runs on every invocation.
If the resolved config lives inside a git repository and is not
gitignored, the run stops with exit code 3 and an actionable message.
`--no-check` opts out of the guard entirely. It is a deliberate
override, used by the test suite and by anyone who has knowingly
accepted the risk; it is not the remedy for exit 3, which is to
gitignore the config. The threat model and the full layered defenses
are documented in
[PRD §12b](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#12b-config-storage-and-safety).

### First run without a clone

If you installed from PyPI and are scrubbing in a scratch directory
that is not a git repository, the guard has no ignore rules to consult.
It prints one warning line to stderr and the scrub proceeds normally.
That warning does not mean the scrub was unsafe or incomplete. It means
the `git add .` threat the guard defends against does not apply where
there is no repository to stage into, so the guard had nothing to
check. The same warn-and-proceed path covers a missing `git` binary and
any other `git check-ignore` failure.

Exit 3 is reachable only from inside a git repository. If you later
move that config into a repo, gitignore it there.

## Development

The package is `uv`-managed and Python 3.11+. From `tooling/sanitizer/`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest                          # run the test suite
ccs-sanitize --version          # smoke-check the entry point
```

The runtime dependency surface is intentionally minimal: stdlib plus PyYAML
for config parsing. `pytest` is the only dev dep.

CI runs the same suite on a 3.11 / 3.12 / 3.13 matrix, plus `python -m build`,
`twine check --strict`, and a clean-environment smoke test of the built wheel
(`.github/workflows/sanitizer-ci.yml`). The aggregate `sanitizer-ci` check is
required, so packaging problems surface on a pull request rather than during
`twine upload`, where a bad artifact costs a version number.

Version bumps follow [`CHANGELOG.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/CHANGELOG.md)'s "bump on any
byte-affecting change" checklist, because the value lands in every `.scrubbed` sidecar and
downstream consumers gate on it. What each bump level promises to those consumers is
[Stability and the determinism contract](#stability-and-the-determinism-contract) above.
Cutting a release also means tagging `sanitizer-v<version>`, which is the trigger for
the release workflow described in [Releases and tagging](#releases-and-tagging) above and
walked through step by step in
[RELEASING.md](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/tooling/sanitizer/RELEASING.md).

## Not in scope (for v0)

- GUI / interactive review mode
- Streaming sanitization of live sessions
- Automatic upload to any destination
- Reverse-mapping (the scrub is one-way)

## Open questions — resolved

These four questions originally gated implementation. All are resolved in
[`prd-sanitizer.md` §15](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#15-open-questions--resolutions):

1. ~~Yaml-configured rule sets vs. code-defined rules~~ → **Hybrid** (D-1): secrets in code (non-weakenable; additive YAML extension), paths/identifiers in YAML.
2. ~~Sidecar: embed substitution dictionaries vs. rule-level counts~~ → **Redacted detail** (D-2): per-substitution detail with category placeholders and the non-sensitive replacement; secrets count-only; originals never recorded.
3. ~~Statistical jitter granularity~~ → **Deferred to v1** (D-3); designed as a per-session timestamp offset coupled to a future session-bundle mode.
4. ~~Fixture-validator integration~~ → **Independent re-scan** (D-4); the validator never trusts the sidecar.

The PRD also adds [D-7](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/prd-sanitizer.md#decision-d-7--v0-drops-high-risk-line-types):
v0 drops `file-history-snapshot` and `attachment` lines wholesale rather than scrub arbitrary
file bodies or opaque binary payloads.
