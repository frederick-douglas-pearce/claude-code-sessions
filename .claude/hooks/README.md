# `.claude/hooks/` — secrets-protection hooks

These hooks are the **mechanical** half of this repo's security posture (the
narrative half lives in [`CLAUDE.md`](../../CLAUDE.md) → "Security posture").
Claude Code session JSONL contains prompts, file paths, code, command output,
and occasionally secrets. This repo's job is to document and publish that
format safely — so reading raw secrets or raw sessions into the model's context
is the thing we most need to prevent.

Ported from AgentFluent's `.claude/hooks/`, adapted for this repo (see issue
#12). They are wired in [`../settings.json`](../settings.json).

## The two hooks

### `block_secret_reads.py` — PreToolUse (primary defense)

Denies a tool call *before* it executes when the target would leak data into
the session transcript. Three classes of target:

1. **Credential files** — `.env*`, shell rc files (`.bashrc`, `.zshrc`, …),
   SSH private keys (`id_rsa`, `id_ed25519`, …), `.pem`, and named secrets
   files (`credentials.json`, `secrets.yaml`, …). Checked for the file tools
   (`Read`/`Edit`/`Write`/`NotebookEdit`), the search tools (`Grep`/`Glob`),
   and `Bash` commands.
2. **Raw session transcripts** — anything ending in `.jsonl` under
   `~/.claude/projects/`. Checked for `Read`/`Edit`/`NotebookEdit`/`Grep`/`Glob`
   **only — not `Bash`**.
3. **Live sanitizer config** — `.ccs-sanitize.yaml` (the file that holds the
   literal PII strings to scrub). Checked for `Read`/`Edit`/`NotebookEdit`/
   `Grep`/`Glob`/`Bash`. **`Write` is allowed** so `ccs-sanitize --init` and
   rewrite-from-scratch iteration still work — mirrors the raw-session
   asymmetry. The committed `.ccs-sanitize.example.yaml` schema reference is
   PII-free and stays freely readable; the pattern is anchored to the live
   basename. Full threat model + defense layers in
   [PRD §12b](../specs/prd-sanitizer.md#12b-config-storage-and-safety).

#### Why raw sessions are blocked for file tools but not Bash

This is the deliberate difference from AgentFluent, whose whole purpose is to
*read* `~/.claude/projects/`. Here the posture is the opposite: "read sample
data from `fixtures/`, never an unsanitized session." So the file tools that
pull a transcript's contents into context are blocked.

`Bash` is intentionally left alone so that:

- the documented inspection workflow (`tail -f ~/.claude/projects/…`,
  `ls`, `jq`) still works, and
- the planned sanitizer CLI can read a real session over Bash to produce a
  scrubbed copy.

`Write` is also excluded from the raw-session rule — it overwrites rather than
surfacing existing content, so it isn't a read-leak vector.

Fails closed: an unparseable event is denied by default.

### `detect_secrets_in_output.py` — PostToolUse (secondary guard)

Scans `Read`/`Grep`/`Bash` output for known credential patterns (Anthropic,
OpenAI, GitHub PAT, AWS, GCP) and emits a `block` decision so Claude won't
echo or summarize a leaked value. **Caveat:** PostToolUse fires *after* the
tool runs, so the value is already on disk in the session JSONL — this hook
limits propagation, it does not prevent the on-disk leak. That's why
`block_secret_reads.py` (which runs *before*) is the primary defense.

## Relationship to the sanitizer

These hooks guard the **input** side: they stop Claude from reading secrets or
raw sessions into context during day-to-day work. The planned
[`tooling/sanitizer/`](../../tooling/sanitizer/) guards the **output** side: it
scrubs a raw session into a publishable, `fixtures/sanitized/`-ready artifact.
Per issue #12, these hooks must be in place before any real session data is
read or any sanitized fixture lands.

## Tests

```bash
python3 .claude/hooks/tests/test_hooks.py
```

`tests/fixtures/` holds synthetic PreToolUse/PostToolUse events — both
known-bad (must block/deny) and known-good (must pass). The known-bad secret
fixture uses a fake, clearly-synthetic key, never a real one.
