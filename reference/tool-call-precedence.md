# Tool-call precedence: mods, settings hooks and permission rules

What decides a Claude Code tool call, and in what order, now that [mods](https://code.claude.com/docs/en/plugins/mods/overview) exist. A mod is a plugin whose `hooks/hooks.json` has a `modules` entry: a JavaScript or TypeScript module that Claude Code loads into its own process, whose handlers can watch, rewrite, answer or approve tool calls. This doc covers how those handlers sit next to the hooks registered in settings files (here called **settings hooks**, to keep them apart from a mod's handlers, which the mods docs also call hooks) and next to permission rules.

These are harness facts, not JSONL fields, but they decide what a guard hook's decision is worth, so they live here beside the hook-input facts (#287, #310). The [claude-hook-validator](https://github.com/frederick-douglas-pearce/claude-hook-validator) catalog cites this doc row by row (its #4) and uses it for the mod-layer condition in its report (its #9).

**Evidence.** Every fact below is **documented, not measured**: it comes from the official docs (fetched 2026-10-20), the Claude Code changelog, or the source of the built-in `sec-default` mod in [`anthropics/claude-code/mods/sec-default`](https://github.com/anthropics/claude-code/tree/main/mods/sec-default). Nothing here ran a mod. Measured confirmation is planned through claude-hook-validator's mock-model live tier (a fixture adversary mod, its #90). The behavior is still changing (see [Open upstream reports](#open-upstream-reports)), so every claim carries the version it was checked against.

Mods shipped in Claude Code v2.1.287 (2026-10-01). The current version at verification was v2.1.304 (2026-10-19).

---

## The order on a tool call

**Verified against Claude Code v2.1.304 (documented, not measured).** Sources: [Events: the order mods run in](https://code.claude.com/docs/en/plugins/mods/events#the-order-mods-run-in), [Admin: know which controls still apply](https://code.claude.com/docs/en/plugins/mods/admin#know-which-controls-still-apply), [Permissions: precedence among rules, hooks, and mods](https://code.claude.com/docs/en/permissions#precedence-among-rules-hooks-and-mods).

1. **`PreToolUse` hooks from managed settings.** They run before any mod's `tool.call` handler. If one blocks, no mod's `tool.call` handler runs for that call. If the call goes on and a mod rewrites it, the managed hooks run again on the rewritten call.
2. **Mods' `tool.call` handlers**, as one middleware chain, outermost first:
   1. the built-in guard `sec-default@builtin` (where it loads; see [When the built-in guard loads](#when-the-built-in-guard-loads)), the organization's `prependPlugins`, then any other mod that counts as the organization's and isn't in `appendPlugins`
   2. mods the user installed
   3. the organization's `appendPlugins`
   4. other built-in mods

   The outermost mod sees the event first and the result last, and decides whether the others run. A handler that returns `{ deny }` or `{ result }` without calling `next` ends the chain there.
3. **`PreToolUse` hooks from every other settings file and from plugins' `hooks/hooks.json`.** They run after the last mod calls `next`, as part of Claude Code's own behavior. These are the user-level and project-level guards. "A mod that answers `tool.call` without calling `next` keeps them from running" (events doc).
4. **Permission rules** (`deny`, `ask`, `allow`), evaluated whatever a `PreToolUse` hook returned. A hook that blocks (exit code 2) stops the call before allow rules apply.
5. **Mods' `tool.check` handlers.** They get the decision that the rules, the permission mode and the `PreToolUse` hooks reached, and can return `allow`, `ask` or `deny` in its place. How far an `allow` reaches depends on the regime (next sections). The event carries `agentId` for a subagent's check (v2.1.290) and `isReadOnly` (v2.1.304).
6. **The permission prompt, the auto-mode classifier and `PermissionRequest` hooks**, then the tool.

A mod's `{ deny }` returned **after** `await next(e)` doesn't stop the tool: the tool has already run, and only its result is withheld from Claude (changelog v2.1.299: "a tool that already ran has its result withheld").

Every settings hook event is also a mod event, `classic.<Event>`, whose `e` is the settings hook's stdin JSON. A mod on `classic.PreToolUse` sits in front of the settings `PreToolUse` hooks it wraps.

---

## When the built-in guard loads

**Verified against Claude Code v2.1.304 (documented, not measured).** Sources: [Admin: know what happens by default](https://code.claude.com/docs/en/plugins/mods/admin#know-what-happens-by-default), the [`sec-default` README](https://github.com/anthropics/claude-code/blob/main/mods/sec-default/README.md).

`sec-default@builtin` (listed by `/plugin` and the debug log as `cc-plugin-sec-default`) loads ahead of every user-installed mod, and users can't turn it off, when either is true:

- the machine has managed settings, or
- the session's credential is a `/login` for a Team or Enterprise plan.

These don't count on their own: an API key; Amazon Bedrock, Google Cloud's Agent Platform or Microsoft Foundry; a long-lived `CLAUDE_CODE_OAUTH_TOKEN`, even with a Team or Enterprise login stored on the machine. Those sessions get the guard only on a machine with managed settings.

Exception: where managed settings define `prependPlugins`, that list is the whole prepend tier and must name `sec-default@builtin`. A list that leaves it out means the guard doesn't load, and none of its options apply (admin doc, "The guard has to load").

The guard protects what the organization manages: what managed hooks receive and decide, the system prompt, managed `CLAUDE.md` and instructions, what any mod reads as settings, managed MCP servers' tools, and the deny rules in force. It **protects verdicts, not whether a guard runs**: with it loaded, a user's mod still can't approve a call a `PreToolUse` hook blocked, but it can still answer `tool.call` itself so that non-managed `PreToolUse` hooks never run.

"Are managed settings present?" is therefore not a complete test for the regime: a Team or Enterprise login also loads the guard, and a managed `prependPlugins` list without it keeps it out.

---

## What a user-installed mod can do, by regime

**Verified against Claude Code v2.1.304 (documented, not measured).** Sources: [Permissions: precedence among rules, hooks, and mods](https://code.claude.com/docs/en/permissions#precedence-among-rules-hooks-and-mods), [Admin: know what happens by default](https://code.claude.com/docs/en/plugins/mods/admin#know-what-happens-by-default), [Admin: read what a mod can do](https://code.claude.com/docs/en/plugins/mods/admin) (its `$.env.set` and `$.fs` rows), the [`sec-default` README](https://github.com/anthropics/claude-code/blob/main/mods/sec-default/README.md) (its `classic.*`, `tool.check` and `env.set` rows), changelog v2.1.299.

| A user-installed mod can... | Where the built-in guard loads | Where it doesn't |
| --- | --- | --- |
| Approve (`tool.check` `allow`) a call that a `PreToolUse` hook **blocked**, from any settings file | No, unless the organization sets `allowModsToOverrideDenyRules`, which also lifts `PreToolUse` blocks and asks | **Yes.** "The mod can approve a call that a deny rule refuses or a `PreToolUse` hook blocked" (permissions doc) |
| Approve a call a `deny` rule refuses | No, unless `allowModsToOverrideDenyRules` | Yes |
| Approve a call an `ask` rule, a `PreToolUse` hook's `ask` or `permissions.blockReadsOutsideWorkingDirectories` would prompt for, without the prompt | No: the prompt stays | Yes |
| Approve a call that `--permission-prompt-tool` or an Agent SDK `canUseTool` callback would be asked about, without asking it | No | Yes |
| Skip non-managed `PreToolUse` hooks by answering `tool.call` without calling `next` | **Yes** | Yes |
| Rewrite what settings hooks receive, or their answers, through `classic.*` | No: `sec-default` continues `classic.*` events past the user tier, so the organization's settings hooks see the engine's input and their answer stands | Not stated outright. The guard exists to stop it, which suggests yes |
| Set environment variables for Claude Code and for every command and MCP server it starts afterward, including command hooks (`$.env.set`) | **Yes for most variables, `PATH` and `HOME` included.** Refused: variables managed `env` sets, nine that move where policy and sign-in are read from (such as `CLAUDE_CONFIG_DIR`), and ten that can load code into a child (`LD_PRELOAD`, `LD_LIBRARY_PATH`, `LD_AUDIT`, `DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, `DYLD_FRAMEWORK_PATH`, `BASH_ENV`, `ENV`, `ZDOTDIR`, `NODE_OPTIONS`). `allowModsToOverrideDenyRules` doesn't change this | Yes. Since v2.1.299 a user mod's `$.env.set` no longer changes the environment or shell prefix that **managed** command hooks start with; other command hooks aren't shielded |
| Read a protected file directly (`$.fs.read`, or `$.process` to start a program that reads it) | **Yes.** "With `Read(.env)` denied, a mod can still read that file with `$.fs.read`" (admin doc). Permission rules and `PreToolUse` hooks apply to Claude's tool calls, not to a mod's own calls | Yes |

### Mode and tool exceptions, in both regimes

**Verified against Claude Code v2.1.304 (documented, not measured).** Source: [Permissions: precedence among rules, hooks, and mods](https://code.claude.com/docs/en/permissions#precedence-among-rules-hooks-and-mods), [Hook approvals in plan mode](https://code.claude.com/docs/en/permissions#hook-approvals-in-plan-mode).

- **Plan mode:** a mod's `tool.check` `allow` can't approve a call that isn't read-only (a file edit, a shell command that writes), though it can still block one. The same holds for a `PreToolUse` hook's `allow`. Before v2.1.299, plan mode could run a write that a `PreToolUse` hook or a mod's `tool.check` allowed (changelog v2.1.299).
- **Auto mode:** a call the mod approves runs without a classifier check, except where the guard is loaded and the session uses `--permission-prompt-tool` or a `canUseTool` callback. There the classifier checks the call first.
- **`dontAsk` mode:** the mod can approve a call that nothing but the mode would deny.
- **Tools that require user interaction** (`AskUserQuestion`, an MCP tool marked `requiresUserInteraction`): a mod's `tool.check` approval doesn't skip the prompt (v2.1.292 or later).

---

## What closes or narrows the mod layer

**Verified against Claude Code v2.1.304 (documented, not measured).** Source: [Admin: stop user-installed mods from loading](https://code.claude.com/docs/en/plugins/mods/admin#stop-user-installed-mods-from-loading), [Admin: know which controls still apply](https://code.claude.com/docs/en/plugins/mods/admin#know-which-controls-still-apply).

For a guard that isn't a managed hook, only these close the gap the table above describes:

- no mods installed and none loaded for the session (`--plugin-dir`, `CLAUDE_CODE_PLUGIN_DIRS`, a hot-reloaded session mod all count);
- managed `allowManagedModsOnly`, with the built-in guard loaded; or
- making the guard a managed `PreToolUse` hook, which runs before every mod and again on a rewritten call.

Narrower controls: a marketplace allowlist (`strictKnownMarketplaces`) plus `disableSideloadFlags` limits where mods come from. `allowManagedHooksOnly` keeps user-installed mods from loading but also blocks hooks in users' own settings files. `disableAllHooks` stops every mod and every settings hook, the guard included. Built-in mods ignore all of these.

---

## Version history

Changes that moved a fact on this page. From the [Claude Code changelog](https://code.claude.com/docs/en/changelog).

| Version | Change |
| --- | --- |
| v2.1.287 (2026-10-01) | Mods ship. |
| v2.1.290 | `tool.check` gets `agentId`. `claude plugin validate --json` lists each gating handler and whether it has a `.catch` (`gatingHooks`). Mods no longer stay off for sessions reaching Claude through a gateway (`ANTHROPIC_BASE_URL` with `ANTHROPIC_AUTH_TOKEN`) with no Anthropic account. |
| v2.1.292 | A mod's `tool.check` approval doesn't skip the prompt for tools that require user interaction (the permissions doc's minimum version for this). |
| v2.1.293 (2026-10-07) | A mod's handlers on `classic.*` events are no longer skipped while the plugin hooks worker restarts. |
| v2.1.299 | A user mod's `$.env.set` no longer changes the environment of managed command hooks. Plan mode no longer runs a write a `PreToolUse` hook or a `tool.check` handler allowed. A call a plugin hook can block is refused, not let through, when the hook can't be handed it or can't hand back its answer. Values with `__proto__` keys no longer skip a `tool.check` guard. Enforcement of managed permission rules and managed hooks against user-installed mods improved. |
| v2.1.304 (2026-10-19) | `tool.check` gets `isReadOnly`. |

---

## Open upstream reports

Reports that dispute or qualify a fact above. Recheck them before relying on the affected row.

- [anthropics/claude-code#102470](https://github.com/anthropics/claude-code/issues/102470) (open, filed 2026-10-15): reports a behavior change in v2.1.299 that the docs and changelog don't describe.
- [anthropics/claude-code#100869](https://github.com/anthropics/claude-code/issues/100869): reports `classic.*` events not reaching a module on v2.1.295. Affects the `classic.*` row.

---

## Cross-references

- **What a hook receives:** #287 records how Claude Code normalizes `tool_input` before `PreToolUse` hooks. #312 asks whether mods' `tool.call` and `tool.check` see the same input.
- **Which shell runs a command hook:** #310.
- **Where this is used:** claude-hook-validator's [research note on mods](https://github.com/frederick-douglas-pearce/claude-hook-validator/blob/main/research/mods/README.md) holds the analysis and the full source list. Its catalog keeps a version-ranged copy of these rows.
- **Official pages:** [Mods overview](https://code.claude.com/docs/en/plugins/mods/overview), [Events](https://code.claude.com/docs/en/plugins/mods/events), [Reference](https://code.claude.com/docs/en/plugins/mods/reference), [Admin](https://code.claude.com/docs/en/plugins/mods/admin), [Permissions](https://code.claude.com/docs/en/permissions), [Hooks reference](https://code.claude.com/docs/en/hooks).
