"""The steps shared by the CLI commands and the daily workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from cg_id_map.config import Config, Credentials
from cg_id_map.core.matcher import CoinPlan, Matcher, MatchRow, match_all
from cg_id_map.core.networks import CGAddressIndex, NetworkMapping, build_network_map
from cg_id_map.core.overrides import (
    load_coin_overrides,
    load_network_overrides,
    validate_targets,
)
from cg_id_map.models import CGCoin, CGPlatform, MarketData, ProviderCoin, ProviderPlatform
from cg_id_map.providers import PROVIDERS
from cg_id_map.providers.base import Provider
from cg_id_map.providers.coingecko import CoinGecko

log = logging.getLogger(__name__)


@dataclass
class Inputs:
    coins: list[ProviderCoin]
    platforms: list[ProviderPlatform]
    cg_coins: list[CGCoin]
    cg_platforms: list[CGPlatform]
    index: CGAddressIndex


@dataclass
class Pipeline:
    provider: Provider
    cg: CoinGecko
    config: Config
    overrides_dir: Path = Path("overrides")

    @classmethod
    def create(
        cls, provider_name: str, config: Config, *, refresh: bool = False, overrides_dir: Path
    ) -> Pipeline:
        if provider_name not in PROVIDERS:
            raise ValueError(f"unknown provider {provider_name!r}; known: {sorted(PROVIDERS)}")
        creds = Credentials.from_env()
        key = creds.cmc_api_key if provider_name == "cmc" else None
        provider = PROVIDERS[provider_name](key, config, refresh=refresh)
        return cls(provider, CoinGecko(creds, config, refresh=refresh), config, overrides_dir)

    @property
    def name(self) -> str:
        return self.provider.name

    def load(self) -> Inputs:
        log.info("fetching %s coins and platforms", self.name)
        coins, platforms = self.provider.fetch_coins(), self.provider.fetch_platforms()
        log.info("fetching CoinGecko coins and platforms")
        cg_coins, cg_platforms = self.cg.fetch_coins(), self.cg.fetch_platforms()
        return Inputs(
            coins, platforms, cg_coins, cg_platforms, CGAddressIndex(cg_coins, cg_platforms)
        )

    def networks(self, inp: Inputs) -> list[NetworkMapping]:
        overrides = load_network_overrides(self.overrides_dir / f"networks.{self.name}.yaml")
        validate_targets(
            "network",
            {o.cg_platform_id for o in overrides.values()},
            {p.id for p in inp.cg_platforms},
        )
        return build_network_map(
            inp.platforms, inp.coins, inp.cg_platforms, inp.index, overrides, self.config.thresholds
        )

    def matcher(self, inp: Inputs, networks: list[NetworkMapping]) -> Matcher:
        overrides = load_coin_overrides(self.overrides_dir / f"coins.{self.name}.yaml")
        validate_targets(
            "coin", {o.cg_id for o in overrides.values()}, {c.id for c in inp.cg_coins}
        )
        return Matcher(inp.cg_coins, inp.index, networks, overrides, self.config.thresholds)

    def market_data(
        self, plans: list[CoinPlan]
    ) -> tuple[dict[str, MarketData], dict[str, MarketData]]:
        prov_ids, cg_ids = Matcher.market_ids(plans)
        log.info(
            "fetching market data: %d %s ids, %d CoinGecko ids",
            len(prov_ids),
            self.name,
            len(cg_ids),
        )
        return self.provider.fetch_market_data(sorted(prov_ids)), self.cg.fetch_market_data(
            sorted(cg_ids)
        )

    def match(self, inp: Inputs, networks: list[NetworkMapping]) -> list[MatchRow]:
        m = self.matcher(inp, networks)
        plans = [m.plan(c) for c in inp.coins]
        prov_md, cg_md = self.market_data(plans)
        return match_all(m, plans, prov_md, cg_md)

    def lookup(self, inp: Inputs, networks: list[NetworkMapping], provider_id: str) -> MatchRow:
        """Match one coin. Many-to-one checks need the full run, so they are not applied here."""
        coin = next((c for c in inp.coins if c.id == provider_id), None)
        if coin is None:
            raise KeyError(f"{self.name} id {provider_id} not found among active coins")
        m = self.matcher(inp, networks)
        plan = m.plan(coin)
        prov_md, cg_md = self.market_data([plan])
        return m.decide(plan, prov_md, cg_md)
