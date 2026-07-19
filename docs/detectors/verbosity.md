# verbosity

**Detects:** a call generating a large amount of output with no `max_tokens` cap set at all.

Output tokens are billed at 4–6× the rate of input tokens on most models, so unconstrained generation is disproportionately expensive relative to its token count.

## How it works

A call is flagged when it has **no `max_tokens` set** *and* its realized output exceeds a configured ceiling (1,000 tokens by default). Both conditions matter: a capped call is never flagged, regardless of how much it generates — the developer already made a deliberate choice about the ceiling, and Wattage doesn't second-guess it without knowing whether the output was substantively useful.

## Known limitation

The fuller version of this detector (per the original design) uses per-task-type expected bands — a short "classify" step should generate very little output; a "draft a document" step legitimately generates a lot. That needs a task-type classifier, which doesn't exist yet in this codebase. Using a single global ceiling risks flagging legitimate long-form generation as if it were verbosity. Wattage documents this rather than fabricating a task-type signal it doesn't actually have; this is a natural direction for a future contribution (see `CONTRIBUTING.md`).

`wasted_tokens` here means "tokens beyond your configured ceiling" — a policy estimate you set the threshold for, not a factual claim that those specific tokens were unnecessary. Judging that for certain would require evaluating the actual content, which needs the optional LLM judge (off by default).

## Fix

Set `max_tokens` close to the expected output size, or request structured/extractive output (JSON, a fixed schema) instead of free text.

## Quality risk: low

Capping output length is usually safe, but an overly aggressive cap can truncate a genuinely long, useful answer — hence "low" rather than "none".
