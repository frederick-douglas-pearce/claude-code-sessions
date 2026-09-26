# Plan: #229 — docs(reference): stop_details is populated only on stop_reason "refusal", not "when available"

**Route:** docs  **Branch:** `fix/229-stop-details-refusal-only`

## Value framing (docs: who reads it / what it unblocks)

**Who reads it.** Anyone writing a parser against `assistant` lines — AgentFluent and CodeFluent
both walk `message.*`, and `reference/data-dictionary.md` is the field-level contract they link to
instead of re-documenting. Beyond the siblings, this doc is the repo's public answer to "what does
this field mean".

**What it unblocks.** Two things, one of them a live published-content debt:

1. A parser reading `stop_details` without guarding on `stop_reason` hits `null` on the
   overwhelming majority of assistant lines. The current row ("Additional stop information when
   available (rarely populated in practice)") describes that symptom and hides the rule that
   predicts it, so a reader cannot write the guard from the doc.
2. Part 5 shipped 2026-09-10 asserting `stop_reason` is an open enum with values the reference does
   not acknowledge. Until this lands, the published narrative layer is ahead of the source-of-truth
   layer, which inverts the repo's own rule. #226 then cites this row rather than restating it.

**Falsifier (discharged below, and it fired).** *What observation would show this is misdirected?*
If Anthropic's own docs did not support the refusal-only rule — if `stop_details` really were
populated opportunistically — the correction would be inventing a contract. **Checked. It holds,
and the check also found the issue itself is wrong in three places.**

## Source-fidelity check (DISCHARGED at plan time — this is the load-bearing step)

#229's entire rationale is "the Messages API contract", with no scan behind it, so the issue's
claims were checked against primary Anthropic documentation before any of them were written into
the source-of-truth doc. Sources:

- [Stop reasons and fallback](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
- [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback#refusal-response)
- [Using the Messages API](https://platform.claude.com/docs/en/build-with-claude/working-with-messages)
- The bundled `claude-api` skill's Stop Details reference

**Confirmed — the issue's central correction is right, verbatim:**

> "`stop_details` itself is `null` for every stop reason other than `refusal`."
> — Refusals and fallback

Stated twice, independently (handling-stop-reasons says the same). The refusal response shape is
documented literally as `{"type": "refusal", "category": "cyber", "explanation": "..."}`.

**Three places the issue is WRONG or incomplete. These are corrections to #229, not to the doc:**

| # | #229 says | Primary docs say |
|---|---|---|
| 1 | "The API defines six: `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`, `pause_turn`, `refusal`" | **Seven.** There is also **`model_context_window_exceeded`** — "The response filled the model's context window." Writing "six" into the reference would ship a closed enum that is already wrong. |
| 2 | `stop_details` carries "`type`, `category`, and `explanation`" | **Four sub-fields.** Also **`recommended_model`** — present only on requests that set `fallbacks` (beta), naming a model to retry when the API skipped the fallback attempt; `null` otherwise. |
| 3 | category is "an open set: `"cyber"`, `"bio"`, `"reasoning_extraction"`, `"frontier_llm"`, or `null`" | Five named categories, not four — it omits **`"general_harms"`**. |

**One claim I could NOT verify, and will not assert.** #229 asks to document that for
`stop_sequence` "the matched string is excluded from the generated content." Anthropic's own docs
say only that `stop_sequence` "will contain the matched stop sequence" and to "read `stop_sequence`
to see which one fired" — the exclusion behavior is stated by third-party sources but **nowhere in
primary Anthropic documentation I could find.** Writing it in would be the reference doing exactly
what this repo's rules forbid: asserting a contract past what its source establishes. Handling is a
question for the plan gate (see Risks).

**One further find, worth recording:** on a refusal the docs' example shows `content: []` and
`output_tokens: 0`. Relevant to any consumer summing tokens or reading content blocks off an
assistant line, and it costs one clause.

## Acceptance criteria (verbatim from issue #229 § Scope)

- [ ] Rewrite the `stop_details` row around the `refusal`-only rule, and name the sub-fields.
- [ ] Widen the `stop_reason` row to the full enum, framed as open rather than closed.
- [ ] Add the `stop_reason` coupling and the excluded-string behavior to the `stop_sequence` row.
- [ ] Re-check the section's **Verified against Claude Code v2.1.170** note. These are API-layer
      semantics rather than harness fields, so the version note may need different wording, or a
      pointer to the Messages API docs as the upstream source.

Out of scope (verbatim): "Any scan work. All three corrections come from the Messages API contract,
not from session data, so nothing here needs a corpus pass. #226 owns the scan-backed half."

## Approach

One file, three rows plus one note. `reference/data-dictionary.md`, lines 95-97 and the § `assistant`
version note at line 83.

1. **`message.stop_reason` (line 95)** — replace "Common values: ..." with the full documented enum
   of **seven**, framed as open ("the set has grown over time; treat an unrecognized value as one
   you have not seen yet, never as malformed"). Mirrors the framing `tool-invocation.md` already
   uses for tool names, so the two docs read consistently. Note which two the sessions in this repo
   actually carry, and point at `tool-invocation.md` for the observed distribution once #226 lands.
2. **`message.stop_sequence` (line 96)** — add the coupling (non-null only when `stop_reason ==
   "stop_sequence"`) and that it holds the caller-supplied string from the request's
   `stop_sequences` array, so it disambiguates *which* sequence fired.
   **AC-3 ruling (human, at the plan gate): verify the exclusion behavior empirically**, then
   document the observed result. **BLOCKED on credentials** — this environment has no `ant` CLI, no
   `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`, and no `~/.config/anthropic` profile, so the call
   cannot be made from here. Everything else in this plan is independent of it, so the row ships
   with its verified half and the exclusion clause is held as the single open item until the probe
   runs.
3. **`message.stop_details` (line 97)** — rewrite around the refusal-only rule. Name all four
   sub-fields, give the five categories plus `null`, and record that `category`/`explanation` are
   "a normal, permanent value, not a placeholder" when `null`. Add the parser guard explicitly.
   Type becomes `object | null`, since `null` is the value on every non-refusal line.
4. **The § `assistant` version note (line 83)** — do **not** restamp. The v2.1.170 stamp is correct
   for what it describes (the API-error markers re-verified then), and these three rows were never
   verified against a Claude Code version at all — they are API-layer semantics. Add a scoped
   sentence naming the Messages API as the upstream source for the `stop_*` rows, with the doc
   links and the date checked. This answers #229's bullet 4 and #231's overlap without restamping a
   number that "does not describe what was checked" (#229's own comment).
5. Run `npx prettier reference/data-dictionary.md --check`, fix, commit, PR.

**Files to touch:** `reference/data-dictionary.md` only. No fixtures, no tooling, no posts.

## Architect triggers hit

**None — but the call is closer than the route suggests, so it is recorded rather than assumed.**

`ARCHITECT_TRIGGERS` fires on "a new reference-doc contract that AgentFluent or CodeFluent will link
to (a field definition's meaning)", and this does change a field definition's meaning. It is also
squarely inside the skip list: "`reference/` prose that documents an already-verified field."

Skipping, because the risk here is **factual, not architectural** — and the factual check is the one
that has already run. `DESIGN_AGENT` has Read/Grep/WebFetch/WebSearch and would be asked to
second-guess a claim now backed by two Anthropic doc pages quoting the rule verbatim. There is no
interface design decision in scope: no new section, no new cross-doc contract, no change to how the
siblings consume the doc. The three corrections the gate might plausibly have caught were caught by
the source-fidelity pass instead, which is the check actually suited to them.

## Risks / open questions for human

1. **AC-3 cannot be met as written.** It asks for "the excluded-string behavior", which primary
   Anthropic docs do not state. Three options, my recommendation first:
   - **(a) Deliver AC-3 partially and say so** — write the verified half (the `stop_reason`
     coupling, the caller-supplied string, the disambiguation purpose), omit the exclusion claim,
     and note on #229 that the removed clause was unverifiable. **Recommended.** This is an AC
     *reduction*, which the engine says is an issue amendment, not something the gate absorbs — so
     it needs your call, not mine.
   - (b) Assert it anyway, sourced to third-party docs. Cheap, and against this repo's whole point.
   - (c) Verify empirically with a live API call using a stop sequence. Definitive, costs a
     request, and is arguably the "scan work" #229 puts out of scope.
2. **#229's "six" is wrong, and Part 5 inherits it.** The published post names `max_tokens`,
   `pause_turn`, `refusal` as the additions and does not mention `model_context_window_exceeded`.
   Part 5 hedged ("that list has grown over time, so read `stop_reason` as an open enum"), so it is
   incomplete rather than false, and the reference will now carry all seven. Flagging because
   reconciling post against reference is #226's job and this is a fact #226 will need.
3. **The issue body will be stale once this merges** (six vs seven, three sub-fields vs four, four
   categories vs five). I plan to comment the corrections on #229 so the record is not misleading.
   Say if you would rather I edit the body.
