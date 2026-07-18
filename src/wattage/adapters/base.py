"""Adapter ABC (doc §9.3): every trace source normalizes to a stream of RawSpans."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import IO

from wattage.models import RawSpan


class Adapter(ABC):
    @abstractmethod
    def read(self, source: str | IO[str]) -> Iterable[RawSpan]: ...

    @abstractmethod
    def supports(self, source: str) -> bool:
        """Sniff whether this adapter can handle the given source (path/URI)."""
