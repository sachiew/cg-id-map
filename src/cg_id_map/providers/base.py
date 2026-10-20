"""The interface every non-CG provider adapter implements."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from cg_id_map.models import MarketData, ProviderCoin, ProviderPlatform


@runtime_checkable
class Provider(Protocol):
    #: Short lowercase name used in CLI flags, overrides file names and outputs (e.g. "cmc").
    name: str

    def fetch_coins(self) -> list[ProviderCoin]:
        """Every coin in scope. `contracts` platform keys must match `fetch_platforms` keys."""
        ...

    def fetch_platforms(self) -> list[ProviderPlatform]:
        """Every network referenced by `fetch_coins` contracts."""
        ...

    def fetch_market_data(self, ids: Sequence[str]) -> dict[str, MarketData]:
        """USD price and market cap for the given coin IDs. Missing IDs may be omitted."""
        ...
