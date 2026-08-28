# AI use in this repository

This repository documents Claude Code. It was also built with Claude Code, which makes an explicit
statement about that collaboration more useful here than it would be in most projects.

In creating this repository, I collaborated with Claude Code (Anthropic's CLI, running Claude models)
to assist with drafting posts and reference documentation, researching the session format against real
session data, implementing and testing the tooling under `tooling/`, and editing throughout. I affirm
that all AI-generated and co-created content underwent thorough review and evaluation. The final output
accurately reflects my understanding, expertise, and intended meaning. While AI assistance was
instrumental in the process, I maintain full responsibility for the content, its accuracy, and its
presentation. This disclosure is made in the spirit of transparency and to acknowledge the role of AI in
the creation process.

## What that means per surface

**[`posts/`](posts/)** — drafted with Claude Code, edited by me, fact-checked against a pinned Claude
Code version recorded in each post's `claude_code_version_verified` frontmatter. Every post ends with a
one-line disclosure footer naming that version. Posts that fall more than a few minor versions behind
their verified version get re-verified or corrected. Short-form derivatives on other platforms carry the
same disclosure without the version clause; a few of the earliest ones, published before that
convention landed, do not.

**[`reference/`](reference/)** — field-level documentation derived from observed session data, not from
a model's recollection of the format. Every section that names a JSONL field carries a
`Verified against Claude Code v<X>` note, and several record the scan that backs them: file counts,
version range, and exactly what was read. Claims that lack evidence are marked as unverified rather than
asserted; the open items are tracked as issues rather than papered over.

**[`tooling/`](tooling/)** — written with Claude Code, reviewed by me, covered by the `pytest` suites in
the sanitizer and format-scan packages and by the CI described in the README. Changes to tooling, hooks,
CI, and fixtures land through pull requests that include an explicit security review section. Content and
documentation changes commit directly.

**[`fixtures/`](fixtures/)** — session data, not authored prose. Synthetic fixtures are fabricated and
ship with a `.generator.md` note describing how; sanitized fixtures are real session data scrubbed by
[`tooling/sanitizer/`](tooling/sanitizer/) and ship with a `.scrubbed` sidecar recording the run. No raw
session data is committed here, ever. See [SECURITY.md](SECURITY.md).

## Where the judgment is mine

The scope of the series, the claims the reference docs make, the security posture and how it is enforced,
and every decision about what is safe to publish are mine. Claude Code drafts, scans, proposes, and
implements. It does not decide what ships.

## Errors

Mistakes here are mine. Corrections are welcome as
[issues](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues). Anything involving real
personal data, or a hole in the scrubbing, goes through the private path in [SECURITY.md](SECURITY.md)
rather than a public issue.

## Why this file exists

The framing follows the Diligence competency in Anthropic's
[AI Fluency: Framework & Foundations](https://academy.claude.com/courses/ai-fluency-framework-foundations)
course, and specifically its guidance on
[writing an AI diligence statement](https://academy.claude.com/tutorials/writing-an-ai-diligence-statement):
name the tool, name the tasks, describe the review, and stand behind the result. This repo is not
affiliated with or endorsed by Anthropic.
