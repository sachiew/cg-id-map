"""CoinGecko client. CG is the hub every provider maps to, so it is not a `Provider`.

Verified live 2026-10-20:
- /coins/list?include_platform=true: active coins with {platform_id: address}.
- /coins/markets: per_page max 250 (larger silently falls back to 100); covers priced coins only.
- /simple/price: batch limit is URL length; unpriced coins return {}; unknown mcap returns 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from cg_id_map.config import CG_BASE_URLS, CG_KEY_HEADERS, Config, Credentials
from cg_id_map.http import HttpClient, batch_ids
from cg_id_map.models import CGCoin, CGPlatform, MarketData

MARKETS_PAGE = 250
PRICE_BATCH = 500
PRICE_MAX_ID_CHARS = 6000


class CoinGecko:
    def __init__(
        self,
        creds: Credentials,
        config: Config,
        *,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base = CG_BASE_URLS[creds.cg_tier]
        headers = {}
        if creds.cg_tier in CG_KEY_HEADERS and creds.cg_api_key:
            headers[CG_KEY_HEADERS[creds.cg_tier]] = creds.cg_api_key
        h = config.http
        self.http = HttpClient(
            "cg",
            headers=headers,
            rate_per_min=h.cg_rate_per_min[creds.cg_tier],
            cache_dir=Path(h.cache_dir) if h.cache_dir else None,
            cache_max_age_hours=h.cache_max_age_hours,
            max_retries=h.max_retries,
            timeout_s=h.timeout_s,
            transport=transport,
            refresh=refresh,
        )
        self._markets: dict[str, tuple[MarketData, int | None]] | None = None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(self.base + path, params)

    def fetch_coins(self) -> list[CGCoin]:
        rows = self._get("/coins/list", {"include_platform": "true"})
        return [
            CGCoin(
                id=r["id"],
                symbol=r["symbol"],
                name=r["name"],
                platforms={k: v for k, v in (r.get("platforms") or {}).items() if k and v},
            )
            for r in rows
        ]

    def fetch_platforms(self) -> list[CGPlatform]:
        rows = self._get("/asset_platforms")
        return [
            CGPlatform(
                id=r["id"],
                name=r.get("name") or r["id"],
                shortname=r.get("shortname") or "",
                chain_identifier=r.get("chain_identifier"),
                native_coin_id=r.get("native_coin_id"),
            )
            for r in rows
        ]

    def markets(self) -> dict[str, tuple[MarketData, int | None]]:
        """All priced coins: {cg_id: (market data, market_cap_rank)}, paged until exhausted."""
        if self._markets is None:
            out: dict[str, tuple[MarketData, int | None]] = {}
            page = 1
            while True:
                rows = self._get(
                    "/coins/markets",
                    {"vs_currency": "usd", "per_page": MARKETS_PAGE, "page": page},
                )
                for r in rows or []:
                    md = MarketData(price_usd=r.get("current_price"), mcap_usd=r.get("market_cap"))
                    out[r["id"]] = (md, r.get("market_cap_rank"))
                if not rows or len(rows) < MARKETS_PAGE:
                    break
                page += 1
            self._markets = out
        return self._markets

    def fetch_market_data(self, ids: Sequence[str]) -> dict[str, MarketData]:
        """Market data from the bulk markets list, falling back to /simple/price for the rest."""
        bulk = self.markets()
        out = {i: bulk[i][0] for i in ids if i in bulk}
        missing = sorted(set(ids) - out.keys())
        for batch in batch_ids(missing, PRICE_BATCH, PRICE_MAX_ID_CHARS):
            data = self._get(
                "/simple/price",
                {"ids": ",".join(batch), "vs_currencies": "usd", "include_market_cap": "true"},
            )
            for cg_id, v in (data or {}).items():
                if v:
                    out[cg_id] = MarketData(
                        price_usd=v.get("usd"), mcap_usd=v.get("usd_market_cap")
                    )
        return out
