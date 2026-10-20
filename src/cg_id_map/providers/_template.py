"""Template for a new provider adapter. See CONTRIBUTING.md, "How to add a provider".

Copy this file to providers/<name>.py, fill in the three fetch methods, and register the factory
in providers/__init__.py (`_load_builtin`). Nothing else in the codebase needs to change: the
network map, matcher, flags and outputs only see the models returned here.

Rules of thumb:
  - Record what you verified against the live API in the module docstring, with the date.
  - IDs are strings. Platform keys in `ProviderCoin.contracts` must match `ProviderPlatform.key`.
  - Return raw addresses; normalization happens in core/normalize.py.
  - Fill `ProviderPlatform.chain_id` only with real EVM chain IDs; leave it None otherwise.
  - Use HttpClient for every request: it rate-limits, retries, caches and never logs keys.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from cg_id_map.config import Config, env_secret
from cg_id_map.http import HttpClient
from cg_id_map.models import MarketData, ProviderCoin, ProviderPlatform

BASE = "https://api.example.com"


class ExampleProvider:
    name = "example"  # short, lowercase; used in CLI flags, file names and output columns

    def __init__(
        self,
        config: Config,
        *,
        api_key: str | None = None,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        h = config.http
        self.http = HttpClient(
            self.name,
            headers={"X-Api-Key": api_key} if api_key else {},  # keys go in headers, never URLs
            rate_per_min=30,  # use the provider's documented limit, ideally via config.toml
            cache_dir=Path(h.cache_dir) if h.cache_dir else None,
            cache_max_age_hours=h.cache_max_age_hours,
            max_retries=h.max_retries,
            timeout_s=h.timeout_s,
            transport=transport,  # tests pass httpx.MockTransport here
            refresh=refresh,
        )

    @classmethod
    def from_env(cls, config: Config, *, refresh: bool = False) -> ExampleProvider:
        return cls(config, api_key=env_secret("EXAMPLE_API_KEY"), refresh=refresh)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(BASE + path, params)

    def fetch_coins(self) -> list[ProviderCoin]:
        """Every active coin, with its contract addresses (one entry per chain)."""
        raise NotImplementedError

    def fetch_platforms(self) -> list[ProviderPlatform]:
        """Every network referenced by fetch_coins contracts."""
        raise NotImplementedError

    def fetch_market_data(self, ids: Sequence[str]) -> dict[str, MarketData]:
        """USD price and market cap. Batch the IDs (see http.batch_ids); omit unknown IDs."""
        raise NotImplementedError


# In providers/__init__.py, _load_builtin():
#     from cg_id_map.providers import example  # noqa: F401
# and at the bottom of your module:
#     register("example", ExampleProvider.from_env)
