# Hook validator: landscape and rough spec (draft)

Status: draft, 2026-10-07. Parked here until the standalone hook-validator repo exists, then moved there and deleted from this repo. Tracking: vigiles spike [#282](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/282), guard fixes [#283](https://github.com/frederick-douglas-pearce/claude-code-sessions/issues/283) / [PR #284](https://github.com/frederick-douglas-pearce/claude-code-sessions/pull/284).

## Problem

Hooks are Claude Code's deterministic control: the place the hard rules live. A guard hook that is wrong fails silently in the direction that matters. Three facts from the current docs and issue tracker make that concrete:

1. **Command hooks fail open.** Only exit 2 or a JSON `deny` blocks. Any other exit code, unparseable stdout, or a timeout lets the tool call proceed ([hooks reference](https://code.claude.com/docs/en/hooks), "Other exit codes" and "Timeouts"). A guard whose interpreter is missing (`python3: not found`, exit 127) allows everything. A script can be fail-closed internally and still fail open at the harness.
2. **Config errors can disable every hook at once.** [anthropics/claude-code#75071](https://github.com/anthropics/claude-code/issues/75071): one schema-invalid matcher silently dropped the whole `hooks` block; one reporter ran ~30 hours with ~109 hooks inert. Closed as completed 2026-08-20, but a v2.1.233 comment on the duplicate (#75081) says `-p` mode was still silent. Matchers on events without matcher support are "silently ignored" (hooks reference). `mcp__memory` (no `.*`) matches nothing.
3. **Guards are usually narrower than their authors think.** Running 11 adversarial synthetic events through this repo's own `block_secret_reads.py` (plus 3 controls) produced 9 allows where the intent was deny. Details in "Worked example."

## Landscape (what exists today)

No tool proves a guard blocks what it is meant to protect and declares what it does not cover. Closest matches, verified:

| Tool | What it is | Fit |
| --- | --- | --- |
| [vigiles](https://github.com/zernie/vigiles) (npm, TypeScript, 15★, created 2026-03, active) | Harness linter and tester for Claude Code and Codex. `runHook` pipes payloads and asserts; a fixed destructive-command battery with 136 spelling variants; `experimental_verifyPluginGuards` reports *why* a hook wasn't measured (`not-applicable`, `unresolved`); `runHarnessTest` drives the real CLI with a scripted mock model; property-based fuzzing. | Closest. Command-centric (destructive Bash), not asset-centric. No cross-tool reachability, interpreter indirection, symlink, MCP, or subagent probes found. Single maintainer, key APIs `experimental_`. |
| `claude plugin eval` (official) | Runs real headless Claude Code with one plugin loaded; graders `regex` (incl. full trace), `tool_used`, `tool_order`, `file_exists`, `llm`, `baseline`. | Integration only, indirect. No hook grader; project/user settings hooks are not loaded; costs model calls; nondeterministic. |
| plugin-dev `hook-development` scripts (official) | `validate-hook-schema.sh` (stale 9-event list), `test-hook.sh` (prints exit code), `hook-linter.sh`. | Smoke test plus lint, no assertions. |
| [claude-hooks-check](https://pypi.org/project/claude-hooks-check/) (v0.1.0) | Static linter for the `hooks` block. | Thin; no regex compile or reachability checks. |
| claude-code-hook-tester | Mock payload per event, flags crashes and slow hooks. | Smoke test. |
| redstamp `arena/` | 298 self-authored labeled samples, 25 attack families, JSONL adapter for any guard. | Benchmark corpus, Bash/exfil only. Possibly reusable. |
| Cupcake (OPA/Rego), Sondera (Cedar) | Policy engines that enforce through hooks. | Enforce, don't verify. Cedar's static analysis checks the policy, not the hook. |
| hookify, rule2hook, hook SDKs, "battle-tested hooks" collections | Generators and pre-made hooks, some with their own tests. | Not validators. |

First-party: no hook doctor, no `claude hook validate`, no published hook I/O JSON Schema; `/hooks` is a read-only browser; `--debug-file` logs hook execution.

Known bypass classes a validator must probe (sources in the research notes): fail-open exit codes; command-form variance; indirect file access via interpreters and `grep -r` (the [permissions docs](https://code.claude.com/docs/en/permissions) say Bash deny rules aren't a security boundary); symlinks (CVE-2025-59829, CVE-2026-25724); path aliasing (`/proc/self/root/...`); subagents (historically didn't fire, [#21460](https://github.com/anthropics/claude-code/issues/21460); docs now say they do, with `agent_id`/`agent_type`); hook self-modification ([#11226](https://github.com/anthropics/claude-code/issues/11226)); denylist fragility at scale ([arXiv 2606.15549](https://arxiv.org/abs/2606.15549)).

## Core idea: contract first

Today a guard's intent lives in prose (this repo's `.claude/hooks/README.md` is a good example: "Bash is intentionally left alone so that..."). The validator makes that intent machine-readable, then tests the hook against it. Every probe lands in one of four cells:

- **covered**: intent says deny, hook denies
- **gap**: intent says deny, hook allows. Fails CI.
- **declared**: hook allows, and the contract names it as an accepted exemption with a reason. Passes, and is listed in the report.
- **unclosable at this layer**: the probe class cannot be closed by a string-matching hook at all (e.g. `python3 -c` building a path at runtime). Reported with the layer that *can* close it (sandbox filesystem rules, OS permissions, moving the file).

The last cell is the point. The tool is honest about what a hook can't do, instead of encouraging an ever-longer regex.

Sketch of a contract (`hook-contract.yaml`):

```yaml
guard: .claude/hooks/block_secret_reads.py
event: PreToolUse
protects:
  - id: credentials
    paths: ["**/.env", "**/.env.*", "**/.ssh/id_*", "**/*.pem", "**/credentials.json"]
    deny: [read, search-content, edit]       # capability verbs, mapped to tools by the catalog
  - id: raw-sessions
    paths: ["~/.claude/projects/**/*.jsonl"]
    deny: [read, search-content, edit]
    exempt:
      - via: Bash
        reason: "tail -f demos and the ccs-sanitize CLI must read raw sessions"
must_allow:                                  # regression set: the guard must not over-block
  - { tool: Bash, command: "ccs-sanitize session.jsonl" }
  - { tool: Read, file_path: "fixtures/synthetic/x.jsonl" }
```

## Components

**1. Config lint (static, free).** Resolve and merge every hook source (managed, user, project, local, plugins) the way Claude Code does, then check: event names valid for the target version; matcher regex compiles and actually reaches tools (`mcp__x` without `.*`, plugin-scoped MCP names, matchers on matcher-less events); the whole-file-drop condition from #75071; script exists, is executable, interpreter resolves on the hook's PATH; timeout set; and **self-protection**: can Edit/Write reach the guard script or the settings file that registers it, unguarded?

**2. Contract tests (deterministic, offline, cheap).** A tool catalog maps capability verbs to every tool and input field that can carry a path or command (Read `file_path`; Grep `path`, `glob`, `pattern`; Glob; NotebookEdit; Bash `command`; known MCP tools). It generates asset × tool × field payloads and pipes them to the hook. The catalog is the reusable asset, and it is format knowledge, which this repo's `reference/` already owns.

**3. Mutation probes (deterministic).** Path mutations: case, `..`, `~`, trailing slash, directory-level targets, globs, backup suffixes (`id_rsa.bak`), symlink-shaped paths. Command mutations: globs, string concatenation, variable indirection, interpreters (`python -c`, `node -e`, `perl`), `xargs`, here-strings, base64, `sh -c`. Each probe is tagged with its class so the report aggregates by class, not by 300 individual lines.

**4. Robustness / fail-mode.** Malformed JSON, missing fields, wrong types, oversized input, missing interpreter, timeout, noisy stdout. Verifies the fail-closed claim *at the harness*, using the documented exit-code semantics, not just inside the script.

**5. Live integration (optional, costs tokens).** Headless `claude -p` in a throwaway directory with canary files holding fake marker values, instructed to reach them via main thread, subagent, and MCP. Pass/fail by reading the resulting session JSONL: `toolDenialKind`, `is_error` tool results, and whether a canary value appears anywhere in the transcript. This is the only layer that answers harness questions the unit layers can't (does the harness normalize `..` before the hook sees it? do hooks fire in this mode, this version?). Run on a version cadence, like format-scan, to catch regressions.

**6. Report.** A coverage matrix by asset × tool × probe class with the four cells above, plus a generated **residual-risk statement** in plain prose that can be pasted into a hooks README. Exit nonzero on any `gap` for CI.

**7. Builder (later).** A skill in the shape of skill-creator: interview (what are you protecting, from which capabilities, what must keep working), write the contract, generate the hook, run components 1–4, iterate until no `gap` remains, emit the residual-risk statement. Contract-first means the builder and validator share one artifact. The builder never claims completeness.

## Worked example: this repo's guard

11 adversarial cases plus 3 controls (omitted), synthetic payloads, nothing read from disk. "Got" is the hook at commit `70d2a86`, before the fixes; the vigiles spike (#282) runs against that commit so these rows serve as ground truth.

| Probe | Intended | Got | Status |
| --- | --- | --- | --- |
| Read `.ENV` (same file on macOS/Windows) | deny | allow | was undeclared; fixed in #284 |
| Read `~/.ssh/id_rsa.bak` | deny | allow | was undeclared; fixed in #284 |
| Read raw session via `.../x/../.claude/projects/...` | deny | allow | was undeclared; fixed in #284 (whether the harness normalizes `..` first is still unknown) |
| Grep `output_mode: content`, `glob: .env` | deny | allow | was undeclared (`glob` not inspected); fixed in #284 |
| Grep content with `path: ~/.claude/projects` (directory) | deny | allow | was undeclared (rule required a `.jsonl` suffix); fixed in #284 |
| Bash `cat .e?v` | deny | allow | declared (CLAUDE.md: globbing) |
| Bash `f=.en; cat "${f}v"` | deny | allow | declared (variable indirection) |
| Bash `python3 -c open('.e'+'nv')` | deny | allow | unclosable at this layer |
| `mcp__filesystem__read_file` | deny | allow | no such server here; `mcp__ide__executeCode` is the live analog |
| Bash `cat <raw session>` | allow | allow | declared exemption |
| Read unexpanded `~/.claude/projects/...` | deny | deny | covered |

The two Grep rows are the strongest finding: they surfaced raw-session or credential *contents* through a file tool the README said was covered. After #284, two cases are declared rather than fixed: Grep rooted at an ancestor of the session directory, and symlinks.

## Proposed phasing

- **Spike (half a day, #282):** run vigiles against this repo's two hooks. Decide adopt / contribute / build based on what it reports.
- **v0:** contract format, tool catalog, components 1, 2, 4, and the report. Python, stdlib-first, matching the tooling family. Dogfood on this repo's guards and AgentFluent's.
- **v0.1:** mutation probes (3).
- **v0.2:** live integration (5), reading the session JSONL with format knowledge from `reference/`.
- **Later:** builder skill (7); policy-engine adapters (Cupcake, Sondera) so the same contract can test a Rego/Cedar guard.

## Decisions (2026-10-07)

- **Home: a standalone repo.** It's general hook tooling, not format documentation. Create it after the spike; the name and visibility are still open.
- **AgentFluent and CodeFluent consume it rather than embed it.** Until v1 they run its command line and read a versioned JSON report, so they depend on that report's format rather than the tool's internals.
- **The tool catalog is owned by the validator** as data, citing this repo's `reference/` as evidence, with no runtime dependency on this repo.
- **Language: Python, stdlib-first**, matching the tooling family. It tests hooks in any language, since it only pipes JSON to a command.
- **Hook observability gaps in session JSONL go upstream.** Track them as a format issue in this repo, then file one consolidated, evidence-backed issue with Anthropic after searching for existing ones. Candidates from Part 6:
  - a PreToolUse or PostToolUse hook that allows leaves no record
  - `toolDenialKind: permission-rule` doesn't separate a hook from a settings deny rule
  - the event name is never a field
  - the hook's identity on a denial exists only in prose

  Check the debug log and telemetry first, so the ask is "persist it" rather than "record it."
- **Guard fixes:** all five undeclared gaps go into #283 / PR #284.

## Still open

- **Adopt, contribute, or build**, decided by #282. vigiles covers command-centric testing well. What it lacks is the asset contract, the cross-tool catalog, the unclosable-at-this-layer verdict, and the session-JSONL live check. Contributing those upstream means TypeScript and depending on a single maintainer.
- **Repo name and visibility.**
