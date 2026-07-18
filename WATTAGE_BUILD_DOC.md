# Wattage — Complete Build Documentation

> **Wattage** is a Kill‑A‑Watt meter for your AI agents. It's an open‑source **token‑spend profiler and cost‑regression gate** that reads OpenTelemetry GenAI traces, tells you *exactly where your tokens are being burned and wasted*, quantifies the dollar cost of each waste pattern, prescribes the fix, and fails your CI when a change makes your agents more expensive. Its standout feature is a **convergence engine** that catches agents thrashing in non‑productive loops — the failure mode shallow loop‑guards miss. Runtime enforcement (killing waste in‑flight) is Phase 2.

**Tagline:** *See where your tokens burn. Stop paying for it.*

---

## 0. How to use this document

This is a build specification detailed enough to hand to an engineer (or to Claude Code) and implement end‑to‑end. It is opinionated and concrete: it contains data models, algorithms in pseudocode, module interfaces, CLI/config schemas, a GitHub Action, a benchmark plan, and a go‑to‑market plan.

Read order: skim §1–§3 for the "what and why," then §4–§6 (the detectors, the convergence engine, the score — the intellectual core), then build from §7 onward. §13 (benchmark) and §14 (GTM) are what turn a good tool into a *viral* one; don't skip them.

Status of external facts: market statistics cited are from public reporting (mid‑2026) and are attributed inline. Provider **pricing and caching numbers change** — they are treated as *data* (a versioned registry, §7.5) and must be verified against provider docs at build time, never hardcoded as gospel. Where this doc gives "typical savings," those are observed ranges from public write‑ups, not guarantees.

---

## 1. Executive summary

Per‑token prices are falling fast, yet total AI spend is *rising* fast — because agentic workloads consume orders of magnitude more tokens than chat. This is Jevons' paradox: cut the unit price 75% while consuming 250× more tokens per task and you pay more, not less. The market reaction in 2026 has been panic — Uber burned its entire annual AI‑coding budget in four months (TechCrunch); JPMorgan circulated a note whose title was, roughly, that token costs are eating internet profits alive; Microsoft/Stanford research put agentic tasks at ~1,000× the token draw of standard chat.

The tooling that exists splits into three camps with a precise gap between them:

- **Observability** (LiteLLM, Helicone, Langfuse, Braintrust) tells you *how much* and *where the spans are*. As one honest 2026 buyer's guide put it, these surface waste but don't act — you pair them with another tool to fix anything.
- **Compression** (Headroom, ~30k★) statically squeezes context at the proxy. Powerful, but it's a hammer — it doesn't tell you *why* you're bloated or whether the fix held.
- **Shallow loop‑guards** (SHA‑256 duplicate detection, `smartMaxTurns`, debounce hooks) catch exact‑repeat tool calls but miss fuzzy thrash and semantic non‑progress.

Nobody owns the **diagnosis‑and‑prescription layer** between "here's your bill" and "here's a compressor." Wattage is that layer. It consumes the now‑standard **OpenTelemetry GenAI semantic conventions** (`gen_ai.*` spans that every major vendor maps to), so it works with anything that emits traces — no lock‑in, local‑first. The signature output is a **flame graph of token spend** plus a ranked, dollar‑quantified list of named waste patterns with fixes, a single **Token Efficiency score**, and a **CI gate** that catches cost regressions in pull requests before they hit the invoice.

The moat is depth in the *detectors*. The hard part isn't the plumbing (OTel gives you spans); it's the logic that decides "this loop stopped making progress" or "this retrieval wasn't worth its tokens." That logic is exactly what a researcher working on convergence‑aware orchestration and SLO‑aware retrieval already knows how to build.

---

## 2. Problem & opportunity

### 2.1 The mechanism (why cheaper tokens → bigger bills)

A 2024 chat interaction was ~2k tokens: prompt in, answer out. A 2026 agentic task decomposes a goal, retrieves context, calls tools, validates outputs, and retries — every step burns tokens, and context is *re‑sent* on every turn. EY illustratively puts a simple 2023 workflow at ~$0.04/interaction vs ~$1.20 for a 2026 orchestrated agent (~30×). Goldman Sachs Research projects token consumption multiplying ~24× to ~120 quadrillion/month by 2030, driven by always‑on enterprise agents.

### 2.2 Where the money actually goes (the addressable waste)

Independent audits converge on a small number of dominant, *fixable* waste patterns:

- **Re‑sent context is ~62% of the agent bill.** Corroborated by LeanOps (30‑team audit) and Cockroach Labs. Mostly fixable with prompt caching, which is **off by default in most frameworks**.
- **Prompt caching is dramatically underused.** ProjectDiscovery raised cache hit rate from 7% → 84% and cut costs 59%. Anthropic caching is a ~90% discount on cache reads.
- **Retrieval thrash / context bloat.** On hard queries, retrieval iterations spike (p95 6+ vs median 1–2) and context grows faster than useful evidence (Towards Data Science).
- **Non‑convergent loops.** Agents retry the same failing action or oscillate between two approaches until a hard `max_iterations` cap stops them, burning tokens on every iteration.
- **Model mismatch.** 60–70% of agent calls suit a smaller/cheaper model (public routing guidance).
- **Output verbosity.** Output tokens cost ~4–6× input; models over‑generate without tight `max_tokens`/format constraints.

### 2.3 The gap Wattage fills

Observability reports *that* cost changed; compression *changes* it bluntly; nobody explains the *mechanism* of waste in named, quantified, prescriptive terms and then *guards against regressions*. A representative OTel write‑up frames the invisible failure precisely: an agent using 50,000 tokens for a question that normally takes 3,000 is misbehaving — looping or re‑reading context — and *without per‑span accounting it's invisible*. Wattage makes it visible, priced, and preventable.

### 2.4 Non‑obvious tailwind: the standard exists now

The OpenTelemetry **GenAI Semantic Conventions** (GenAI SIG, since 2024; agent/tool spans + token‑usage metrics standardized through 2026, still "Development" status but adopted by Datadog, Honeycomb, Grafana, Langfuse, OpenLLMetry/traceloop, OpenInference). This means a *portable analysis layer* on top of traces is finally buildable without per‑vendor adapters — and Wattage can help push the convention forward (proposing waste‑oriented attributes upstream is a credibility play).

---

## 3. Product overview

### 3.1 What Wattage is (and is not)

**Is:** a diagnostic + gate. Point it at a trace (file, OTLP endpoint, or live tail), get (a) a prioritized, dollar‑quantified **diagnosis** of waste with fixes, (b) a shareable **efficiency score + flame graph**, (c) a **CI check** that fails PRs on cost/efficiency regressions.

**Is not (v1 non‑goals):**
- Not another observability dashboard (it *consumes* your existing telemetry; it doesn't replace Langfuse/Helicone).
- Not a proxy/gateway (it doesn't sit in the hot path in v1; runtime enforcement is opt‑in Phase 2).
- Not a compressor (it recommends and *simulates* fixes; it doesn't silently rewrite your prompts). "A failed cost gate should trigger investigation, not automatic prompt trimming" (QASkills).
- Not a model host or router (it flags routing waste; it doesn't route in v1).

Keeping the wedge sharp — **diagnosis + prescription + gate + score** — is existential. If Wattage tries to become a full platform, it dies.

### 3.2 The three surfaces

1. **Profiler / diagnosis report.** For each trace or batch: named findings (`prefix_churn`, `cache_gap`, `retrieval_thrash`, `nonconvergence`, `redundant_tool_calls`, `verbosity`, `model_mismatch`, `reasoning_overspend`), each with severity, wasted tokens, wasted dollars, an evidence snippet, a prescribed fix, and a *quality‑risk* flag. Ranked by dollars wasted.
2. **Efficiency score + flame graph.** A single 0–100 **Token Efficiency** grade (A–F) and a self‑contained HTML **flame graph** ("burn map") showing exactly where every token went — by session → step → span → category (system prompt, re‑sent history, retrieved context, tool I/O, reasoning, output). This is the screenshot people post.
3. **CI gate + badge.** `wattage ci` fails a PR when cost/efficiency regresses past thresholds vs a committed baseline, posts a PR comment with the per‑detector delta, and updates a README **badge** (`Token Efficiency: A · $2.4k/mo est. waste ↓`).

### 3.3 Target users & jobs‑to‑be‑done

- **AI/platform engineers** shipping agents: "Tell me why my agent is expensive and how to fix it" + "Don't let a teammate 3× the bill in a PR."
- **Eng leaders / FinOps**: "Give me a defensible, per‑team efficiency number and trend, not just an invoice."
- **OSS/indie devs**: "Run one command, get a beautiful report I can share."

### 3.4 Positioning vs. existing tools

| Capability | Langfuse/Helicone (observability) | Headroom (compression) | Loop‑guards | **Wattage** |
|---|---|---|---|---|
| Per‑span token/cost visibility | ✅ | ❌ | ❌ | ✅ (consumes theirs) |
| Names *specific* waste patterns | ❌ | ❌ | partial | ✅ |
| Quantifies $ per waste pattern | ❌ | ❌ | ❌ | ✅ |
| Prescribes fixes | ❌ | n/a (is a fix) | ❌ | ✅ |
| Quality‑aware (cost↔quality) | ❌ | ❌ | ❌ | ✅ |
| Semantic non‑convergence detection | ❌ | ❌ | ❌ (exact‑match only) | ✅ **(standout)** |
| CI regression gate + badge | partial (some) | ❌ | ❌ | ✅ |
| Framework‑agnostic via OTel | varies | proxy | per‑framework | ✅ |
| Runtime enforcement | ❌ | ✅ (blunt) | ✅ (blunt) | ✅ Phase 2 (smart) |
| Local‑first / no lock‑in | varies | ✅ | ✅ | ✅ |

### 3.5 Design principles

1. **Diagnosis over dashboards.** Every output ends in a *decision* (fix X, save $Y) or a *gate* (pass/fail).
2. **Ride the standard.** OTel GenAI semconv is the substrate; never invent a competing schema.
3. **Local‑first, private.** Runs offline on a trace file; no data leaves the machine unless the user opts into an LLM‑judge or hosted report.
4. **Quality is a first‑class axis.** Never recommend a saving that isn't quality‑checked. Cheaper ≠ better.
5. **Estimate, don't butcher.** Simulate savings; let a human/eval approve. Auto‑enforcement is opt‑in.
6. **Extensible by design.** Detectors are plugins; the community adding detectors is the growth flywheel.
7. **Fast, one‑liner wow.** `pipx run wattage report trace.json` → gorgeous output in seconds.

---

## 4. The Waste Taxonomy (the detectors)

This is the heart of Wattage. Each detector consumes a normalized session (§7.4) and emits zero or more `Finding`s. Detectors are independent, individually toggleable plugins.

**Overview:**

| ID | Detects | Primary OTel signal(s) | Prescribed fix | Typical observed savings |
|---|---|---|---|---|
| `prefix_churn` | Re‑sent context not being cached | prompt token growth across turns; absent `gen_ai.usage.cache_read_input_tokens` | Enable prompt caching on stable prefix | up to ~62% of bill is re‑sent context |
| `cache_gap` | Cacheable prefix present but cache unused/misconfigured | cache_read≈0 while stable prefix ≥ min cacheable size | Configure cache breakpoints/TTL | reads discounted ~90% |
| `retrieval_thrash` | Retrieval iterations spike without evidence gain | `execute_tool`/retrieval spans per task; context growth vs distinct evidence | Cap iterations; tighten retrieval; SLO‑gate | RAG right‑sizing 70–80% context cut |
| `nonconvergence` | Loop keeps going without progress (thrash/oscillation/stall) | successive tool calls/results; plan/state deltas | Add convergence stop; fix ambiguous tool state | catch after 3–4 vs 60 iters |
| `redundant_tool_calls` | Duplicate/near‑duplicate tool calls | normalized tool name+args fuzzy hash within window | Debounce/memoize tool results | eliminates repeats |
| `verbosity` | Output over‑generation | output/input ratio; `max_tokens` unset; format not constrained | Set `max_tokens`; request structured output | output costs 4–6× input |
| `model_mismatch` | Over‑powered model for a simple step | model tier vs step complexity heuristic | Route simple steps to cheaper model | 60–95% on routed calls |
| `reasoning_overspend` | Excess reasoning/thinking tokens | `gen_ai.usage.reasoning_tokens`; `reasoning_effort` | Lower reasoning effort where unneeded | model/step dependent |

Each detector spec below uses the same shape: **Definition → Signals → Algorithm → Severity → Fix → Savings → False‑positive guards.**

### 4.1 `prefix_churn` — re‑sent context (the 62% detector)

- **Definition.** Across turns of a session, a large, mostly‑identical prefix (system prompt + tool schemas + early history) is re‑sent and re‑billed as fresh input because caching isn't in effect.
- **Signals.** Per‑LLM‑call `gen_ai.usage.input_tokens`; presence/absence of `gen_ai.usage.cache_read_input_tokens` / `cache_creation_input_tokens`; the input message arrays (if content capture enabled) or a per‑call prefix fingerprint (rolling hash of the stable head).
- **Algorithm.**
  1. Order LLM calls in the session by start time.
  2. For each adjacent pair, compute the **longest common prefix ratio** of their input token streams (approximate via message‑boundary hashing when content is available; else via input‑token deltas + turn structure).
  3. Sum tokens in the re‑sent stable prefix across turns → `resent_tokens`.
  4. If `cache_read_input_tokens ≈ 0` on those calls, the re‑sent tokens were billed at full input price → recoverable.
- **Severity.** Proportional to `resent_dollars / session_dollars`. High if > 30%.
- **Fix.** Enable provider prompt caching on the stable prefix; move volatile content to the tail; ensure prefix ≥ provider min cacheable size (e.g., 1,024 tokens on current Sonnet/Opus tiers — verify per registry).
- **Savings.** `savings ≈ resent_tokens × input_price × (1 − cache_read_multiplier)` (cache reads ~10% of input ⇒ ~90% of the re‑sent cost is recoverable). Report both tokens and $.
- **Guards.** Don't flag if caching is already active (cache_read present) or prefix is genuinely volatile; account for provider min‑prefix and TTL windows (short sessions may not benefit).

### 4.2 `cache_gap` — caching present but ineffective

- **Definition.** The prefix is cacheable and stable, but cache reads are near zero (misplaced breakpoints, TTL too short, prefix below minimum, cache key busted by a volatile token near the head).
- **Signals.** `cache_read_input_tokens` vs `cache_creation_input_tokens` ratio; stable‑prefix size vs provider minimum; position of first volatile token.
- **Algorithm.** Detect stable prefix length; compare to provider min; check whether a volatile field (timestamp, request id) appears before the cache breakpoint, invalidating it; check cache_creation without subsequent cache_read (writing but never reading = pure overhead).
- **Fix.** Move volatile tokens after the cache breakpoint; raise TTL; consolidate prefix to exceed minimum.
- **Savings.** Recoverable read discount on the cacheable prefix; plus eliminating wasted cache‑write overhead.
- **Guards.** Respect provider‑specific mechanics; TTL economics differ (5‑min vs 1‑hr).

### 4.3 `retrieval_thrash` & RAG bloat (SAGE‑derived)

- **Definition.** On a task, the agent retrieves repeatedly and/or stuffs oversized, low‑relevance context; context grows faster than *useful evidence*, and extra retrieval doesn't improve the answer — sometimes it degrades it (context rot).
- **Signals.** Retrieval/tool spans per task; retrieved‑chunk counts and sizes; embedding relevance of retrieved chunks vs the query; answer‑stability across retrieval iterations; latency vs SLO (if an SLO is configured).
- **Algorithm.**
  1. Group retrieval spans per task.
  2. **Evidence gain per iteration:** embed newly retrieved chunks; measure novelty vs previously retrieved (near‑duplicate chunks = no gain). Track `distinct_evidence_tokens / retrieved_tokens`.
  3. **Relevance yield:** fraction of retrieved chunks above a relevance threshold to the query; low yield ⇒ bloat.
  4. **Iteration productivity:** if iterations climb while answer/tool‑selection stays flat ⇒ thrash.
  5. **SLO awareness (SAGE):** if extra retrieval pushes latency past the SLO *and* doesn't raise a quality proxy, flag "over‑retrieval against SLO."
- **Severity.** Combine relevance yield (low = bad), duplicate ratio (high = bad), and iteration excess.
- **Fix.** Right‑size `top_k`; add a relevance/rerank filter; cap retrieval iterations; adopt SLO‑aware adaptive retrieval (retrieve only until the marginal chunk stops adding evidence or the SLO budget is hit).
- **Savings.** Tokens from dropped low‑relevance/duplicate chunks × input price; often large given 70–80% context‑cut figures reported for RAG right‑sizing.
- **Guards.** Legitimate hard queries need more retrieval; use per‑query, not global, thresholds; never penalize retrieval that demonstrably changed the answer.

### 4.4 `nonconvergence` — the standout (full deep dive in §5)

- **Definition.** The agent continues iterating (planning/tool/verify loops) without making progress — thrashing (same action), oscillating (A↔B), or stalling (context grows, information doesn't) — until a hard cap stops it.
- **Signals.** Successive tool calls + results; plan/goal/state representation deltas; context growth vs distinct information; per‑iteration "what new evidence / why insufficient" (if traced or via optional judge).
- **Why it's hard & why shallow guards miss it:** existing guards use exact SHA‑256 match on tool calls; they miss calls with slightly different args (e.g., different line numbers), semantic oscillation, and "productive‑looking but non‑advancing" loops. See §5.
- **Fix.** Insert a convergence stop (warn → nudge model to change strategy → hard stop); fix ambiguous tool success states; add explicit progress signals.
- **Savings.** `wasted_tokens = tokens spent after the last productive iteration` (attribution defined in §5.4).
- **Guards.** Warn‑then‑act escalation; exempt legitimately repetitive workflows (polling, batch); tuneable thresholds; never flag a loop that reached success.

### 4.5 `redundant_tool_calls`

- **Definition.** The same or near‑identical tool call is executed multiple times with the same effective result within a short window.
- **Signals.** Tool name + normalized args (canonicalize whitespace, order‑insensitive keys, numeric tolerances); fuzzy hash within a sliding window; identical results.
- **Algorithm.** Canonicalize args → hash → sliding‑window duplicate detection with a *fuzzy* mode (near‑duplicate args flagged, not just exact). Distinguish from legitimate polling via a configurable exempt list and result‑change check (if the result changed, it's not redundant).
- **Fix.** Memoize/cache tool results within a task; debounce; make tool success states unambiguous.
- **Savings.** Tokens for the duplicate call's input + its result feeding back into context on later turns.
- **Guards.** Polling/status‑checks exempt; args with meaningful differences not flagged.

### 4.6 `verbosity` — output overspend

- **Definition.** The model over‑generates: long free‑text where structured/extractive output would do, no `max_tokens` cap, verbose reasoning surfaced into output.
- **Signals.** Output/input token ratio vs task‑type norm; `max_tokens` unset or far above realized output; response format not constrained; output tokens as a share of cost (they're the expensive ones).
- **Algorithm.** Compare realized output tokens to a per‑task‑type expected band; flag high ratios; detect absent length/format constraints in the request.
- **Fix.** Set `max_tokens`; request structured/JSON or extractive output; instruct concision; strip chain‑of‑thought from final output where not needed.
- **Savings.** `(realized_output − expected_output) × output_price` (output priced ~4–6× input, so this is high‑leverage).
- **Guards.** Some tasks legitimately need long output (drafting, summarization of long inputs); use task‑type bands, not a global cap.

### 4.7 `model_mismatch` — routing waste

- **Definition.** A premium model is used for a step a cheaper model handles equally well (classification, extraction, simple tool selection, formatting).
- **Signals.** Model tier per span; step type (tool‑selection vs reasoning vs generation); output complexity; whether cheaper models historically pass this step's evals (if provided).
- **Algorithm.** Heuristic step‑complexity classifier (tool‑only steps, short structured outputs, deterministic transforms → "downgrade candidate"); optionally consult a user‑provided per‑step eval map to confirm a cheaper model preserves quality.
- **Fix.** Route simple steps to a smaller model (Haiku‑class) and reserve premium models for multi‑step reasoning.
- **Savings.** `tokens × (premium_price − candidate_price)` on downgradable steps; public guidance says 60–70% of agent calls suit small models.
- **Guards.** **Quality gate mandatory** — never recommend a downgrade without a quality signal or a clearly trivial step; mark all such findings `quality_risk: review`.

### 4.8 `reasoning_overspend`

- **Definition.** Excess reasoning/thinking tokens where lower effort suffices.
- **Signals.** `gen_ai.usage.reasoning_tokens`, `gen_ai.request.reasoning_effort`; reasoning tokens as a share of cost; task type.
- **Algorithm.** Flag steps where reasoning tokens dominate cost but the task is simple/structured; recommend lower `reasoning_effort`.
- **Fix.** Lower reasoning effort / disable extended thinking for simple steps.
- **Savings.** Reasoning tokens are billed as output — high per‑token; savings can be significant.
- **Guards.** Hard reasoning tasks need it; task‑type aware; quality‑gated.

---

## 5. The Convergence Engine (deep dive — the CAFO‑derived standout)

This is the feature that makes Wattage more than a nicer dashboard, and it is the piece most directly grounded in convergence‑aware orchestration research. Ship it as the headline.

### 5.1 Why shallow loop‑guards fail

Existing guards (OpenFang `loop_guard.rs`, Genkit `smartMaxTurns`, Strands debounce hooks) detect **exact** repeated tool calls via SHA‑256 + sliding window. They fail on:
- **Fuzzy loops:** same tool, slightly different args each time (read_file with incrementing line numbers) — never hashes equal.
- **Semantic oscillation:** the agent alternates between two strategies (A→B→A→B) that individually look like progress.
- **Productive‑looking stalls:** context keeps growing (new tokens every turn) but no *new information* is added — the hash always differs, so exact‑match guards never fire.
- **No cost attribution:** they stop the loop but don't tell you how many tokens/dollars the thrash cost.

Wattage's engine measures **progress**, not repetition.

### 5.2 Progress signals

For each iteration *i* in a loop, compute a set of signals:

1. **Evidence gain `E_i`.** Embed the new information acquired this iteration (tool results, retrieved chunks, model conclusions). `E_i = 1 − max cosine similarity(new_info_i, all prior info)`. Near‑duplicate acquisition ⇒ `E_i ≈ 0` (no progress). Use a local embedding model by default (offline); API embeddings optional.
2. **State/plan delta `S_i`.** If the trace exposes the agent's plan/goal/scratchpad (or the model's stated next‑step), measure semantic change vs the prior state. No change across iterations ⇒ stall.
3. **Oscillation score `O_i`.** Canonicalize each iteration's action (tool + fuzzy‑normalized args + intent) into a symbol; run cycle detection over the recent symbol sequence (detect ABAB / ABCABC patterns via periodicity in the sequence, tolerant to arg noise).
4. **Context‑growth‑vs‑information `G_i`.** `G_i = added_context_tokens_i / max(distinct_new_evidence_tokens_i, ε)`. High ratio = paying for tokens that carry no new information (bloat without progress).
5. **Goal‑proximity trend `P_i` (optional).** If a success/goal signal exists (task completed, assertion passed, tool returned SUCCESS), track whether iterations move toward it. Flat/negative trend = non‑productive.
6. **LLM‑judge fallback `J_i` (optional, sampled, off by default).** For ambiguous cases, ask a cheap model: "Between iteration i‑1 and i, was new, decision‑relevant progress made? yes/no + reason." Sampled and cached to keep the *tool's own* cost negligible.

### 5.3 Convergence score & loop classification

Combine signals into a per‑iteration **progress score**:

```
progress_i = w_E·E_i + w_S·S_i + w_P·P_i − w_O·O_i − w_G·penalty(G_i)      # clamp [0,1]
```

Default weights (tuneable, learn from benchmark): `w_E=0.4, w_S=0.2, w_P=0.2, w_O=0.15, w_G=0.05`. Judge `J_i`, when enabled, overrides ties.

Classify the loop by the trajectory of `progress_i`:

- **productive** — progress stays above `θ_prog` (e.g., 0.25) or trends to a success signal. No finding.
- **thrashing** — progress collapses below `θ_prog` for ≥ `k` consecutive iterations (default k=3) with low evidence gain.
- **oscillating** — high `O_i` / detected cycle in the action sequence.
- **stalled** — `E_i≈0` and `S_i≈0` while context grows (`G_i` high) — the shallow‑guard blind spot.

Emit a `nonconvergence` finding with the subtype, the iteration index where productivity ended, and the cost attribution below.

### 5.4 Wasted‑token attribution

```
last_productive = max{ i : progress_i ≥ θ_prog }   # last iteration that advanced
wasted_tokens   = Σ_{j > last_productive} tokens(iteration_j)      # input + output + reasoning
wasted_dollars  = price(wasted_tokens, per-model)
```

If the loop eventually *succeeded* after apparent stalls, do **not** flag it (retros­pect: the "stall" was productive). Only attribute waste to loops that hit the cap or terminated without success, or clear post‑success tail iterations.

### 5.5 Pseudocode

```python
def analyze_convergence(loop: Loop, cfg) -> Optional[Finding]:
    iters = loop.iterations
    if len(iters) < cfg.min_iterations:            # short loops exempt
        return None
    if loop.reached_success:                        # don't punish success
        return maybe_flag_post_success_tail(loop, cfg)

    progress = []
    prior_info_embs = []
    action_symbols = []
    for i, it in enumerate(iters):
        new_info = extract_new_information(it)      # tool results, retrieved chunks, conclusions
        emb = embed(new_info)                        # local model by default
        E = 1.0 - max_cosine(emb, prior_info_embs) if prior_info_embs else 1.0
        prior_info_embs.append(emb)

        S = state_delta(it, iters[i-1]) if i > 0 else 1.0
        sym = canonical_action(it)                   # tool + fuzzy args + intent
        action_symbols.append(sym)
        O = oscillation_score(action_symbols, window=cfg.osc_window)
        G = growth_vs_info(it, new_info)
        P = goal_proximity(it, loop.goal_signal)     # optional

        p = clamp(cfg.wE*E + cfg.wS*S + cfg.wP*P - cfg.wO*O - cfg.wG*penalty(G), 0, 1)
        if cfg.judge_enabled and is_ambiguous(p):
            p = judge_progress(iters[i-1], it)       # sampled + cached
        progress.append(p)

    subtype = classify(progress, action_symbols, cfg)     # productive|thrashing|oscillating|stalled
    if subtype == "productive":
        return None

    last_prod = last_index_ge(progress, cfg.theta_prog)
    wasted = sum(tokens(iters[j]) for j in range(last_prod + 1, len(iters)))
    return Finding(
        id="nonconvergence", subtype=subtype,
        wasted_tokens=wasted, wasted_dollars=price(wasted, loop.model_mix),
        evidence=summarize_loop(iters, last_prod),
        fix=fix_for(subtype), quality_risk="none",
        severity=severity_from_dollars(price(wasted, loop.model_mix)),
    )
```

### 5.6 Loop reconstruction from traces

Loops aren't always labeled. Reconstruct them from OTel spans:
- An `invoke_agent` span with repeated child `execute_tool` + `chat` cycles is a loop.
- Framework spans (LangGraph nodes, LlamaIndex steps) often expose iteration boundaries directly.
- Fallback heuristic: a repeating pattern of {LLM call → tool call → LLM call} under one agent invocation.

### 5.7 Phase‑2 preview (runtime enforcement)

The same signals run **online** as a drop‑in wrapper/callback (the "Leash" pattern): after each iteration, compute `progress_i`; on sustained non‑progress, **warn** (inject a message telling the model it's not advancing and to change strategy), then **nudge** (force a strategy switch or summarize‑and‑restart), then **hard‑stop** with a clean aborted result. Compose *outermost* so it catches what retries/fallbacks don't. Never stop a loop above `θ_prog`. See §12.

---

## 6. The Token Efficiency Score

### 6.1 Requirements

The score must be: **principled** (maps to real dollars), **normalized** (comparable across workloads/models), **quality‑aware** (a cheaper run that tanks quality does *not* score higher), and **hard to game** (can't be improved by degrading the product).

### 6.2 Definition

For a trace/batch, define **recoverable waste ratio**:

```
waste_ratio = Σ(quality_safe_wasted_dollars) / total_dollars
```

where `quality_safe_wasted_dollars` sums findings whose fixes are quality‑neutral or quality‑verified (see §6.3). Then:

```
efficiency = round( 100 × (1 − waste_ratio) × quality_factor )
```

`quality_factor ∈ [0,1]` down‑weights the score if the run's quality (from a provided eval/labels/judge) is below target — so you can't score 100 by shipping a cheap‑but‑wrong agent. If no quality signal is provided, `quality_factor = 1` and the report states quality was **unmeasured** (never claim quality it can't see).

Grades: **A** 90–100, **B** 80–89, **C** 70–79, **D** 60–69, **F** < 60. Also report the **dollar‑denominated** headline (`$X/mo estimated recoverable waste`) because dollars, not a grade, move executives.

### 6.3 Quality‑cost gating (the differentiator)

Every fix is tagged `quality_risk`: `none` (caching, dedup, cache config — pure win), `low` (verbosity/format), or `review` (model downgrade, reasoning reduction, aggressive retrieval cuts). The score's `quality_safe_wasted_dollars` includes `none`/`low` fully and includes `review` findings *only* if the user supplies an eval/label set confirming the cheaper path preserves quality. This is the honest, defensible core: Wattage never claims a saving it can't stand behind, and it beats naive tools that ignore the cost↔quality frontier.

### 6.4 Badge

`wattage badge` renders an SVG for the README: `⚡ Token Efficiency: B (84) · ~$2.4k/mo recoverable`. Optionally posts the trend (▲/▼ vs last baseline). The badge is free viral distribution — every repo that adds it advertises Wattage.

---

## 7. Architecture

### 7.1 System diagram

```
                          ┌──────────────────────────────────────────────┐
   TRACE SOURCES          │                  WATTAGE CORE                  │        OUTPUTS
 ┌──────────────┐         │                                                │   ┌──────────────────┐
 │ OTLP file    │──┐      │  ┌──────────┐   ┌──────────┐   ┌────────────┐  │   │ Terminal report  │
 │ (.json/.pb)  │  │      │  │ Adapters │──▶│ Normalize│──▶│ Sessionize │  │──▶│ (rich)           │
 ├──────────────┤  ├─────▶│  │ (ingest) │   │  → model │   │  → sessions│  │   ├──────────────────┤
 │ OTLP endpoint│  │      │  └──────────┘   └──────────┘   └─────┬──────┘  │   │ HTML flame graph │
 │ (collector)  │  │      │                                      │         │──▶│ ("burn map")     │
 ├──────────────┤  │      │        ┌─────────────────────────────▼──────┐  │   ├──────────────────┤
 │ Provider     │  │      │        │        DETECTOR ENGINE             │  │   │ JSON report      │
 │ usage logs   │──┤      │        │  prefix_churn · cache_gap ·        │  │──▶│ (machine)        │
 ├──────────────┤  │      │        │  retrieval_thrash · nonconvergence │  │   ├──────────────────┤
 │ OpenLLMetry /│  │      │        │  redundant · verbosity ·           │  │   │ JUnit XML / SARIF│
 │ OpenInference│──┘      │        │  model_mismatch · reasoning        │  │──▶│ (CI)             │
 ├──────────────┤         │        └──────────────┬─────────────────────┘  │   ├──────────────────┤
 │ Live tail    │────────▶│                        │ Findings               │   │ MD PR comment    │
 └──────────────┘         │        ┌───────────────▼───────┐  ┌──────────┐  │──▶│ + SVG badge      │
                          │        │  Cost Engine (pricing) │  │  Scorer  │  │   └──────────────────┘
                          │        └───────────────────────┘  └────┬─────┘  │
                          │                    ▲                    │        │   ┌──────────────────┐
                          │        ┌───────────┴──────┐   ┌─────────▼─────┐  │──▶│ Baseline store   │
                          │        │ Pricing registry │   │ Report assembler│  │  │ (JSON/SQLite)    │
                          │        └──────────────────┘   └───────────────┘  │   └──────────────────┘
                          └──────────────────────────────────────────────┘
```

### 7.2 Pipeline stages

`ingest → normalize → sessionize → detect → cost → score → render → (baseline compare)`.

1. **Ingest.** An `Adapter` reads a source and yields raw spans.
2. **Normalize.** Map to the internal model (OTel `gen_ai.*` first‑class; other schemas mapped in).
3. **Sessionize.** Group spans into sessions → tasks → loops → LLM/tool/retrieval calls (trace/parent‑span IDs; fallbacks).
4. **Detect.** Run enabled detectors over each session → `Finding`s.
5. **Cost.** Price every span and every finding via the Cost Engine.
6. **Score.** Compute Token Efficiency + dollar headline (quality‑gated).
7. **Render.** Emit selected output formats.
8. **Baseline compare (CI).** Diff against committed baseline; decide pass/fail.

### 7.3 Ingestion adapters

Priority order for v1:

1. **OTLP file** (`.json` / protobuf) — primary; deterministic, offline, testable. The MVP requires only this.
2. **Provider usage fields** — Anthropic/OpenAI response `usage` (input/output/**cache_creation**/**cache_read**/**reasoning** tokens). Critical for cache detectors even when full content capture is off.
3. **OpenLLMetry (traceloop) / OpenInference (Arize)** — the two dominant GenAI instrumentation schemas; map their attributes to `gen_ai.*`.
4. **OTLP endpoint / OTel Collector** — pull spans from a running collector or accept push.
5. **Live tail** — subscribe to a stream for real‑time profiling (bridges to Phase 2).

Adapters normalize divergent attribute names (`llm.model`, `openai.model`, `gen_ai.request.model` → one field), tolerate the semconv's "Development" churn via a version‑tolerant mapping table, and support dual‑emission attribute names.

### 7.4 Normalized data model (built on OTel GenAI semconv)

Core entities (pydantic; see §9.1 for full schemas):

- **`Trace`** → list of **`Session`** (a user/agent interaction).
- **`Session`** → list of **`Task`** (a goal) → each Task has **`Loop`**(s).
- **`Loop`** → ordered **`Iteration`**s; each Iteration references the **`LLMCall`** / **`ToolCall`** / **`RetrievalCall`** spans within it.
- **`LLMCall`**: model, provider, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `reasoning_tokens`, `reasoning_effort`, `max_tokens`, prompt fingerprint / messages (if captured), latency, cost fields (filled by Cost Engine).
- **`ToolCall`**: name, canonical args, args_hash, result, result_hash, latency, tokens attributable.
- **`RetrievalCall`**: query, retrieved chunks (id, size, relevance if available), top_k, latency.

All token/cost fields map to OTel: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read_input_tokens`, `gen_ai.usage.cache_creation_input_tokens`, `gen_ai.usage.reasoning_tokens`, `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.request.reasoning_effort`, `gen_ai.operation.name`, `gen_ai.provider.name`. Spans of interest: `chat`, `execute_tool`, `invoke_agent`, `create_agent`, `embeddings`.

### 7.5 Cost engine & pricing registry

- **Reuse, don't reinvent.** Back the pricing registry with an existing, maintained source — **AgentOps `tokencost`** (400+ models) and/or **LiteLLM's `model_prices_and_context_window.json`** — vendored and refreshed, with a thin Wattage adapter. This avoids the maintenance treadmill of tracking price changes and is the honest engineering choice.
- **Cache‑aware.** Price four token classes per model: `input`, `output`, `cache_read` (~10% of input on current Anthropic tiers — verify), `cache_creation` (write premium), and `reasoning` (billed as output). The registry stores multipliers so cache economics are computed, not hardcoded.
- **Versioned & overridable.** A `pricing.yaml` the user can override for negotiated/enterprise rates or self‑hosted models (where "cost" may be GPU‑seconds; support a pluggable cost function for self‑hosted/`vLLM`).
- **Provenance.** Every dollar figure carries the pricing‑registry version + date so reports are reproducible and auditable.

### 7.6 Detector plugin system

Detectors implement a common ABC (§9.2), are registered via entry points, and are individually enabled/weighted in config. Third‑party detectors install as separate packages and auto‑discover — this is the growth flywheel (community detectors for niche frameworks/waste patterns).

### 7.7 Renderers

- **Terminal** (`rich`): summary panel (score, $ headline, top findings), a compact per‑category token breakdown, and the top 5 fixes.
- **HTML flame graph** ("burn map"): self‑contained single file (inline JS/CSS/SVG, no external calls), hierarchical flame graph of tokens by session→task→step→span→category, hover for tokens/$/model, click to zoom, a findings sidebar. This is the shareable artifact; invest in making it beautiful (see §14, frontend‑design).
- **JSON**: full machine‑readable report (findings, costs, score, provenance).
- **JUnit XML**: one test case per detector/threshold for generic CI.
- **SARIF**: findings as code‑scanning alerts (GitHub Security tab), annotated on the offending config/prompt file when locatable.
- **Markdown PR comment**: per‑detector delta table vs baseline.
- **SVG badge**: the efficiency grade + $ headline.

### 7.8 Baseline & history store

- Baseline is a small JSON committed to the repo (`.wattage/baseline.json`) holding per‑detector metrics + score for the last passing run, plus a **rolling 7‑day window** of runs (append‑only) so CI distinguishes a noise‑floor flake from a real regression.
- Optional local **SQLite** for richer history/trends on a dev machine.

---

## 8. Tech stack & repository layout

### 8.1 Language / runtime decision

**Python core.** Rationale: the LLM/agent ecosystem, the OTel Python SDK, embeddings (local `sentence-transformers`), data analysis, and the target users all live in Python; and the maintainer's strengths are Python/ML. A native‑speed CLI (Rust/Go) buys startup time Wattage doesn't need (it's an analysis pass, not a hot‑path proxy in v1).

**`npx` reach without a rewrite.** Publish a tiny **npm shim** (`wattage`) that shells out to a bundled/py‑installed core, so `npx wattage ...` works for the JS crowd. Primary install paths: `pipx install wattage` / `uvx wattage` / `pip install wattage`. Keep the core dependency‑light; make embeddings/LLM‑judge **optional extras** (`wattage[embeddings]`, `wattage[judge]`) so the base install is fast and offline.

**Report UI.** The HTML report is static (self‑contained) — ideal for a hosted demo on Vercel (the maintainer's deploy target). A small companion site (`wattage.dev`) hosts the demo, the "Wall of Savings," and docs.

### 8.2 Monorepo layout

```
wattage/
├─ README.md                      # the viral front door (see §14.2)
├─ pyproject.toml                 # single package or workspace; ruff + mypy + pytest
├─ LICENSE                        # Apache-2.0 (permissive → adoption)
├─ CONTRIBUTING.md                # how to write a detector (flywheel)
├─ docs/                          # mkdocs-material; hosted on wattage.dev
│  ├─ index.md
│  ├─ detectors/                  # one page per detector
│  ├─ convergence.md              # the standout, explained
│  ├─ ci.md
│  └─ adapters.md
├─ src/wattage/
│  ├─ __init__.py
│  ├─ cli.py                      # typer app: report | score | ci | badge | tail | explain
│  ├─ config.py                   # load/validate wattage.yaml (pydantic-settings)
│  ├─ models.py                   # core pydantic models (§9.1)
│  ├─ adapters/
│  │  ├─ base.py                  # Adapter ABC
│  │  ├─ otlp_file.py             # v1 primary
│  │  ├─ provider_usage.py
│  │  ├─ openllmetry.py
│  │  ├─ openinference.py
│  │  ├─ otlp_endpoint.py
│  │  └─ live_tail.py
│  ├─ normalize.py                # raw spans → models; semconv version tolerance
│  ├─ sessionize.py               # spans → sessions/tasks/loops/iterations
│  ├─ pricing/
│  │  ├─ registry.py              # load tokencost/litellm map + user overrides
│  │  ├─ engine.py                # price spans + findings (cache-aware)
│  │  └─ data/pricing.yaml        # vendored snapshot + provenance/date
│  ├─ detectors/
│  │  ├─ base.py                  # Detector ABC + registry
│  │  ├─ prefix_churn.py
│  │  ├─ cache_gap.py
│  │  ├─ retrieval_thrash.py
│  │  ├─ convergence.py           # the engine (§5)
│  │  ├─ redundant_tools.py
│  │  ├─ verbosity.py
│  │  ├─ model_mismatch.py
│  │  └─ reasoning_overspend.py
│  ├─ convergence/                # engine internals (kept separate for depth/testing)
│  │  ├─ signals.py               # E, S, O, G, P, J
│  │  ├─ embed.py                 # local embeddings (optional API)
│  │  ├─ classify.py
│  │  └─ judge.py                 # optional sampled LLM judge
│  ├─ scoring/
│  │  ├─ score.py                 # efficiency + $ headline
│  │  └─ quality.py               # quality_factor / quality-gating
│  ├─ render/
│  │  ├─ terminal.py
│  │  ├─ html/                    # flame graph template + assets (self-contained)
│  │  ├─ json_report.py
│  │  ├─ junit.py
│  │  ├─ sarif.py
│  │  ├─ pr_comment.py
│  │  └─ badge.py
│  ├─ baseline.py                 # .wattage/baseline.json + rolling window
│  └─ ci.py                       # ci command orchestration + exit codes
├─ npm/                           # thin `npx wattage` shim
│  ├─ package.json
│  └─ bin/wattage.js
├─ action/                        # GitHub Action (composite or Docker)
│  ├─ action.yml
│  └─ entrypoint.sh
├─ benchmarks/                    # §13 — credibility
│  ├─ traces/                     # recorded agent sessions (fixtures)
│  ├─ harness.py
│  └─ report/                     # frontier plots, before/after
├─ examples/                      # sample traces + expected reports (golden)
└─ tests/                         # unit + golden-file tests per detector
```

### 8.3 Key dependencies

- Core: `pydantic`, `pydantic-settings`, `typer`, `rich`, `pyyaml`, `numpy`.
- OTel ingest: `opentelemetry-proto` / OTLP JSON parsing (avoid heavy SDK where a parser suffices).
- Pricing: vendored `tokencost` and/or LiteLLM price map.
- Optional extras: `sentence-transformers` (local embeddings) for the convergence engine; an LLM client (Anthropic/OpenAI) for the optional judge; `plotly`/`d3` (bundled) for the HTML flame graph; `jinja2` for templating.
- Dev: `ruff`, `mypy`, `pytest`, `pytest-golden`, `hypothesis` (property tests for detectors).

---

## 9. Interfaces & module specs (code‑level)

### 9.1 Core models (`models.py`)

```python
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class SpanKind(str, Enum):
    chat = "chat"; execute_tool = "execute_tool"; invoke_agent = "invoke_agent"
    create_agent = "create_agent"; embeddings = "embeddings"; other = "other"

class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    reasoning: int = 0

class Cost(BaseModel):                      # filled by the Cost Engine
    input: float = 0; output: float = 0
    cache_read: float = 0; cache_creation: float = 0; reasoning: float = 0
    total: float = 0
    pricing_version: str = ""               # provenance

class LLMCall(BaseModel):
    span_id: str; parent_id: Optional[str]
    provider: str; model: str
    usage: TokenUsage
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    prompt_fingerprint: Optional[str] = None      # rolling hash of stable head
    messages: Optional[list[dict]] = None          # only if content capture on
    start_ns: int; end_ns: int
    cost: Cost = Field(default_factory=Cost)

class ToolCall(BaseModel):
    span_id: str; parent_id: Optional[str]
    name: str; args: dict; args_hash: str
    result: Optional[str] = None; result_hash: Optional[str] = None
    start_ns: int; end_ns: int

class RetrievalCall(BaseModel):
    span_id: str; parent_id: Optional[str]
    query: Optional[str] = None; top_k: Optional[int] = None
    chunks: list[dict] = []                 # {id, tokens, relevance?}
    start_ns: int; end_ns: int

class Iteration(BaseModel):
    index: int
    llm_calls: list[LLMCall] = []
    tool_calls: list[ToolCall] = []
    retrievals: list[RetrievalCall] = []
    def tokens(self) -> TokenUsage: ...
    def cost(self) -> float: ...

class Loop(BaseModel):
    loop_id: str
    iterations: list[Iteration]
    reached_success: bool = False
    goal_signal: Optional[str] = None
    model_mix: dict[str, int] = {}          # model -> token share

class Task(BaseModel):
    task_id: str; loops: list[Loop] = []
    llm_calls: list[LLMCall] = []           # non-loop calls

class Session(BaseModel):
    session_id: str; tasks: list[Task] = []

class Trace(BaseModel):
    source: str; sessions: list[Session]

class QualityRisk(str, Enum):
    none = "none"; low = "low"; review = "review"

class Severity(str, Enum):
    info = "info"; low = "low"; medium = "medium"; high = "high"; critical = "critical"

class Finding(BaseModel):
    id: str                                 # detector id, e.g. "prefix_churn"
    subtype: Optional[str] = None           # e.g. "stalled" for nonconvergence
    severity: Severity
    wasted_tokens: int = 0
    wasted_dollars: float = 0.0
    quality_risk: QualityRisk = QualityRisk.none
    evidence: str                           # human-readable, links to span_ids
    fix: str                                # prescribed action
    fix_savings_note: Optional[str] = None
    location: Optional[str] = None          # file/prompt to annotate (SARIF)
    span_ids: list[str] = []

class Score(BaseModel):
    efficiency: int                         # 0..100
    grade: str                              # A..F
    waste_ratio: float
    quality_factor: float
    quality_measured: bool
    recoverable_dollars: float
    monthly_projection: Optional[float] = None

class Report(BaseModel):
    trace_source: str
    total_dollars: float
    token_breakdown: dict[str, int]         # category -> tokens
    findings: list[Finding]
    score: Score
    pricing_version: str
    generated_at: str
```

### 9.2 Detector ABC (`detectors/base.py`)

```python
from abc import ABC, abstractmethod

class Detector(ABC):
    id: str                                 # unique, stable
    default_enabled: bool = True

    @abstractmethod
    def analyze(self, session: Session, ctx: "AnalysisContext") -> list[Finding]:
        """Pure function of a session (+ ctx: pricing, config, optional quality map).
        Must be side-effect free and deterministic given the same inputs
        (except optional sampled judge, which must be seedable)."""

# Registration via entry points:
# [project.entry-points."wattage.detectors"]
# prefix_churn = "wattage.detectors.prefix_churn:PrefixChurn"
```

`AnalysisContext` carries the `PricingEngine`, the resolved `Config`, an optional embedder, an optional judge, and an optional `quality_map` (per‑task/step eval results) used by quality‑gated detectors.

### 9.3 Adapter ABC (`adapters/base.py`)

```python
class Adapter(ABC):
    @abstractmethod
    def read(self, source: str | IO) -> Iterable[RawSpan]: ...
    @abstractmethod
    def supports(self, source: str) -> bool: ...     # sniff format/schema
```

### 9.4 Pricing engine (`pricing/engine.py`)

```python
class PricingEngine:
    def __init__(self, registry: PricingRegistry, overrides: dict | None = None): ...
    def price_call(self, call: LLMCall) -> Cost:
        p = self.registry.get(call.provider, call.model)     # raises if unknown → warn, don't guess
        return Cost(
            input          = call.usage.input          * p.input,
            output         = call.usage.output         * p.output,
            cache_read     = call.usage.cache_read     * p.input * p.cache_read_mult,
            cache_creation = call.usage.cache_creation * p.input * p.cache_write_mult,
            reasoning      = call.usage.reasoning      * p.output,   # reasoning billed as output
            total          = ...,
            pricing_version= self.registry.version,
        )
```

Unknown model ⇒ emit a warning and mark cost `unknown` (never fabricate a price). Support a pluggable cost function for self‑hosted models (GPU‑seconds).

### 9.5 CLI command specs (`cli.py`, `typer`)

```
wattage report  <source>            # human report (terminal) + optional --html out.html --json out.json
wattage score   <source>            # print just the Token Efficiency score + $ headline
wattage ci      <source>            # baseline compare; exit non-zero on regression (§11)
wattage badge   <source>            # emit SVG badge to stdout/file
wattage tail     <endpoint>          # live profiling stream (bridges to Phase 2)
wattage explain <finding_id>        # docs + remediation detail for a finding type

Global flags:
  --config wattage.yaml
  --pricing pricing.yaml            # override rates
  --quality quality.json            # per-task/step eval results (enables quality-gated findings)
  --detectors prefix_churn,cache_gap,...   # subset
  --format terminal|json|junit|sarif|md
  --baseline .wattage/baseline.json
  --fail-on score<80 | delta>5% | any-critical      # CI thresholds
  --embed local|api|off             # convergence embeddings backend
  --judge off|sampled               # optional LLM judge for ambiguous loops
```

### 9.6 Config schema (`wattage.yaml`, full example)

```yaml
version: 1
project: my-support-agent

pricing:
  source: vendored            # vendored | litellm | tokencost | file
  overrides_file: pricing.yaml   # optional negotiated/self-hosted rates

quality:
  map_file: quality.json         # per-task/step eval results; enables `review` findings in score
  target: 0.90                   # below this, quality_factor < 1

detectors:
  prefix_churn:   { enabled: true }
  cache_gap:      { enabled: true, min_prefix_tokens: 1024 }   # verify per provider
  retrieval_thrash:
    enabled: true
    relevance_threshold: 0.35
    max_iterations_soft: 4
  nonconvergence:
    enabled: true
    min_iterations: 3
    theta_prog: 0.25
    consecutive_k: 3
    osc_window: 6
    weights: { E: 0.40, S: 0.20, P: 0.20, O: 0.15, G: 0.05 }
    exempt_tools: [poll_status, wait, healthcheck]
    embed: local
    judge: off
  redundant_tool_calls: { enabled: true, window: 5, fuzzy: true }
  verbosity:
    enabled: true
    task_bands:                  # expected output/input ratio by task type
      extract: 0.3
      classify: 0.1
      draft: 3.0
  model_mismatch:
    enabled: true
    downgrade_candidates: [haiku-class]
    require_quality_map: true    # never downgrade without a quality signal
  reasoning_overspend: { enabled: true }

scoring:
  monthly_projection_from: trace-window   # extrapolate $ headline

ci:
  baseline: .wattage/baseline.json
  rolling_window_days: 7
  fail_on:
    score_below: 80
    cost_delta_pct_above: 5
    any_critical: true
  pr_comment: true
  badge_out: .wattage/badge.svg
  sarif_out: wattage.sarif
```

### 9.7 Sample input & output (golden)

Input (OTLP JSON, abbreviated — one `chat` span):

```json
{ "resourceSpans": [ { "scopeSpans": [ { "spans": [ {
  "name": "chat",
  "attributes": [
    {"key":"gen_ai.provider.name","value":{"stringValue":"anthropic"}},
    {"key":"gen_ai.request.model","value":{"stringValue":"claude-sonnet-4-6"}},
    {"key":"gen_ai.usage.input_tokens","value":{"intValue":"18450"}},
    {"key":"gen_ai.usage.output_tokens","value":{"intValue":"320"}},
    {"key":"gen_ai.usage.cache_read_input_tokens","value":{"intValue":"0"}}
  ]
} ] } ] } ] }
```

Output (JSON report, abbreviated):

```json
{
  "trace_source": "trace.json",
  "total_dollars": 1.84,
  "token_breakdown": {"system":4200,"resent_history":11800,"retrieved":2100,"tool_io":900,"reasoning":0,"output":320},
  "findings": [
    {"id":"prefix_churn","severity":"high","wasted_tokens":10620,"wasted_dollars":0.029,
     "quality_risk":"none","evidence":"11.8k re-sent prefix tokens across 7 turns; cache_read=0",
     "fix":"Enable prompt caching on the stable system+tools prefix (≥ provider min); move volatile fields to the tail."},
    {"id":"nonconvergence","subtype":"stalled","severity":"medium","wasted_tokens":6400,"wasted_dollars":0.052,
     "quality_risk":"none","evidence":"Iterations 4–7 added context but no new evidence (E≈0.02); last productive iter=3",
     "fix":"Add convergence stop; disambiguate tool success state."}
  ],
  "score": {"efficiency":71,"grade":"C","waste_ratio":0.29,"quality_factor":1.0,
            "quality_measured":false,"recoverable_dollars":0.53,"monthly_projection":2410.0},
  "pricing_version":"2026-07-litellm-snapshot",
  "generated_at":"2026-07-17T00:00:00Z"
}
```

---

## 10. CLI & UX principles

The one‑liner is the product's first impression — make it excellent:

- **Zero‑config default.** `pipx run wattage report trace.json` produces a great terminal report with no setup. Config is optional refinement.
- **Progressive disclosure.** Terminal shows score + $ headline + top 5 findings + top fixes. `--html` for the shareable flame graph; `--json` for machines.
- **Actionable, not accusatory.** Every finding ends in a concrete fix and a dollar number. Tone: a helpful profiler, not a scold.
- **Fast & offline by default.** Base install has no network dependency; embeddings/judge are opt‑in extras.
- **Copy‑paste fixes.** Where possible, emit the *exact* code/config change (e.g., the cache breakpoint snippet, the `max_tokens` line).

---

## 11. CI/CD integration

CI is where Wattage becomes sticky (it runs on every PR) and where the badge spreads. Follow the hard‑won best practices from 2026 cost‑regression write‑ups (FutureAGI, QASkills, MLflow):

### 11.1 Principles

- **PRs only**, with a `paths:` filter and `concurrency.cancel-in-progress` — never every commit (that floods noise, blows any judge budget, and trains people to ignore red).
- **Committed baseline + rolling window.** Store the last passing metrics and a 7‑day window as JSON in the repo so a run can tell a noise‑floor flake from a real regression.
- **Per‑detector deltas, not one aggregate.** Report which detector regressed (e.g., "cache_gap +18%"), not just "efficiency −4." Aggregation hides the cause.
- **A failed gate triggers investigation, not auto‑fix.** Wattage never silently trims prompts in CI.
- **Deterministic fixtures.** CI runs against a committed fixture trace (or a recorded eval run), not live production traffic (which is flaky and privacy‑heavy). Sample/sanitize prod → promote a few into the fixture set.

### 11.2 GitHub Action (`action/action.yml` usage)

```yaml
# .github/workflows/wattage.yml
name: Wattage
on:
  pull_request:
    paths: ["agents/**", "prompts/**", "src/**"]
concurrency:
  group: wattage-${{ github.ref }}
  cancel-in-progress: true
jobs:
  token-efficiency:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate trace fixture
        run: python scripts/run_agent_fixture.py > trace.json   # deterministic eval run
      - name: Wattage cost-regression gate
        uses: <org>/wattage-action@v1
        with:
          source: trace.json
          baseline: .wattage/baseline.json
          quality: quality.json            # optional; enables quality-gated findings
          fail-on: "score_below:80,cost_delta_pct_above:5,any_critical:true"
          pr-comment: "true"
          sarif-out: wattage.sarif
      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: wattage.sarif }
```

### 11.3 Exit codes (`ci.py`)

| Code | Meaning |
|---|---|
| 0 | Pass — within thresholds vs baseline |
| 1 | Fail — a `fail-on` threshold breached (regression) |
| 2 | Config/usage error |
| 3 | Ingestion error (unparseable/empty trace) |
| 4 | Pricing error (unknown model, no override) |

### 11.4 PR comment (Markdown)

```
### ⚡ Wattage — Token Efficiency: C (71)  ▼ 6 vs baseline
Estimated recoverable waste: **$0.53/run (~$2,410/mo)**

| Detector | This PR | Baseline | Δ | $ waste |
|---|---|---|---|---|
| prefix_churn | 10.6k tok | 0 | ▲ new | $0.029 |
| nonconvergence (stalled) | 6.4k tok | 2.1k | ▲ +205% | $0.052 |
| verbosity | ok | ok | — | — |

**Top fix:** enable prompt caching on the stable prefix → ~$0.026/run recoverable (quality‑neutral).
<sub>pricing: 2026‑07 snapshot · quality: unmeasured (add quality.json to gate model‑downgrade findings)</sub>
```

### 11.5 SARIF & badge

- **SARIF:** each finding becomes a code‑scanning alert; when a finding maps to a file (a prompt template, a config), annotate that line in the GitHub "Files changed"/Security tab.
- **Badge:** `wattage badge` writes `badge.svg`; commit it or serve from `wattage.dev/badge/<repo>`. README badge = passive distribution.

### 11.6 Other CI

Ship JUnit XML so GitLab CI, CircleCI, Jenkins, etc. render results natively; the exit codes make the gate work anywhere.

---

## 12. Runtime enforcement — Phase 2 (the live convergence controller)

Phase 1 is *observe/diagnose/gate* (safe, offline, high‑trust). Phase 2 turns the convergence engine into a **drop‑in runtime guard** — the "Leash" pattern: a thin wrapper that watches an agent live and stops waste in‑flight. This is powerful but higher‑trust, so it ships second and stays opt‑in.

### 12.1 Integration surfaces

- **Generic (OTel‑based):** consume the live span stream (`wattage tail`) and signal back via a callback — framework‑agnostic.
- **Framework callbacks:** LangChain/LangGraph callbacks, LlamaIndex callbacks, and thin SDK wrappers for the Anthropic/OpenAI clients. One adapter per major framework.
- **Drop‑in wrapper:** `guarded = wattage.guard(agent, policy=...)` — minimal code change, mirrors the Leash zero‑config ethos.

### 12.2 Policies (escalation, safety‑first)

Run the §5 signals online. On sustained non‑progress (`progress_i < θ_prog` for `k` iters):

1. **Warn** — inject a system/tool message: "You've made no new progress for N steps; change strategy or stop." Many loops self‑correct given this nudge.
2. **Nudge** — force a strategy switch (summarize‑and‑restart, or restrict the offending tool) once.
3. **Hard‑stop** — return a clean aborted result rather than crashing or hitting the cap.

Compose **outermost** so it catches what retry/fallback middleware doesn't. Additional guardrails: a **token/$ budget per task** (soft warn → constrained mode → hard stop) and a **redundant‑tool debounce** (block a duplicate call, feed the cached result).

### 12.3 Safety rules

- **Never stop a productive loop** (`progress_i ≥ θ_prog`).
- **Warn‑then‑act** (never hard‑stop on the first sign).
- **Exempt lists** for legitimate repetition (polling, batch).
- **Dry‑run mode** that only logs what it *would* do — the on‑ramp to trust (run in shadow, show the savings it would have captured, then enable).
- **Deterministic + seedable** so behavior is reproducible; every intervention is traced (as its own OTel span) for auditability.

### 12.4 Why this is the moat, restated

Every shallow guard is exact‑match and blunt. Wattage's guard is *semantic and progress‑aware* — it's the productization of convergence‑aware orchestration. Phase 1 proves the detection is accurate (on recorded traces); Phase 2 acts on it live. Shipping Phase 1 first de‑risks Phase 2: you've already demonstrated, on real data, that the "stall" and "oscillation" calls are correct.

---

## 13. Benchmark & evaluation plan (credibility → virality)

A tool that *claims* to save tokens is ignored; a tool with a **reproducible benchmark** showing "we cut a real Claude Code session 61% with no quality loss" gets shared. This section is what separates excellent from average, and it plays directly to rigorous‑evaluation strengths. **Do not fabricate results — the numbers below are targets/methodology, filled in by running the harness.**

### 13.1 Datasets (recorded agent traces)

- **Coding agents:** recorded SWE‑bench‑style agent runs and real Claude Code / OpenAI‑Codex sessions (with permission/sanitized). Coding agents are the canonical token‑burn case and the most viral audience.
- **Agentic RAG:** a QA agent over a public corpus with hard multi‑hop queries (to exercise `retrieval_thrash`).
- **Tool‑use agents:** multi‑tool workflows (to exercise `redundant_tool_calls`, `nonconvergence`).
- **Synthetic adversarial loops:** hand‑crafted thrash/oscillation/stall traces with *known* ground truth for the convergence engine (precision/recall of loop classification).

Store fixtures in `benchmarks/traces/` so every run is reproducible.

### 13.2 Metrics

- **Recoverable waste identified** (tokens, $) and **% of bill** per detector.
- **Realized savings after applying fixes** (re‑run the agent with the fix; measure actual token delta) — the honest number.
- **Quality preservation:** task success / eval score before vs after each fix (the cost↔quality frontier). A fix that saves 30% but drops success 5% is reported as such, not hidden.
- **Convergence engine accuracy:** precision/recall/F1 of {productive, thrashing, oscillating, stalled} vs the labeled adversarial set; and vs shallow SHA‑256 guards as a baseline (show Wattage catches the fuzzy/semantic cases they miss).
- **Tool overhead:** Wattage's own runtime and (if judge/embeddings on) its own token cost — must be negligible vs. what it saves.

### 13.3 The headline artifact

A **quality‑cost frontier plot**: x = tokens/$, y = task quality, before → after Wattage's fixes, with each fix annotated. This one chart is the blog post and the launch tweet. Pair with a table: per‑detector savings, quality delta, on N real sessions.

### 13.4 Harness

`benchmarks/harness.py`: load fixture → run Wattage → (optionally) apply fixes → re‑run agent → measure deltas → emit the frontier plot + table into `benchmarks/report/`. Fully scripted and CI‑runnable so results are reproducible and self‑updating as detectors improve.

### 13.5 Guardrail on claims

Publish methodology, fixtures, and the harness alongside numbers. Report variance (repeated runs of the same agent task vary widely — a known 2026 finding), so present ranges/medians, not cherry‑picked bests. Credibility *is* the marketing here.

---

## 14. Go‑to‑market — the virality plan

An excellent tool that nobody runs isn't viral. Distribution is a feature; build it in.

### 14.1 The viral loop

1. **One‑liner wow:** `pipx run wattage report trace.json` → a gorgeous terminal report + a shareable HTML flame graph in seconds.
2. **Shareable artifact:** the flame graph screenshot ("62% of our tokens were re‑sent context") + the dollar headline. People post *savings*.
3. **Passive spread:** the README **badge** on every adopting repo advertises Wattage to that repo's visitors.
4. **Flywheel:** community **detector plugins** (niche frameworks, new waste patterns) → more coverage → more users → more detectors.

### 14.2 README anatomy (the front door)

Order matters: **(1)** one‑sentence what‑it‑is + the Kill‑A‑Watt line; **(2)** an animated GIF of the one‑liner producing the report/flame graph; **(3)** the copy‑paste install + run; **(4)** the benchmark headline (frontier plot + "cut a real session X%"); **(5)** the badge you can add; **(6)** "how it works" (the detectors, the convergence engine); **(7)** CI setup; **(8)** "write a detector" (contribution). Keep the top third pure payoff.

### 14.3 The hosted demo (Vercel)

`wattage.dev`: upload a trace (or use a sample) → get the flame graph + report in the browser (runs the analysis client/edge‑side; nothing stored). Plus docs (mkdocs‑material) and the **Wall of Savings** — opt‑in user submissions of before/after (tokens saved, quality preserved), which is social proof *and* a growing benchmark corpus.

### 14.4 Launch sequence

- **Pre‑launch:** run the benchmark, write the frontier‑plot blog post, record the GIF, seed 3–4 example traces + golden reports.
- **Launch:** Show HN ("Wattage — see where your AI agents burn tokens, and gate cost regressions in CI"), r/LocalLLaMA + r/MachineLearning, an X/LinkedIn thread led by the frontier plot, and posts in the LangChain/LlamaIndex/OTel communities. Tie the pitch to the live 2026 cost‑panic narrative (it's timely and real).
- **Integrations announcement:** "works with your existing Langfuse/Helicone/OpenLLMetry traces" — position as *complementary*, not competitive, to observability tools (they surface data; Wattage diagnoses it). This makes them amplifiers, not rivals.

### 14.5 Brand

Flame‑graph‑meets‑gauge motif; a "W" mark; the burn‑map as the signature visual. Consistent voice: precise, a little witty, dollar‑honest. Use the `frontend-design` skill when building the HTML report and the site so they look intentional, not templated — the report's polish is a growth lever.

### 14.6 Positioning one‑liners (reuse everywhere)

- "A Kill‑A‑Watt meter for your AI agents."
- "See where your tokens burn. Stop paying for it."
- "Observability tells you the bill. Wattage tells you *why* — and stops it happening again."

---

## 15. Roadmap & milestones

**Phase 0 — Skeleton (week 1):** repo, packaging, `models.py`, OTLP‑file adapter, pricing engine (vendored map), `wattage report` terminal output on a sample trace. *Exit:* one real trace produces a priced report.

**Phase 1 — MVP detectors (weeks 2–4):** `prefix_churn`, `cache_gap`, `verbosity`, `redundant_tool_calls`; JSON output; efficiency score (quality‑unmeasured). *Exit:* a real Claude Code trace yields correct, dollar‑quantified findings.

**Phase 2 — The standout (weeks 4–7):** the convergence engine (`signals.py`, `classify.py`, local embeddings) + `retrieval_thrash`; the adversarial labeled set + precision/recall vs shallow guards. *Exit:* convergence F1 beats SHA‑256 baseline on the labeled set; a compelling "stalled loop" example.

**Phase 3 — Shareable (weeks 6–9):** the HTML flame graph (invest in polish), the badge, `model_mismatch`/`reasoning_overspend`, quality‑gating + `--quality`. *Exit:* a screenshot‑worthy report + the frontier plot.

**Phase 4 — CI + launch (weeks 8–11):** GitHub Action, baseline/rolling window, PR comment, SARIF, JUnit; benchmark harness + blog post; `wattage.dev` demo. *Exit:* public launch.

**Phase 5 — Runtime enforcement (post‑launch):** the live convergence guard (dry‑run → warn → nudge → stop), framework callbacks, budget guardrails. *Exit:* opt‑in runtime mode with shadow‑mode proof.

**Phase 6 — Ecosystem/team (later):** third‑party detector marketplace, hosted team dashboards/trends, upstream OTel semconv proposals for waste‑oriented attributes.

(Weeks are relative effort ordering, not commitments; sequence and dependencies are the point.)

---

## 16. Risks & mitigations (honest)

| Risk | Mitigation |
|---|---|
| **Crowded space** (observability + compression are mature) | Sharp wedge: *diagnosis + prescription + gate + score*, not another dashboard/compressor. Depth in detectors (esp. convergence) is the moat. Position as complementary to observability. |
| **"Just another cost tool"** perception | Lead with the convergence engine and the frontier plot — capabilities nobody else ships. Don't launch as "a cost dashboard." |
| **Cost↔quality tradeoff** (cheaper can hurt quality) | Quality is a first‑class axis; `quality_risk` tags; score gates `review` fixes behind a provided eval; never claim an unverified saving. |
| **False positives** (esp. convergence flagging good loops) | Warn‑then‑act; exempt lists; per‑query thresholds; never flag successful loops; sampled judge for ambiguity; benchmark precision explicitly. |
| **The tool's own cost** (embeddings/judge) | Local embeddings by default; judge off by default, sampled + cached when on; base install offline. Report tool overhead in the benchmark. |
| **Pricing drift** | Pricing is versioned data (reuse tokencost/LiteLLM), user‑overridable, provenance stamped; never hardcoded. |
| **OTel GenAI semconv still "Development"** | Version‑tolerant normalization; dual‑attribute support; map OpenLLMetry/OpenInference too; contribute upstream. |
| **Scope creep into a platform** | Enforce non‑goals (§3.1). v1 doesn't proxy, host, route, or compress. |
| **Content/privacy** (traces may hold PII) | Operate on token *counts* + fingerprints by default; content capture optional; never exfiltrate; support redaction; local‑first. |
| **Provider content not in traces** (can't always see prompts) | Detectors degrade gracefully to token‑count/structure signals (cache detectors work from `usage` alone); richer signals when content is present. |

---

## 17. Appendices

### Appendix A — OTel GenAI attributes used (reference)

Spans: `chat`, `execute_tool`, `invoke_agent`, `create_agent`, `embeddings`.
Attributes consumed: `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.operation.name`, `gen_ai.request.max_tokens`, `gen_ai.request.reasoning_effort`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read_input_tokens`, `gen_ai.usage.cache_creation_input_tokens`, `gen_ai.usage.reasoning_tokens`. Content (optional, if capture enabled): input/output message events. Normalize legacy names (`llm.model`, `openai.model`, etc.) → canonical. Semconv is "Development" (v1.4x era) — keep the mapping table version‑aware.

### Appendix B — Sample pricing registry (`pricing.yaml`) — VERIFY BEFORE USE

> Prices/caching change frequently. These illustrate structure; **verify against provider docs at build time** and prefer sourcing from the maintained `tokencost`/LiteLLM maps.

```yaml
version: "2026-07-illustrative-VERIFY"
providers:
  anthropic:
    claude-sonnet-4-6:
      input: 3.0e-6          # $/token (≈ $3 / MTok — verify)
      output: 15.0e-6        # ($15 / MTok — verify)
      cache_read_mult: 0.10  # cache reads ≈ 10% of input (≈90% discount — verify)
      cache_write_mult: 1.25 # write premium — verify per TTL (5min vs 1hr differ)
      min_cacheable_prefix_tokens: 1024   # current Sonnet/Opus tiers — verify
    haiku-class:
      input: 0.8e-6          # placeholder — verify
      output: 4.0e-6         # placeholder — verify
      cache_read_mult: 0.10
      cache_write_mult: 1.25
      min_cacheable_prefix_tokens: 4096   # Haiku/older tiers — verify
self_hosted:
  my-vllm-llama:
    cost_fn: gpu_seconds     # pluggable: cost = gpu_seconds × $/gpu-sec
    gpu_dollar_per_sec: 0.0  # set to your infra rate
```

### Appendix C — Quality map (`quality.json`) shape

```json
{
  "tasks": {
    "task_017": {"success": true,  "eval_score": 0.94, "step_scores": {"tool_select": 0.98}},
    "task_018": {"success": false, "eval_score": 0.71}
  },
  "downgrade_evals": {
    "tool_select@haiku-class": {"pass_rate": 0.97}
  }
}
```

### Appendix D — Glossary

- **Prefix churn:** re‑sending a stable prompt prefix uncached, re‑billed as fresh input.
- **Cache read/write:** provider prompt‑caching token classes; reads are heavily discounted, writes carry a premium.
- **Retrieval thrash:** repeated retrieval without evidence gain; **RAG bloat:** oversized/low‑relevance context.
- **Non‑convergence:** a loop that doesn't advance — **thrashing** (same action), **oscillating** (A↔B), **stalled** (context grows, information doesn't).
- **Evidence gain (E):** novelty of information acquired in an iteration vs all prior — the core convergence signal.
- **Quality factor:** score multiplier that prevents a cheap‑but‑wrong agent from scoring well.
- **Token Efficiency:** 0–100 grade = (1 − quality‑safe waste ratio) × quality factor.
- **Burn map:** Wattage's flame graph of token spend.

### Appendix E — Naming & availability

Chosen name: **Wattage** (CLI `wattage`, pkg `wattage`, npm shim `wattage`, site `wattage.dev`).
Before publishing, **verify availability** of: PyPI `wattage`, npm `wattage`, the GitHub org/repo, and `wattage.dev`. If any core handle is taken, fallbacks (in order): **Tokenscope**, **Scorch**, **Singe**, **Kilowatt**. Keep the tagline and Kill‑A‑Watt framing regardless of the final wordmark.

---

*End of build documentation. The next step is implementation — Phase 0 skeleton first (OTLP‑file adapter + pricing + `wattage report`), then the MVP detectors, then the convergence engine as the headline.*
