"""Optional sampled LLM judge (doc §5.2 point 6): for ambiguous cases, asks a
cheap model whether real progress was made between two iterations.

Off by default. `NullJudge` — which declines every call — is what the
default pipeline and every core test actually exercises, so nothing here
depends on a live API key unless a caller explicitly constructs and enables
`SampledLLMJudge` (the `wattage[judge]` extra).
"""

from __future__ import annotations

import hashlib
import random
from abc import ABC, abstractmethod


class Judge(ABC):
    @abstractmethod
    def judge_progress(
        self, prior_action: str, prior_info: str, curr_action: str, curr_info: str
    ) -> bool | None:
        """True/False if the judge has an opinion; None if it declines or
        fails — callers must fall back to the non-judge signals, never treat
        None as a guess."""


class NullJudge(Judge):
    def judge_progress(
        self, prior_action: str, prior_info: str, curr_action: str, curr_info: str
    ) -> bool | None:
        return None


class SampledLLMJudge(Judge):
    """Calls a cheap Claude model for ambiguous cases only. Sampled (not
    every call reaches the API) and cached by the exact (prior, curr) pair
    so repeated ambiguous cases in one run don't re-spend tokens. Any
    failure (missing API key, network error, unexpected response) yields
    None rather than a guess.
    """

    def __init__(self, model: str = "claude-haiku-4-5", sample_rate: float = 1.0) -> None:
        self._model = model
        self._sample_rate = sample_rate
        self._cache: dict[str, bool | None] = {}
        self._client: object | None = None

    def _client_or_none(self) -> object | None:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError:
            return None
        try:
            self._client = anthropic.Anthropic()
        except Exception:
            return None
        return self._client

    def judge_progress(
        self, prior_action: str, prior_info: str, curr_action: str, curr_info: str
    ) -> bool | None:
        key = hashlib.sha256(
            f"{prior_action}|{prior_info}|{curr_action}|{curr_info}".encode()
        ).hexdigest()
        if key in self._cache:
            return self._cache[key]
        if random.random() > self._sample_rate:
            return None

        client = self._client_or_none()
        if client is None:
            return None

        prompt = (
            "Between the prior step and the current step of an AI agent's task, "
            "was new, decision-relevant progress made? Answer only 'yes' or 'no'.\n\n"
            f"Prior action: {prior_action}\nPrior result: {prior_info}\n\n"
            f"Current action: {curr_action}\nCurrent result: {curr_info}"
        )
        try:
            response = client.messages.create(  # type: ignore[attr-defined]
                model=self._model,
                max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip().lower()
            result: bool | None = text.startswith("yes")
        except Exception:
            result = None

        self._cache[key] = result
        return result
