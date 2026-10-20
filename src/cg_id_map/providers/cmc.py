"""CoinMarketCap adapter.

Verified live 2026-10-20:
- /v1/cryptocurrency/map: limit <= 5000, paginate with start; listing_status=active by default.
- /v2/simple/price: data is a list, quotes is a list; market_cap only with include_market_cap.
- /v1/dex/platform/list: undocumented abbreviated fields; id matches map platform.id, chId = EVM
  chain ID (-1 or missing for non-EVM). Optional: the adapter works without it.
Without CMC_API_KEY, requests go to the keyless /public-api prefix (shared per-IP pool).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from cg_id_map.config import Config
from cg_id_map.http import ApiError, HttpClient, batch_ids
from cg_id_map.models import MarketData, ProviderCoin, ProviderPlatform
from cg_id_map.providers import register

log = logging.getLogger(__name__)

BASE = "https://pro-api.coinmarketcap.com"
MAP_PAGE = 5000
PRICE_BATCH = 500
PRICE_MAX_ID_CHARS = 6000


@register("cmc")
class CoinMarketCap:
    name = "cmc"

    def __init__(
        self,
        api_key: str | None,
        config: Config,
        *,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.prefix = BASE if api_key else f"{BASE}/public-api"
        h = config.http
        self.http = HttpClient(
            self.name,
            headers={"X-CMC_PRO_API_KEY": api_key} if api_key else {},
            rate_per_min=h.cmc_rate_per_min_keyed if api_key else h.cmc_rate_per_min_keyless,
            cache_dir=Path(h.cache_dir) if h.cache_dir else None,
            cache_max_age_hours=h.cache_max_age_hours,
            max_retries=h.max_retries,
            timeout_s=h.timeout_s,
            transport=transport,
            refresh=refresh,
        )
        self._map: list[dict[str, Any]] | None = None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        body = self.http.get_json(self.prefix + path, params)
        status = body.get("status") or {}
        if str(status.get("error_code", "0")) != "0":
            raise ApiError(f"cmc {path}: {status.get('error_code')} {status.get('error_message')}")
        return body.get("data")

    def _map_rows(self) -> list[dict[str, Any]]:
        if self._map is None:
            rows: list[dict[str, Any]] = []
            start = 1
            while True:
                page = self._get(
                    "/v1/cryptocurrency/map",
                    {"listing_status": "active", "start": start, "limit": MAP_PAGE},
                )
                rows.extend(page or [])
                if not page or len(page) < MAP_PAGE:
                    break
                start += MAP_PAGE
            self._map = rows
        return self._map

    def fetch_coins(self) -> list[ProviderCoin]:
        coins = []
        for r in self._map_rows():
            if r.get("is_active") == 0:
                continue
            p = r.get("platform")
            contracts = []
            if p and (p.get("token_address") or "").strip():
                contracts.append((str(p["id"]), p["token_address"]))
            coins.append(
                ProviderCoin(
                    id=str(r["id"]),
                    name=r["name"],
                    symbol=r["symbol"],
                    slug=r.get("slug"),
                    rank=r.get("rank"),
                    contracts=contracts,
                )
            )
        return coins

    def fetch_platforms(self) -> list[ProviderPlatform]:
        platforms: dict[str, ProviderPlatform] = {}
        for r in self._map_rows():
            p = r.get("platform")
            if p and str(p["id"]) not in platforms:
                # platform.slug is the native coin's slug (e.g. TON -> "gram"), not a network slug.
                platforms[str(p["id"])] = ProviderPlatform(
                    key=str(p["id"]), name=p["name"], slug=p.get("slug")
                )
        try:
            dex = self._get("/v1/dex/platform/list") or []
        except ApiError as exc:
            log.warning("cmc dex platform list unavailable (%s); continuing without chain IDs", exc)
            dex = []
        for d in dex:
            plat = platforms.get(str(d.get("id")))
            if plat is None:
                continue
            chain_id = d.get("chId")
            if isinstance(chain_id, int) and chain_id > 0:
                plat.chain_id = chain_id
            plat.aliases = sorted({a for a in (d.get("n"), d.get("dn")) if a and a != plat.name})
        return sorted(platforms.values(), key=lambda p: int(p.key))

    def fetch_market_data(self, ids: Sequence[str]) -> dict[str, MarketData]:
        out: dict[str, MarketData] = {}
        for batch in batch_ids(sorted(set(ids), key=int), PRICE_BATCH, PRICE_MAX_ID_CHARS):
            rows = self._get(
                "/v2/simple/price",
                {
                    "id": ",".join(batch),
                    "convert": "USD",
                    "include_market_cap": "true",
                    "skip_invalid": "true",
                },
            )
            for r in rows or []:
                usd = next((q for q in r.get("quotes") or [] if q.get("symbol") == "USD"), None)
                if usd:
                    out[str(r["id"])] = MarketData(
                        price_usd=usd.get("price"), mcap_usd=usd.get("market_cap")
                    )
        return out
