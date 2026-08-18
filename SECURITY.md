# Security policy

This repository publishes documentation for Claude Code's session JSONL format and the
tooling that makes that data safe to share. The tooling includes
[`ccs-sanitize`](tooling/sanitizer/README.md), distributed on PyPI as
`claude-code-sessions-sanitizer`. A defect in that tool can cause someone to publish
personal data believing it was scrubbed, so reports about it are treated as security
reports, not as ordinary bugs.

## Reporting a vulnerability

**Please do not open a public issue for a scrubbing bypass.** A public issue is a working
recipe for extracting data from every session anyone scrubs with the affected version,
published before a fix exists.

Report privately through GitHub Security Advisories:

**[Report a vulnerability](https://github.com/frederick-douglas-pearce/claude-code-sessions/security/advisories/new)**
(Security tab → Advisories → Report a vulnerability)

Private reporting is enabled on this repository. The report is visible only to the
maintainer until an advisory is published.

### What is worth reporting

- Input that survives the sanitizer with a real path, identifier, or secret intact.
- A `.scrubbed` sidecar that records an original value it should never have recorded
  (the I-3 guarantee).
- A way to make the sanitizer write output while the residual scan should have failed
  the run, or any other bypass of the fail-closed path.
- A way to defeat the pre-run gitignore guard, or the repository's `.claude/hooks/`
  guards, such that a live config or raw session data reaches a commit.
- Real personal data found in a committed fixture under `fixtures/`, or in a published
  post. Report this privately as well, even though it is data rather than code.

### What is a known limitation, not a vulnerability

The sanitizer scrubs structured leaks. It does **not** scrub free-text prompts and tool
output for arbitrary PII, and it never claimed to. That limitation is documented in
[PRD §4](.claude/specs/prd-sanitizer.md#4-non-goals) and at the top of the
[sanitizer README](tooling/sanitizer/README.md). A report of "the tool did not remove a
person's name that a user typed into a prompt" describes designed behavior.

A concrete proposal for a *new* structured rule that would have caught a real class of
leak is welcome, and belongs in a normal public issue.

### What to include

The input shape that reproduces the problem, the sanitizer version (`ccs-sanitize
--version`), and the relevant part of your config with the sensitive values replaced by
stand-ins. **Do not attach real session data, real secrets, or real personal data to a
report.** A synthetic input that reproduces the same shape is more useful and carries no
risk of the report itself becoming the leak.

### What to expect

This is a single-maintainer project, so response is best effort rather than a
service-level commitment. The intent is to acknowledge a report within a few days, agree
on the severity and a disclosure timeline with you, and credit you in the advisory unless
you prefer otherwise. Please hold public details until a fixed version is available.

## Supported versions

`ccs-sanitize` is pre-1.0 and `Development Status :: 3 - Alpha`. Security fixes go to the
newest released version. There are no backports to older `0.x` releases.

| Version | Supported |
|---|---|
| Newest published release (currently `0.3.0`) | Yes, security fixes |
| Any earlier release | No. Upgrade to the newest release |

Upgrading is not a no-op for previously scrubbed data: a scrubbed artifact stays pinned to
the version that produced it, and byte-level determinism holds only within a version. See
[Stability and the determinism contract](tooling/sanitizer/README.md#stability-and-the-determinism-contract),
which owns that policy.

## Response to a confirmed scrubbing defect or a compromised release

1. **Fix and publish.** A fixed version is released to PyPI, with the CHANGELOG entry
   naming what the defect could leak.
2. **Yank the affected version on PyPI, rather than deleting it.** A yanked release drops
   out of dependency resolution, so no one installs it by accident, but it stays
   installable by exact pin. That matters here: someone who scrubbed under the bad version
   needs to be able to reinstall it and reproduce exactly what their artifacts contain.
   Deleting the artifact destroys that forensic path and does not un-publish anything.
3. **Publish a GitHub Security Advisory** describing the defect, the affected versions,
   the fixed version, and what a user should re-check in artifacts they already published.
4. **State the re-scrub obligation plainly.** If artifacts scrubbed under the affected
   version may contain unscrubbed data, the advisory says so and says which sidecar
   `sanitizer_version` values are implicated.

Yanking is reserved for security. A version is never yanked merely because a newer one
exists.

## Data handling in this repository

No raw session JSONL is ever committed here. Committed session data is either synthetic,
or sanitized with a `.scrubbed` sidecar. The live sanitizer config, which holds literal
PII by design, is gitignored and additionally blocked by a `PreToolUse` hook. The rules
are in [CLAUDE.md](CLAUDE.md) and the threat model is in
[PRD §12b](.claude/specs/prd-sanitizer.md#12b-config-storage-and-safety).
