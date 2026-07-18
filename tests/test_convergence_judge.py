"""Core tests never depend on a live API key: NullJudge is what's exercised
by default, and SampledLLMJudge is only tested on its deterministic paths
(zero sample rate, cache hits, forced-no-client) — never an actual network
call, regardless of whether `anthropic` happens to be installed or an API
key happens to be set in the environment.
"""

import hashlib

import pytest

from wattage.convergence.judge import NullJudge, SampledLLMJudge


def test_null_judge_always_declines() -> None:
    judge = NullJudge()
    assert judge.judge_progress("a", "b", "c", "d") is None


def test_sampled_judge_with_zero_sample_rate_never_calls_out() -> None:
    judge = SampledLLMJudge(sample_rate=0.0)
    result = judge.judge_progress("prior action", "prior info", "curr action", "curr info")
    assert result is None
    assert judge._client is None  # noqa: SLF001


def test_sampled_judge_cache_hit_skips_the_client_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    judge = SampledLLMJudge(sample_rate=1.0)
    cache_key = hashlib.sha256(b"pa|pi|ca|ci").hexdigest()
    judge._cache[cache_key] = True  # noqa: SLF001

    def _fail_if_called() -> None:
        raise AssertionError("cache hit should never reach the client")

    monkeypatch.setattr(judge, "_client_or_none", _fail_if_called)

    assert judge.judge_progress("pa", "pi", "ca", "ci") is True


def test_sampled_judge_declines_when_no_client_available(monkeypatch: pytest.MonkeyPatch) -> None:
    judge = SampledLLMJudge(sample_rate=1.0)
    monkeypatch.setattr(judge, "_client_or_none", lambda: None)

    result = judge.judge_progress("prior action", "prior info", "curr action", "curr info")
    assert result is None
