## What this does

<!-- One or two sentences: what changed, and for a new detector, the real
waste pattern it targets. -->

## Why

<!-- What prompted this — a bug you hit, a gap CONTRIBUTING.md's ground
rules call out, a detector this project doesn't cover yet. -->

## Testing

<!-- Paste the output showing new tests pass and nothing else broke: -->

```
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

- [ ] Added tests for the new behavior (golden + at least one Hypothesis
      property test for a new detector — see CONTRIBUTING.md)
- [ ] `uv run mkdocs build --strict` passes, if `docs/` changed
- [ ] No fabricated numbers — every dollar figure, F1 score, or benchmark
      claim in this PR came from an actual run (see CONTRIBUTING.md's
      ground rules)

## Anything reviewers should look at closely

<!-- Optional: a tradeoff you're unsure about, an edge case you couldn't
test, a design choice you want a second opinion on. -->
