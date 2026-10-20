"""Settings: API keys from env (or a local .env file) and thresholds from config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

CGTier = Literal["pro", "demo", "public"]

CG_BASE_URLS: dict[str, str] = {
    "pro": "https://pro-api.coingecko.com/api/v3",
    "demo": "https://api.coingecko.com/api/v3",
    "public": "https://api.coingecko.com/api/v3",
}
CG_KEY_HEADERS: dict[str, str] = {"pro": "x-cg-pro-api-key", "demo": "x-cg-demo-api-key"}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables that are already set."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Credentials:
    cg_api_key: str | None
    cg_tier: CGTier
    cmc_api_key: str | None

    def __repr__(self) -> str:  # never show key values
        return (
            f"Credentials(cg_api_key={'set' if self.cg_api_key else None}, "
            f"cg_tier={self.cg_tier!r}, cmc_api_key={'set' if self.cmc_api_key else None})"
        )

    @classmethod
    def from_env(cls) -> Credentials:
        load_dotenv()
        cg_key = os.environ.get("CG_API_KEY") or None
        tier = (os.environ.get("CG_API_TIER") or ("pro" if cg_key else "public")).lower()
        if tier not in CG_BASE_URLS:
            raise ValueError(f"CG_API_TIER must be one of pro|demo|public, got {tier!r}")
        if tier != "public" and not cg_key:
            raise ValueError(f"CG_API_TIER={tier} needs CG_API_KEY (or use CG_API_TIER=public)")
        return cls(cg_key, tier, os.environ.get("CMC_API_KEY") or None)  # type: ignore[arg-type]


@dataclass
class Thresholds:
    # Network map (Step 1)
    network_min_overlap: int = 20
    network_lead_ratio: float = 2.0
    network_min_name_score: float = 70.0
    # Small networks can never reach network_min_overlap; accept them (medium) on strong evidence.
    network_small_min_overlap: int = 3
    network_small_min_share: float = 0.5
    network_small_min_name_score: float = 90.0
    # Name matching (Steps 3-4)
    name_fuzzy_min: float = 85.0
    price_diff_pct: float = 5.0
    mcap_diff_pct: float = 25.0
    # Daily-run safety checks
    min_coin_count_ratio: float = 0.90
    max_match_rate_drop_pts: float = 2.0
    max_top1000_match_rate_drop_pts: float = 0.0
    max_cg_id_change_ratio: float = 0.01


@dataclass
class HttpSettings:
    cache_dir: str = ".cache"
    cache_max_age_hours: float = 20.0
    max_retries: int = 5
    timeout_s: float = 60.0
    # Requests per minute; tier/key dependent defaults are applied by the providers.
    cg_rate_per_min: dict[str, float] = field(
        default_factory=lambda: {"pro": 250.0, "demo": 30.0, "public": 3.0}
    )
    cmc_rate_per_min_keyed: float = 25.0
    cmc_rate_per_min_keyless: float = 4.0


@dataclass
class Config:
    thresholds: Thresholds = field(default_factory=Thresholds)
    http: HttpSettings = field(default_factory=HttpSettings)

    @classmethod
    def load(cls, path: Path = Path("config.toml")) -> Config:
        cfg = cls()
        if path.is_file():
            raw = tomllib.loads(path.read_text())
            _apply(cfg.thresholds, raw.get("thresholds", {}))
            _apply(cfg.http, raw.get("http", {}))
        return cfg


def _apply(target: Any, values: dict[str, Any]) -> None:
    known = {f.name for f in fields(target)}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"unknown config key {key!r} in [{type(target).__name__}]")
        setattr(target, key, value)
