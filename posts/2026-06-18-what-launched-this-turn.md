---
layout: post
title: "What launched this turn? Subagents, MCP tools, and Skills"
date: 2026-06-18 00:00:00-0800
description: "Every assistant line can record how it came to exist: the subagent, MCP tool, or Skill behind it. The attribution* fields, and the one that misleads."
categories: ["claude-code-sessions"]
tags: ["claude-code", "agent-sdk", "jsonl", "sessions", "subagents", "foundation"]
og_image: https://frederick-douglas-pearce.github.io/assets/img/what-launched-this-turn-og.png
og_card_source: social/images/2026-06-18-linkedin-what-launched-this-turn/og-card.png
featured: false
claude_code_version_verified: v2.1.150
humanizer_pass: v3.0.0
---

[Part 3 of this series](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-11-inside-the-subagent-trace-file.md) opened the subagent trace file and, in passing, named a family of fields it didn't stop to unpack: `attributionAgent`, `attributionMcpServer`, `attributionMcpTool`, `attributionSkill`. It called them markers that tell you that you've crossed into a sidechain and moved on, since that post was about the file split.

This aside picks them up. It's short and standalone: one field family, what each member records, and the one trap to look out for.

**Every `assistant` line can carry a record of how it came to exist**: which subagent it ran as, which MCP tool it routed through, which Skill it ran under. That record sits at the top level of the line, so you can query it without descending into `message.content`.

---

## Provenance, not content

Part 2 made a point of the [`snake_case` / `camelCase` split](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/posts/2026-06-04-reading-a-claude-code-session-line-by-line.md): `message.content` is Anthropic API payload (`snake_case`), and the fields Claude Code wraps around it are harness bookkeeping (`camelCase`). The `attribution*` family is squarely the second kind. They're Claude Code's annotation of how this turn was routed, recorded alongside the message and outside anything the model said.

The content can't answer that question about itself. A `tool_use` block knows it's calling `mcp__github__get_issue`; it doesn't know it's doing so as the `pm` subagent, three levels removed from your prompt. The attribution fields carry that context at the top level of the line.

There are three kinds of provenance here, across four fields:

| Field                                         | What it records                                | Example value              |
| --------------------------------------------- | ---------------------------------------------- | -------------------------- |
| `attributionAgent`                            | The subagent _type_ this turn ran as           | `"pm"`                     |
| `attributionMcpServer` / `attributionMcpTool` | The MCP server + tool this turn routed through | `"github"` / `"get_issue"` |
| `attributionSkill`                            | The invoked Skill this turn ran under          | a Skill name               |

Each has a strict per-line-type presence pattern, documented in full in [`reference/subagent-traces.md`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#attribution-fields): all four appear on `assistant` lines only, never on `user` or `attachment` lines. So a parser can branch on `type == "assistant"` first and only look for these there.

The worked examples below run against the synthetic [`anatomy-subagent-trace.jsonl`](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl) fixture, a sixteen-line `pm` subagent run that reads an issue and posts two comments. It's valid JSONL, so the `jq` snippets execute against it directly.

---

## `attributionAgent` — which agent ran

This is the one most people reach for first, and the most reliable. Every `assistant` line inside a subagent trace carries `attributionAgent`, set to the subagent type that ran: `"pm"`, `"general-purpose"`, or a custom agent name. The value is the same string the parent recorded as `toolUseResult.agentType`, and the same one you passed as `subagent_type` in the `Agent` call. A run has one agent type, and it's stamped on every model turn the run took.

```bash
# Which agent produced each assistant turn?
jq -r 'select(.type == "assistant") | .attributionAgent // "(main loop)"' \
  anatomy-subagent-trace.jsonl | sort | uniq -c
#   8 pm
```

All eight `assistant` lines come back `pm`, because the fixture is a single `pm` invocation. The `// "(main loop)"` fallback is doing nothing here, but it matters the moment you point this at a parent session: there, `attributionAgent` is **absent**, and every main-loop turn falls through to `(main loop)`. That contrast is what makes the field useful: it partitions turns by which agent produced them, with the main loop as the implicit "no agent" bucket.

One caveat to carry into the next section: the observational scan behind the reference doc found `attributionAgent` on sidechain assistant lines **only** (10,291 sidechain, 0 main). So in practice its presence _does_ track subagent-ness. That's a property of how it's emitted, though, and it doesn't make the field a safe subagent test. More on why in a moment.

---

## `attributionMcpServer` / `attributionMcpTool` — which MCP tool

These two travel together (present as a pair or absent as a pair), and they appear only on `assistant` turns that interact with an [MCP](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#when-attributionmcpserverattributionmcptool-appear)-defined tool. Our `pm` run calls `mcp__github__get_issue` once and `mcp__github__add_issue_comment` twice, which makes three MCP turns out of eight, and exactly those three lines carry the pair:

```bash
# Which MCP server/tool did the MCP turns route through?
jq -r 'select(.type == "assistant" and has("attributionMcpServer"))
  | "\(.attributionMcpServer)__\(.attributionMcpTool)"' \
  anatomy-subagent-trace.jsonl | sort | uniq -c
#   2 github__add_issue_comment
#   1 github__get_issue
```

The other five `assistant` lines, the `Read`s and the final summary, **omit both keys entirely**. The keys aren't set to empty strings; they simply aren't on the line. So test with `has("attributionMcpServer")` rather than a truthiness check on the value.

What the pair gives you that the `tool_use` block doesn't is a _decoded_ form, pre-split at the top level. The call itself carries `name: "mcp__github__get_issue"` buried in `message.content`; the attribution pair lifts the `github` server and the `get_issue` tool out to the line's surface, so you can group turns by server or by tool without parsing the `__`-delimited name or walking into the content array.

One gap remains: the **exact** trigger condition is [still being verified](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#open-verification-items). Whether the pair lands on the assistant line that _emits_ the MCP `tool_use`, only on the turn that _follows_ an MCP `tool_result`, or on both, isn't yet disambiguated. Roughly half the assistant lines in a given MCP flow carry it. Treat it as "MCP-routing context is present when this turn touches an MCP server," and don't assume one-to-one with `tool_use` emission until that's nailed down.

---

## `attributionSkill` — and the trap

The fourth field has the same shape as the others. It's present on `assistant` lines and names the invoked Skill a turn ran under. One difference changes how you can use it.

**`attributionSkill` is not a sidechain signal.** Skills run in the main loop as well as inside subagents, so the field shows up in _parent_ sessions too. The scan behind the reference doc found it on both sides of the line: 4,785 sidechain assistant lines and 1,895 main-session ones. Compare that to `attributionAgent`'s clean 10,291 / 0 split: `attributionAgent` happens to be subagent-exclusive, and `attributionSkill` is not.

That makes for an easy trap to fall into:

> Don't decide "is this a subagent line?" by checking whether an `attribution*` field is present.

It seems reasonable. The fields cluster in trace files, so "has an attribution field" feels like "is a subagent line." But it's wrong two ways. `attributionSkill` appears on main-loop turns whenever a Skill is active, and the `attributionMcp*` pair appears on main-loop turns whenever an MCP tool is used outside a subagent. Branch on either and you'll tag ordinary main-session turns as subagent work.

The field that answers the question is `isSidechain`, the [canonical, content-free signal](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#the-issidechain-marker) Part 3 built its case around. **The attribution fields tell you _how_ a turn was launched; `isSidechain` tells you _where_ it lives.** Only the second is a subagent test.

---

## What provenance buys you

Because all of this sits at the top level of the line, you can attribute behavior and cost by origin without reparsing `message.content`. Each of these is a single top-level field filter:

- **Per agent.** Group `assistant` turns (or their `message.usage`) by `attributionAgent` to see which subagent type ran up the most turns or tokens. Part 4 gives the token side its full treatment, but the _grouping key_ is this field.
- **Per MCP tool.** Tally `attributionMcpServer` / `attributionMcpTool` to see which servers and tools a session leans on, and which subagents lean on them.
- **Per Skill.** Filter on `attributionSkill` to find every turn a Skill touched, across both the main loop and subagents. That same reach rules it out as a sidechain signal and makes it a complete Skill-usage view.

None of these needs the content array, because provenance lives in the harness bookkeeping layer and not inside the model's message.

---

## Try it on your own sessions

Point the agent grouping at a real session and its traces together. Main-loop turns fall into `(main loop)`; subagent turns report their agent type:

```bash
# Which agent produced each assistant turn, across a session AND its traces:
jq -r 'select(.type == "assistant") | .attributionAgent // "(main loop)"' \
  ~/.claude/projects/<slug>/<session-uuid>.jsonl \
  ~/.claude/projects/<slug>/<session-uuid>/subagents/*.jsonl \
  | sort | uniq -c
```

If you've run anything under a Skill recently, this next one makes the "not a sidechain signal" point concrete on your own data: you'll see `attributionSkill` values coming from the parent session file, not just the trace files:

```bash
# Every Skill-attributed turn, with which file it came from:
for f in ~/.claude/projects/<slug>/<session-uuid>.jsonl \
         ~/.claude/projects/<slug>/<session-uuid>/subagents/*.jsonl; do
  jq -r --arg f "$(basename "$f")" \
    'select(.type == "assistant" and has("attributionSkill"))
     | "\($f)\t\(.attributionSkill)"' "$f"
done
```

Both use defensive `?`-free `select` guards on `type`, so non-matching lines are skipped rather than raising. That's the same discipline as Part 2's snippets. They assume `jq` on bash or zsh.

---

## What's next

This aside doesn't change the through-line: Part 3 still hands off to [Part 4 — "Token accounting is harder than it looks"](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/.claude/specs/series-outline.md). If anything it sets the table for it. Once you can compute what a session cost, the natural next question is _whose_ cost: which agent, which tool, which Skill ran up the bill. The attribution fields are the grouping keys for that slice; Part 4 is the arithmetic.

This is verified against **Claude Code v2.1.150**, the same baseline as Part 3. The attribution family is exactly the kind of harness bookkeeping that evolves independently of the API message format, so if your own sessions show an attribution field or a trigger condition I haven't described, especially from the Agent SDK, that's the kind of thing that updates the [reference doc](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md) and sharpens later posts. Please open an issue in the repo.

The sources behind this post:

- **Reference grounding:** [`reference/subagent-traces.md` § Attribution fields](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/reference/subagent-traces.md#attribution-fields)
- **Synthetic fixture** — valid JSONL, so the `jq` snippets run against it directly: the [subagent trace](https://github.com/frederick-douglas-pearce/claude-code-sessions/blob/main/fixtures/synthetic/anatomy-subagent-trace.jsonl)

---

_Drafted with Claude Code (verified against v2.1.150). The ideas, claims, and any errors are mine._
