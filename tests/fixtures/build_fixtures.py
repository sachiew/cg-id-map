"""Rebuild tests/fixtures/recorded/ from a local .cache/ (filled by `cg-id-map fetch`).

The recorded fixtures are a small, trimmed subset of real API responses: the gold-set coins, the
top CMC coins, copycats and tokens on non-EVM networks, plus every CoinGecko coin that could be a
candidate for them. They let CI run the whole pipeline with no network access.

    uv run python tests/fixtures/build_fixtures.py
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from cg_id_map.core.normalize import name_key, symbol_key

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
OUT = Path(__file__).resolve().parent / "recorded"
TOP_N = 150
EXTRA_CMC_IDS = {"31093", "38861", "1343", "35697", "4172", "40000", "1503", "7257"}
PER_NETWORK = {"16": 15, "29": 10, "176": 6, "93": 5}  # Solana, Cardano, Sui, Hedera


def entries(provider: str) -> Iterator[dict[str, Any]]:
    for path in sorted((CACHE / provider).glob("*.json")):
        yield json.loads(path.read_text())


def by_path(provider: str, suffix: str) -> list[dict[str, Any]]:
    return [e for e in entries(provider) if e["url"].endswith(suffix)]


def dump(name: str, data: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    gold = {str(g["id"]) for g in yaml.safe_load((ROOT / "tests/gold/cmc.yaml").read_text())}

    cmc_rows = [r for e in by_path("cmc", "/cryptocurrency/map") for r in e["data"]["data"]]
    keep = set(gold) | EXTRA_CMC_IDS
    keep |= {str(r["id"]) for r in cmc_rows if r.get("rank") and r["rank"] <= TOP_N}
    for net, n in PER_NETWORK.items():
        on_net = [r for r in cmc_rows if r["platform"] and str(r["platform"]["id"]) == net]
        keep |= {str(r["id"]) for r in sorted(on_net, key=lambda r: r["rank"])[:n]}
    cmc_sel = sorted((r for r in cmc_rows if str(r["id"]) in keep), key=lambda r: r["id"])

    dex = by_path("cmc", "/dex/platform/list")[0]["data"]["data"]
    plat_ids = {r["platform"]["id"] for r in cmc_sel if r["platform"]}
    prices = [
        r
        for e in by_path("cmc", "/v2/simple/price")
        for r in e["data"]["data"]
        if str(r["id"]) in keep
    ]

    cg_list = by_path("cg", "/coins/list")[0]["data"]
    names = {name_key(r["name"]) for r in cmc_sel}
    symbols = {symbol_key(r["symbol"]) for r in cmc_sel}
    slugs = {r["slug"] for r in cmc_sel}
    addrs = {r["platform"]["token_address"].strip().lower() for r in cmc_sel if r["platform"]}
    cg_sel = [
        c
        for c in cg_list
        if symbol_key(c["symbol"]) in symbols
        or name_key(c["name"]) in names
        or c["id"] in slugs
        or any((a or "").strip().lower() in addrs for a in (c.get("platforms") or {}).values())
    ]
    cg_ids = {c["id"] for c in cg_sel}
    cg_plats = {p for c in cg_sel for p in (c.get("platforms") or {})}
    platforms = [
        {k: v for k, v in p.items() if k != "image"}
        for p in by_path("cg", "/asset_platforms")[0]["data"]
        if p["id"] in cg_plats
    ]
    market_fields = ("id", "current_price", "market_cap", "market_cap_rank")
    markets = [
        {k: r.get(k) for k in market_fields}
        for e in by_path("cg", "/coins/markets")
        for r in e["data"]
        if r["id"] in cg_ids
    ]
    simple: dict[str, Any] = {}
    for e in by_path("cg", "/simple/price"):
        simple |= {k: v for k, v in e["data"].items() if k in cg_ids}

    ok = {"timestamp": "recorded", "error_code": 0, "error_message": None}
    dump("cmc_map.json", {"status": ok, "data": cmc_sel})
    dump("cmc_dex_platforms.json", {"status": ok, "data": [d for d in dex if d["id"] in plat_ids]})
    dump("cmc_prices.json", {"status": ok, "data": prices})
    dump("cg_coins_list.json", cg_sel)
    dump("cg_asset_platforms.json", platforms)
    dump("cg_markets.json", markets)
    dump("cg_simple_price.json", simple)
    print(
        f"cmc {len(cmc_sel)} coins, {len(prices)} prices | cg {len(cg_sel)} coins, "
        f"{len(platforms)} platforms, {len(markets)} markets, {len(simple)} simple prices"
    )


if __name__ == "__main__":
    main()
