"""Provider-neutral data models. The matcher, network map and outputs only use these."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProviderCoin(BaseModel):
    """A coin as listed by a non-CG provider. IDs are strings so any provider fits."""

    id: str
    name: str
    symbol: str
    slug: str | None = None
    rank: int | None = None
    # (provider platform key, raw address). A list: some providers list several chains.
    contracts: list[tuple[str, str]] = Field(default_factory=list)


class ProviderPlatform(BaseModel):
    """A network as named by a non-CG provider."""

    key: str
    name: str
    slug: str | None = None
    # EVM chain ID when the provider exposes one; None when unknown or non-EVM.
    chain_id: int | None = None
    # Extra display names usable for fuzzy name matching (e.g. CMC dex "dn").
    aliases: list[str] = Field(default_factory=list)


class MarketData(BaseModel):
    """USD price and market cap. A zero or negative value means unknown and is stored as None."""

    price_usd: float | None = None
    mcap_usd: float | None = None

    @field_validator("price_usd", "mcap_usd")
    @classmethod
    def _non_positive_is_missing(cls, v: float | None) -> float | None:
        return v if v is not None and v > 0 else None


class CGCoin(BaseModel):
    id: str
    symbol: str
    name: str
    # {cg platform id: raw address}
    platforms: dict[str, str] = Field(default_factory=dict)


class CGPlatform(BaseModel):
    id: str
    name: str
    shortname: str = ""
    chain_identifier: int | None = None
    native_coin_id: str | None = None
