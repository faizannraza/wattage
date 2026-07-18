import pytest
from pydantic import ValidationError

from wattage.models import Cost, Finding, Iteration, LLMCall, Score, Severity, TokenUsage


def test_token_usage_add_and_total() -> None:
    a = TokenUsage(input=100, output=20)
    b = TokenUsage(input=50, cache_read=10)
    combined = a + b
    assert combined.model_dump() == {
        "input": 150,
        "output": 20,
        "cache_read": 10,
        "cache_creation": 0,
        "reasoning": 0,
    }
    assert combined.total() == 180


def test_iteration_aggregates_across_llm_calls() -> None:
    call_a = LLMCall(
        span_id="a",
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=100, output=10),
        cost=Cost(total=1.0),
    )
    call_b = LLMCall(
        span_id="b",
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=TokenUsage(input=50, output=5),
        cost=Cost(total=0.5),
    )
    iteration = Iteration(index=0, llm_calls=[call_a, call_b])
    assert iteration.tokens().model_dump() == {
        "input": 150,
        "output": 15,
        "cache_read": 0,
        "cache_creation": 0,
        "reasoning": 0,
    }
    assert iteration.cost() == pytest.approx(1.5)


def test_cost_unpriced_defaults_false() -> None:
    assert Cost().unpriced is False
    assert Cost(unpriced=True).unpriced is True


def test_finding_requires_severity() -> None:
    with pytest.raises(ValidationError):
        Finding(id="prefix_churn", evidence="...", fix="...")  # type: ignore[call-arg]

    finding = Finding(id="prefix_churn", severity=Severity.high, evidence="e", fix="f")
    assert finding.quality_risk.value == "none"


def test_score_round_trip() -> None:
    score = Score(
        efficiency=71,
        grade="C",
        waste_ratio=0.29,
        quality_factor=1.0,
        quality_measured=False,
        recoverable_dollars=0.53,
        monthly_projection=2410.0,
    )
    assert score.model_dump()["grade"] == "C"
