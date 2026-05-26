# reference/

Canonical format documentation for Claude Code's JSONL session data.

This directory is the **source of truth**. Sibling projects ([AgentFluent](https://github.com/frederick-douglas-pearce/agentfluent), [CodeFluent](https://github.com/frederick-douglas-pearce/codefluent)) link here rather than duplicating field-level documentation in their own CLAUDE.md files.

## Documents

| File | Purpose | Status |
|---|---|---|
| `data-dictionary.md` | Every field, every message type | Skeleton |
| `format-version-history.md` | Observed format changes over time, tied to Claude Code versions | Not yet started |
| `subagent-traces.md` | The `subagents/` directory layout, sidechain pattern, `agentId` linking | Not yet started |
| `tool-invocation.md` | The `Agent` tool, `tool_use` / `tool_result` pairing, `toolUseResult` metadata envelope | Not yet started |

## Verification discipline

Every section that names a JSONL field carries a "Verified against Claude Code v<X>" header. When the format-watch skill identifies a change, the affected sections get re-verified and the version stamp updated.

This means reference docs are versioned at the section level, not the document level — a single doc may contain sections verified at different Claude Code versions.

## Relationship to posts

Posts in `../posts/` are the narrative layer. They tell stories, walk through examples, and motivate why fields matter. Reference docs are the lookup layer — terse, complete, and authoritative. A post that walks through subagent traces links to `subagent-traces.md` for the field-by-field detail.

## Relationship to sibling projects

AgentFluent's and CodeFluent's CLAUDE.md files contain JSONL format notes today. Over time, those notes migrate here, and the project CLAUDE.md files shrink to a link.
