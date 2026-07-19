# retrieval_thrash

**Detects:** repeated retrieval activity within a loop that isn't turning up new evidence — a RAG agent that keeps searching without getting anywhere.

## How it works

This reuses the exact same evidence-gain computation as [the convergence engine](../convergence.md)'s `E` signal, scoped specifically to retrieval-like activity: `RetrievalCall` entries, plus tool calls whose name looks like a retrieval operation (contains "search", "retrieve", "query", "lookup", or "find"). Real-world traces — including this project's own [real-trace validation](../adapters.md) — mostly implement "retrieval" as a plain tool call rather than a dedicated embeddings-kind span, so the name-based heuristic matters in practice, not just in theory.

For each retrieval-tagged iteration, the detector computes how novel its retrieved content is against everything retrieved so far in the loop. If most retrieval iterations in a loop come back with little-to-no new evidence (below a configurable relevance threshold), and there are enough of them to rule out a single unlucky search, the loop is flagged.

## Known limitations

Two signals from the fuller design are honestly left unimplemented rather than faked:

- **Relevance yield** (per-chunk relevance scores) needs data the model *can* carry (`RetrievalCall.chunks`) but that no adapter currently populates.
- **SLO-awareness** (flagging over-retrieval specifically against a latency budget) needs a latency budget input nothing currently supplies.

Both are natural extension points once the underlying data exists — see `CONTRIBUTING.md`.

## Fix

Right-size `top_k`, add a relevance/rerank filter, or cap retrieval iterations once the marginal chunk stops adding evidence.

## Quality risk: review

Capping retrieval could cut off a genuinely hard query that needed the extra iterations — this finding always appears in the report, but only counts toward your Token Efficiency score once a `--quality` map confirms the cut is safe.
