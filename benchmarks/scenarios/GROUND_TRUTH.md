# Real-world scenario testing — ground truth spec

Written BEFORE any trace was built, so results were checked against a
pre-committed expectation, not rationalized after the fact. Every waste
pattern below is constructed using the exact mechanics of the real
detector/convergence source (`src/wattage/detectors/*.py`,
`src/wattage/convergence/*.py`), not guessed — see `../adversarial_fixtures.py`
for the smaller, hand-labeled fixtures these scenarios build on top of at
much larger scale and complexity (multi-agent nesting, mixed providers,
many detectors firing simultaneously in one trace).

Embedder in use: default `local` mode, but `sentence-transformers` is NOT
installed in this environment, so it falls back to `HashEmbedder` (crude
character-4-gram cosine similarity). This is what a real out-of-the-box
`pip install wattage` user gets — the honest default to test against.

Pricing: anthropic claude-sonnet-4-6 (input 3.0e-6, output 15.0e-6, cache_read_mult
0.10, cache_write_mult 1.25, min_cacheable_prefix_tokens 1024), claude-haiku-4-5
(input 1.0e-6, output 5.0e-6), openai models per pricing.yaml — confirm exact
figures against the file when computing expected dollar amounts.

Reasoning tokens: confirmed against real provider docs (both OpenAI's
completion_tokens_details.reasoning_tokens and Anthropic's
output_tokens_details.thinking_tokens) that reasoning is billed as a
*subset* already included in the provider's raw output_tokens, not billed
separately on top. `span_builder.py`'s `chat_span(..., output_tokens=X,
reasoning_tokens=Y)` therefore expects `output_tokens` to be the raw,
reasoning-inclusive wire value -- `normalize.py` derives the *visible*
output (X - Y) and keeps `Y` as its own TokenUsage.reasoning field. The
per-call numbers below (e.g. "80 output tokens") are always this derived
visible amount, not the raw wire attribute in the .json fixture.

---

## Scenario 1 — E-commerce customer support multi-agent system

One session (`trace-cs-001`), one orchestrator + 3 nested specialist
sub-agents, all children of the orchestrator span (2-level nesting, 3
siblings — untested territory; existing test coverage is 1 nested agent,
no siblings).

**Task 0 — orchestrator** (direct calls, no loop since no tool/retrieval activity in it):
- 4 sequential chat calls classifying/routing the ticket, system-prompt-heavy
  (large stable prefix), none use cache_read → **prefix_churn** should fire
  (each call's input >= prior call's total, ratio should be high since this
  is the whole task's cost).
- One of the 4 calls: high reasoning tokens (900, > 500 ceiling) with small
  final output (80 tokens, <= 150 ceiling) → **reasoning_overspend** should fire.
- Expect: prefix_churn (medium/high depending on ratio), reasoning_overspend.
  Should NOT fire: nonconvergence (no loop at all in this task), retrieval_thrash,
  cache_gap, redundant_tool_calls, verbosity (all outputs are modest), model_mismatch
  (no --quality map supplied in the base run).

**Task 1 — billing-agent (nested, parent=orchestrator)**: a loop, 4 iterations,
ends in a final chat-only answer (reached_success=True):
- it0: check_invoice(id=INV-501) → "invoice found, total $84.20"
- it1: check_invoice(id=INV-501) → "invoice found, total $84.20" (SAME args,
  SAME result-ish) → **redundant_tool_calls** should fire (exact args match,
  window default 5 covers this).
- it2: apply_refund(id=INV-501, amount=84.20) → "refund applied"
- it3: chat-only final answer, no tool call → reached_success=True
- Expect: redundant_tool_calls fires. nonconvergence must NOT fire (loop
  reached success — doc §5.5 "never punish a loop that ultimately succeeded").
  This is a real cross-detector-independence check: redundant_tool_calls
  should still fire even though nonconvergence stays silent on the same loop.

**Task 2 — technical-agent (nested, parent=orchestrator)**: a genuine
THRASHING loop, 6 iterations, same tool every time, FLAT token cost
(no context growth), never recovers (last iteration still has a pending
tool call → reached_success=False):
- Every iteration: diagnose_connection(attempt=i) → "still failing: timeout
  on port 443" (near-identical unhelpful result each time; fuzzy arg i
  defeats exact-hash matching, same technique as the proven retry_same_failure
  fixture, scaled to 6 iterations instead of 5).
- input_tok held FLAT across iterations (e.g. 500 each) — the dimension
  that must distinguish this from Task 3's stalled pattern below.
- Expect: **nonconvergence** fires, subtype=**thrashing** (min_iterations=3
  satisfied, streak >= consecutive_k=3, trailing_oscillation stays 0 — same
  tool every time can never form a period>=2 cycle per canonical_action_symbol
  — and NOT stalled since growth_penalty should stay near 0 with flat input_tok).

**Task 3 — escalation-agent (nested, parent=orchestrator)**: retrieval_thrash
+ cache_gap + verbosity, 5 iterations:
- Every iteration: search_kb(query=<fuzzy variant>) → same/near-duplicate
  unhelpful boilerplate result ("no matching articles found") — 5 iterations,
  floor = max(2, max_iterations_soft=4) = 4, so need >=4 low-yield iterations
  out of >=4 retrieval iterations → **retrieval_thrash** should fire (severity
  high since ALL retrieval iterations are low-yield).
- Every LLM call in this task: cache_creation > 0 on the first call (attempting
  to cache the large tool-schema prefix), but cache_read = 0 on every
  subsequent call → **cache_gap** should fire (fully unredeemed, severity high
  since total_read == 0).
- The final iteration's chat call has a huge, uncapped final answer (1400
  output tokens, no max_tokens set) summarizing the failed escalation →
  **verbosity** should fire (1400 > 1000 ceiling; severity: 1400 < 3000
  (3x ceiling) → medium).
- This loop should NOT reach success (agent gives up, hands off to a human —
  last iteration still has a tool call pending) → check whether nonconvergence
  ALSO fires here (retrieval-only iterations with no distinguishing tool-name
  variety could plausibly also read as thrashing/stalled — this is an
  intentional stress point: does retrieval_thrash and nonconvergence correctly
  BOTH fire independently on the same underlying loop, or does one crowd out
  the other in some unexpected way?). Recorded as an open question to verify,
  not asserted in advance.

**Cross-task check**: sessionize.py must produce exactly 4 tasks (0
orchestrator + 3 nested), each nested task's `_descendant_call_ids` must
claim ONLY its own agent's calls, not leak into siblings or the parent.

**Model mix**: orchestrator + billing-agent use anthropic claude-sonnet-4-6;
technical-agent uses anthropic claude-haiku-4-5 (cheaper — legitimate use,
should NOT be flagged by anything); escalation-agent uses openai (whatever
model is in pricing.yaml) — tests mixed-provider pricing correctness in one
session.

**Run twice**: once with no `--quality` map (baseline), once with
`examples/quality.json`-shaped map covering this scenario's tool_select
steps, to verify model_mismatch's silence-by-default and evidence-gated
firing both work correctly at this scale.

---

## Scenario 2 — Autonomous coding agent, large multi-file refactor

One session, ONE task (a single top-level agent, no nesting — tests the
"no invoke_agent spans at all, single catch-all task" path at real scale),
ONE loop with **22 iterations** — far beyond the 4-6-iteration synthetic
fixtures, the main stress test of the convergence engine's cumulative
evidence/state computation over a long real trajectory.

- it0-4 (5 iterations): genuine exploration — list_files, read_file (3
  different files, genuinely different content each time), grep — mirrors
  the proven `multi_tool_pipeline`/productive pattern. Includes ONE
  deliberate exact repeat: read_file(path=config.py) called again with
  identical args later in this stretch → **redundant_tool_calls** should
  fire once.
- it5 (mid-exploration): a file-summary chat call with no max_tokens cap
  and 1500 output tokens → **verbosity** fires (medium, since 1500 < 3000).
- it6: a "which file is the bug in" decision call with 700 reasoning tokens
  and only 55 output tokens → **reasoning_overspend** fires (medium, since
  700 < 1500 = 3x ceiling).
- it7-20 (14 iterations): STALLED pattern at real scale — every iteration
  calls run_tests(attempt=i) (same tool, fuzzy arg), result is always
  "FAILED: 2 tests still failing" (near-identical boilerplate), input_tok
  EXPLICITLY GROWS each iteration (context accumulating failed-attempt
  history) — same proven technique as `growing_context_no_evidence`, scaled
  to 14 iterations instead of 5. Never recovers.
- it21: loop ends here, still mid-tool-call (no final chat-only answer) →
  reached_success=False.
- Expect: **nonconvergence** fires, subtype should be **stalled** (evidence
  and state both low, growth_penalty high across the trailing streak — the
  streak here is large, likely all 14+ of the it7-20 run since it0-6 should
  score above theta_prog individually). Open verification point: does the
  cumulative nature of evidence_gain (novelty vs. ALL prior info, not just
  the trailing window) get confused by the genuinely-novel it0-4 content
  sitting earlier in the same `prior_infos` list? Recorded to check, not
  pre-assumed.
- **prefix_churn**: the large tool-schema/system-prompt prefix gets resent
  uncached across most of these 22 turns → should fire, likely high severity
  given how much of a 22-turn task's cost this represents.
- Should NOT fire: cache_gap (no caching attempted at all — this is
  prefix_churn's territory, by the existing cache_gap docstring's own
  distinction), retrieval_thrash (no retrieval-like tool names used),
  model_mismatch (no --quality map in the base run).

---

## Scenario 3 — RAG research agent, deep nested sub-agents

One session, 3 levels of nesting (orchestrator → research-lead →
summarizer), PLUS 2 sibling research sub-agents at the research-lead's
level, PLUS orphan session-level calls outside any agent span. This is the
real stress test of sessionize.py's task-splitting at realistic depth/breadth
— existing coverage is 2 levels, 1 agent, no siblings.

**Orphan pre-processing** (outside any agent span, own catch-all task):
- 2 chat calls doing input classification, one with cache_creation > 0 and
  a same-session-later cache_read > 0 that DOES redeem it → should NOT
  trigger cache_gap (fully redeemed) or prefix_churn (cache_read present).

**Task — orchestrator** (parent=None): 3 direct calls delegating to
research-lead and reviewing its output; cache_creation > 0 on first call,
cache_read = 0 on all subsequent → **cache_gap** fires (fully unredeemed).

**Task — research-lead** (parent=orchestrator): itself invokes 2 SIBLING
research sub-agents (parallel-ish topics) — tests multiple siblings under
one non-root parent (deeper than the existing single-nested-agent test).
research-lead's own direct calls: a genuinely productive short exchange
(2 calls, different content, ends chat-only) — reached_success=True,
nothing should fire here.

**Task — research-sub-agent-A** (parent=research-lead): retrieval_thrash via
the `iteration.retrievals` (RetrievalCall) path specifically — NOT the
tool-name-heuristic path used in Scenario 1's escalation-agent, to cover
the other branch of `_is_retrieval_iteration`. 5 iterations of embeddings
calls (SpanKind.embeddings) with near-duplicate low-relevance chunk text →
retrieval_thrash should fire. This loop ends inconclusively (no final
success) → also check nonconvergence's behavior here (same open-question
pattern as Scenario 1 Task 3).

**Task — research-sub-agent-B** (parent=research-lead): genuinely
PRODUCTIVE nested loop (3 iterations, distinct real content each time,
different search queries, ends in a chat-only final answer,
reached_success=True) — the false-positive control: 3 levels deep should
NOT trip nonconvergence just because it's deeply nested.

**Task — summarizer** (parent=research-lead, so ALSO 3 levels deep from
orchestrator): a STALLED pattern (same technique as Scenario 2, 6
iterations, same "summarize_chunk" tool, growing input context, near-identical
short boilerplate outputs, never recovers) → nonconvergence should fire,
subtype stalled.

**Cross-task check**: expect exactly 6 tasks total (orphan catch-all +
orchestrator + research-lead + sub-agent-A + sub-agent-B + summarizer).
research-lead's own descendant-collection must correctly EXCLUDE both
nested sub-agents' subtrees from its own call list (per `_descendant_call_ids`'s
"don't recurse past a nested agent span" rule) while still including
them as separate sibling tasks of their own.

---

## What counts as a genuine finding worth recording

- Any crash, exception, or non-graceful failure on any surface (report,
  score, badge, ci, --html, --json).
- Any detector firing when the ground truth above says it shouldn't
  (false positive), or not firing when it should (false negative) —
  with the exact numbers checked, not just presence/absence.
- Any dollar or token figure that doesn't hand-check against the pricing
  registry / detector formulas above.
- Any task-boundary/nesting misattribution (a nested agent's calls leaking
  into the wrong task).
- Any convergence subtype that doesn't match the ground truth's expectation
  — and if it doesn't, whether the ACTUAL classification is nonetheless
  defensible on inspection (per the project's own fixture-labeling standard)
  even if it's not what was predicted, versus a genuine bug.
- Performance/scaling concerns at hundreds of spans (runtime, memory,
  HTML render size/usability).
- Anything the HTML flame graph renders wrong, illegibly, or misleadingly
  at this scale (visually verified, not just "it didn't crash").
- Any doc/behavior mismatch worth a documentation fix even if the code
  itself is technically correct (e.g., convergence.md's "different tool
  every time" stalled narrative vs. the actual same-tool-plus-growing-context
  mechanism the real classifier and fixtures use).
