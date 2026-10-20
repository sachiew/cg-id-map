"""Human-maintained overrides in overrides/{networks,coins}.<provider>.yaml.

Both files are YAML lists. A null CG ID means "this has no CoinGecko equivalent".

    # networks.cmc.yaml
    - key: "14"                       # provider platform key
      cg_platform_id: binance-smart-chain
      reason: why this pin exists

    # coins.cmc.yaml
    - id: "1027"                      # provider coin ID
      cg_id: ethereum
      reason: why this pin exists
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class NetworkOverride(BaseModel):
    key: str
    cg_platform_id: str | None
    reason: str


class CoinOverride(BaseModel):
    id: str
    cg_id: str | None
    reason: str


def _load_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a YAML list")
    return data


def load_network_overrides(path: Path) -> dict[str, NetworkOverride]:
    out: dict[str, NetworkOverride] = {}
    for raw in _load_list(path):
        o = NetworkOverride(**{**raw, "key": str(raw.get("key"))})
        if o.key in out:
            raise ValueError(f"{path}: duplicate key {o.key}")
        out[o.key] = o
    return out


def load_coin_overrides(path: Path) -> dict[str, CoinOverride]:
    out: dict[str, CoinOverride] = {}
    for raw in _load_list(path):
        o = CoinOverride(**{**raw, "id": str(raw.get("id"))})
        if o.id in out:
            raise ValueError(f"{path}: duplicate id {o.id}")
        out[o.id] = o
    return out


def validate_targets(kind: str, targets: set[str | None], known: set[str]) -> None:
    """Fail fast on typos: every non-null override target must exist on CoinGecko."""
    unknown = sorted(t for t in targets if t is not None and t not in known)
    if unknown:
        raise ValueError(f"{kind} overrides point to unknown CoinGecko IDs: {unknown}")
