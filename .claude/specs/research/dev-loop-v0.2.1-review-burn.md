# Reducing review burn in dev-loop — input for v0.2.1

**Source:** a dogfooding run of `dev-loop@claude-code-loop` **v0.2.0** in
[`claude-code-sessions`](https://github.com/frederick-douglas-pearce/claude-code-sessions),
issue #194 (+#199), PR #200, squash-merged as `b8c2b0c` on 2026-08-23.

**Problem being addressed:** the code-review gate consumed most of the run's tokens, and the last
two rounds found no defect that changed shipped behavior. Nearly everything they returned was prose:
stale counts, retracted claims surviving in a second location, unqualified closure statements. This
is a persistent pattern across iterations, not a one-off.

This document is a diagnosis plus concrete proposals. Numbers are measured from the run, not
estimated.

---

## 1. What the run actually cost

Five code-review rounds, three architect passes, one security pass, one acceptance pass (plus one
that died with no verdict), and one human escalation. For a single issue.

Subagent token spend visible in the orchestrator's final context window. Rounds 1 to 3 were
compacted away, so the real total is higher:

| pass                             | tokens         |
| -------------------------------- | -------------- |
| round 4, five independent reviewers | ~688k       |
| round 5, `/code-review`          | 137k           |
| architect ×2                     | 160k           |
| security review                  | 100k           |
| AC-verify (plus one failed attempt) | 124k+       |
| **visible total**                | **~1.21M**     |

### What round 4's ~688k bought

Round 4 ran five reviewers with distinct lenses. Its output:

- **3 findings that changed shipped behavior.** All three came from **one** reviewer, the
  mutation-testing lens: three invariants the code asserted in prose that no test checked. Each
  mutant survived the entire 497-test suite.
- **2 further real defects** from the correctness lens: a UUID-graph gap (filed as #202) and a CI
  diagnostic that could never print (GitHub Actions runs steps as `bash -e {0}`, and
  `set -uo pipefail` does not clear the inherited `-e`).
- **2 BLOCKING findings**, both false claims in the **PR body**.
- **~8 documentation nits**: stale counts, wording that overclaimed coverage.

So the durable value concentrated in two of five lenses. The other three produced accurate,
well-argued findings with low value density. They were not wrong. They were being paid at
review-round prices for work that does not need a round.

### The recurring defect class

The single most repeated defect across the whole run was **a claim retracted in one place surviving
in another**:

- The retracted golden-determinism claim recurred **four times**: twice in the CHANGELOG, once in
  the PR body, once in the PRD.
- The "human review covers that gap" wording recurred **four times** across `pipeline.py`, a test
  module, and the PRD.
- Stale counts: six `57`s, two `30`s, one `~14`, each describing the code one revision back.
- **Twice, a false claim shipped inside the commit whose stated purpose was removing false claims.**

Every one of these cost a full review round plus a commit.

---

## 2. Diagnosis

The engine treats **"the gate returned findings"** as a single state. A false comment and a silent
PII leak both re-arm the gate, both cost a full re-read of the entire diff, and both make the next
commit uncertified under the currency clause.

Three consequences follow, and all three fired in this run:

1. **Prose findings buy full review rounds.** Rounds 3 and 5 existed almost entirely to catch
   wording. Round 5's own verdict explicitly cleared the core implementation.
2. **Fixing a prose finding invalidates the gate that found it.** Four of this branch's commits
   declared "no behavior change; comments, spec and changelog only." Each one re-opened the currency
   question and forced the orchestrator to argue at the merge gate why a verdict on `d5011a0`
   covered `f09146f`.
3. **Every round is a full re-read.** Rounds 2 through 5 each re-ingested the whole PR. That is
   where most of the tokens went. The Fresh-re-check invariant requires a *fresh instance*, not a
   *full re-read*, and the engine currently conflates the two.

The human had to intervene by hand mid-run to impose the missing rule ("docs or testing nits are not
sufficient to block"). That should be the engine's default, not a human patch.

---

## 3. High-leverage proposals

### P1. Severity-gated re-arming

Split gate findings into two classes and let only one re-arm a round.

- **BLOCKING** — correctness, security, test efficacy (a test that cannot fail), acceptance-criteria
  coverage, anything that moves a safety boundary.
- **EDITORIAL** — prose, stale counts, naming, doc drift, comment accuracy, changelog wording.

BLOCKING re-arms the gate as today. EDITORIAL findings accumulate in the ledger and are applied in a
**single editorial sweep** before the merge gate, and are **not re-reviewed**. The reviewer that
found them already told you what to write.

Require the gate agent to emit the class per finding rather than having the orchestrator infer it.
Inference by the author is exactly the judgment the gate exists to remove.

*Evidence:* this rule alone would have collapsed rounds 3 and 5 entirely and shrunk round 4's fix
cycle. Rounds 4 and 5 found zero core-implementation defects between them.

*Failure mode to guard:* an orchestrator under budget pressure will want to misclassify a real
finding as EDITORIAL. Two cheap guards. The gate agent, not the orchestrator, sets the class. And a
finding touching a file matching the repo's declared safety-relevant paths cannot be EDITORIAL.

### P2. A docs-only delta must not re-arm the code-review gate

If the diff since the last verdict touches only comments, docstrings, and markdown, the verdict
carries forward. Journal it explicitly ("verdict on `<sha>` carried to `<sha>`; delta is
comments-and-markdown only, `git diff --stat` attached").

This kills the regress where fixing a doc nit invalidates the gate that found it, which is what
turned this run's tail into three extra rounds.

Implementation is mechanical: classify the delta by file extension plus a comment-only check on
source files. No model needed.

### P3. Delta-scoped re-checks

- **Round 1** gets the full diff and the full lens set.
- **Rounds 2+** get the previous round's findings, the diff *since that round*, and one narrowed
  question: are these findings discharged, and does the new delta introduce anything?

Escalate back to a full review only if the delta exceeds a threshold of non-doc change, or if a fix
touched a safety-relevant path.

*Evidence:* rounds 2 through 5 each re-read the entire PR. Round 5 cost 137k tokens to re-read a
diff whose only change since round 4 was three test guards and a batch of comments.

### P4. Weight the lens allocation by value density

If a round is capped at N agents, spend them where findings historically land.

- Make **one mutation-testing lens mandatory** on any diff touching a repo-declared safety-relevant
  path. It was the only lens in this run that found unguarded invariants, and it found three.
- Collapse prose auditing into **one low-effort lens**, not three.

Mutation testing found what four rounds of reading did not. That is a strong enough signal to
promote it from "a lens the orchestrator might choose" to "a lens the engine requires."

---

## 4. Two mechanical checks worth building

These kill the dominant defect class without a model in the loop.

### M1. Twin-retraction detection

For each line the diff **deletes or rewrites** that is longer than roughly eight words, fuzzy-grep
the rest of the repo, plus the PR body, for a near-duplicate. Surface hits at commit time.

A twenty-line script. Runs in milliseconds. **It would have caught all four recurrences of the
retracted golden-determinism claim and all four of the "human review covers that" wording**, before
any reviewer saw them. Those eight instances collectively cost several review rounds.

The reason the model kept missing it is structural, not a competence gap: when you retract a claim in
file A, nothing prompts you to look for its twin in file B, and the reviewer reading the diff sees
only file A.

### M2. Counts in prose must be derived or pinned

Numbers describing code went stale three times in this run (30 → 29, 14 → 19, 57 → 79). The fix that
worked was a test asserting the docstring's count matches `len(CELLS)`.

Encode it as a step-6 convention: a count in a comment or docstring must either be computed at
runtime or pinned by a test. A lint that flags bare integers adjacent to count-words
(`entries`, `cells`, `positions`, `tests`, `paths`) in docstrings gets most of the way there, and
the false-positive rate is tolerable if it only runs on the diff.

The complementary move is rhetorical, worth saying in the engine's authoring guidance: prefer
wording that cannot go stale. "Every placement assertion" never needs updating. "All 57 placement
assertions" needs updating every time.

---

## 5. Smaller engine fixes surfaced by the same run

### S1. Gate agents need budget sequencing

The first acceptance-gate verifier spent its entire budget building mutation scaffolding and died
with **no verdict at all**, which is strictly worse than a shallow one. Under the gate-outcome
invariant that correctly counts as not-passed, so the whole pass was wasted.

One line in the gate prompt template fixes it: *produce the complete verdict on every criterion
first, then deepen with whatever budget remains. Never let deepening prevent you from returning a
verdict.* The re-spawn with that instruction returned a complete ten-criterion verdict.

### S2. Binding resolution needs a disambiguation step

`loop.config.md` bound `CODE_REVIEW` to `/code-review`. One failed invocation string
(`Skill(skill="code-review:code-review")` → "Unknown skill") was enough for the orchestrator to
declare the binding uninvocable and fall back to the engine's inline composition: five hand-authored
reviewers. The correct invocation was the bare name, `Skill(skill="code-review")`.

The fallback is not equivalent. It substitutes the orchestrator's own authored prompts on the one
gate whose entire value is independence from the author. The rule should require probing the obvious
variants and checking the command exists on disk before concluding a binding is unavailable.

Related: a substituted gate should be journalled under its real identity, so a later reader comparing
four "code-review" verdicts can see that three had different provenance than the fourth.

### S3. The authoring tripwire must cover every surface, not just the diff

The engine's step-6 rule ("a claim that a protection exists must name it, and the name must resolve")
governs claims written into code and docs, and assigns enforcement to the step-8 finders. Two gaps:

- **It needs a self-check before the commit boundary, not only a finder check after it.** The
  finders caught claim drift on three consecutive rounds, and each catch cost a full review round
  plus a commit, because nothing prompted the author to re-read its own added prose against the code
  before staging. Same shape as the existing "walk the acceptance criteria once and name a
  `file:line` for each" tripwire, applied to prose.
- **It stops at the diff.** The two other surfaces the orchestrator writes are the **report to the
  human** and the **ledger**, and those are the surfaces the human actually reads. The ledger is what
  a later invocation resumes from, so a false claim there outlives the run. The tripwire should read
  "every factual assertion you write, in any surface", not "every assertion you add to the diff."

The **PR body** deserves specific mention. Both of round 4's BLOCKING findings were in it. It is
written once, never re-scanned when a claim is retracted elsewhere, and it becomes the squash-merge
commit message, so a false claim there is what the repo's history permanently records.

### S4. Findings ledger with stable IDs and status

Track findings across rounds with IDs and a status field including `declined-with-reason`. Round N+1
receives the ledger so it cannot re-raise a settled item. Cheap insurance, and a prerequisite for P1
and P3 anyway.

### S5. Instrument it

Record per-round token spend and finding counts by severity in `progress.md`. Then "was that round
worth it" stops being a judgment call and becomes a number. Everything in this document required
hand-scraping the transcript to establish.

---

## 6. A config knob worth having

```
PROSE_REVIEW: strict | normal | off
```

Repos differ enormously in comment density. This one uses unusually dense explanatory comments, which
is a deliberate and valuable choice, but it means every commit adds a large assertion surface, and
every assertion is a potential defect. A repo should be able to say "comment accuracy is checked at
commit time by M1 and M2, not at review time by a model."

`normal` would be the default: prose findings are reported but classified EDITORIAL per P1.

---

## 7. What I would not do

- **Do not cap the number of rounds lower.** The 2-round cap already has the right shape. The problem
  is not that rounds are too many, it is that a round is too expensive and too coarse. Cutting the
  count without P1 through P3 just ships the prose defects.
- **Do not drop the Fresh-re-check invariant to save tokens.** It earned its place emphatically in a
  prior iteration: the round-2 checker found that the *fix round itself* had introduced a silent PII
  leak the author could not have caught, because it was the author's own design. Scope the re-check
  (P3), do not weaken who performs it.
- **Do not solve this by telling reviewers to report fewer prose findings.** They were right every
  time. The finding is worth having. What is wrong is that having it costs a round.

---

## 8. Caveat

Part of this is authoring discipline, not engine design. Nothing in the engine made the orchestrator
write claims it had not verified. But the engine decides whether that failure is caught for ~500
tokens at commit time or ~690k at review time, and right now it chooses the expensive one.

The measured shape of this run is the argument: **the two cheapest possible checks (M1, M2) would
have prevented the majority of what the two most expensive rounds found.**
