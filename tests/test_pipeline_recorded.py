"""End-to-end dry run on recorded API fixtures (no network).

Covers adapters, network map, matcher and outputs.

Rebuild the fixtures with tests/fixtures/build_fixtures.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import pytest

from cg_id_map.config import Config, Credentials
from cg_id_map.core.flags import Flag, Status
from cg_id_map.core.gold import evaluate, load_gold
from cg_id_map.core.matcher import MatchRow
from cg_id_map.core.networks import NetworkMapping, NetworkStatus
from cg_id_map.core.output import write_published
from cg_id_map.core.overrides import load_coin_overrides, load_network_overrides
from cg_id_map.pipeline import Pipeline
from cg_id_map.providers.cmc import CoinMarketCap
from cg_id_map.providers.coingecko import CoinGecko

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "tests/fixtures/recorded"
GOLD = load_gold(ROOT / "tests/gold/cmc.yaml")


@cache
def rec(name: str) -> Any:
    return json.loads((REC / name).read_text())


def handler(req: httpx.Request) -> httpx.Response:
    path, q = req.url.path, req.url.params
    if path.endswith("/cryptocurrency/map"):
        body = rec("cmc_map.json")
        return httpx.Response(200, json=body if q["start"] == "1" else {**body, "data": []})
    if path.endswith("/dex/platform/list"):
        return httpx.Response(200, json=rec("cmc_dex_platforms.json"))
    if path.endswith("/v2/simple/price"):
        ids = set(q["id"].split(","))
        body = rec("cmc_prices.json")
        return httpx.Response(
            200, json={**body, "data": [r for r in body["data"] if str(r["id"]) in ids]}
        )
    if path.endswith("/coins/list"):
        return httpx.Response(200, json=rec("cg_coins_list.json"))
    if path.endswith("/asset_platforms"):
        return httpx.Response(200, json=rec("cg_asset_platforms.json"))
    if path.endswith("/coins/markets"):
        page = int(q["page"])
        data = rec("cg_markets.json")
        return httpx.Response(200, json=data[(page - 1) * 250 : page * 250])
    if path.endswith("/simple/price"):
        ids = set(q["ids"].split(","))
        return httpx.Response(
            200, json={k: v for k, v in rec("cg_simple_price.json").items() if k in ids}
        )
    return httpx.Response(404, json={"error": f"unexpected {path}"})


@pytest.fixture(scope="module")
def result() -> tuple[list[MatchRow], list[NetworkMapping]]:
    cfg = Config()
    cfg.http.cache_dir = ""
    cfg.http.cmc_rate_per_min_keyless = 0  # no rate limiting against the mock
    cfg.http.cg_rate_per_min = {"pro": 0, "demo": 0, "public": 0}
    transport = httpx.MockTransport(handler)
    p = Pipeline(
        provider=CoinMarketCap(cfg, transport=transport),
        cg=CoinGecko(Credentials("k", "pro"), cfg, transport=transport),
        config=cfg,
        overrides_dir=ROOT / "overrides",
    )
    inp = p.load()
    nets = p.networks(inp)
    return p.match(inp, nets), nets


def test_gold_set_resolves_with_full_precision(
    result: tuple[list[MatchRow], list[NetworkMapping]],
) -> None:
    rows, _ = result
    gold = evaluate(rows, GOLD)
    assert gold is not None and gold.total == len(GOLD) >= 30
    assert gold.failures == [], gold.failures


def test_major_networks_are_mapped(result: tuple[list[MatchRow], list[NetworkMapping]]) -> None:
    _, nets = result
    accepted = {n.key: n.cg_platform_id for n in nets if n.status is NetworkStatus.ACCEPTED}
    assert accepted["1"] == "ethereum"
    assert accepted["14"] == "binance-smart-chain"
    assert accepted["16"] == "solana"


def test_copycats_are_not_accepted(result: tuple[list[MatchRow], list[NetworkMapping]]) -> None:
    rows, _ = result
    by_id = {r.provider_id: r for r in rows}
    for copycat in ("31093", "38861"):  # second Dogecoin / NEO listings on CMC
        assert by_id[copycat].status is not Status.ACCEPTED
        assert Flag.MANY_TO_ONE in by_id[copycat].flags


def test_every_row_is_consistent(result: tuple[list[MatchRow], list[NetworkMapping]]) -> None:
    rows, _ = result
    for r in rows:
        assert (r.status is Status.ACCEPTED) == (r.cg_id is not None), r.provider_id
        if r.status in (Status.AMBIGUOUS, Status.FLAGGED):
            assert r.suggested_cg_id and r.candidates, r.provider_id


def test_published_output_is_stable(
    result: tuple[list[MatchRow], list[NetworkMapping]], tmp_path: Path
) -> None:
    rows, nets = result
    gold = evaluate(rows, GOLD)
    t = Config().thresholds
    write_published(tmp_path, "cmc", rows, nets, t, datetime(2026, 10, 20, tzinfo=UTC), gold)
    first = {f.name: f.read_bytes() for f in tmp_path.iterdir()}
    changes = write_published(
        tmp_path, "cmc", rows, nets, t, datetime(2026, 10, 21, tzinfo=UTC), gold
    )
    assert not changes.any
    assert first == {f.name: f.read_bytes() for f in tmp_path.iterdir()}
    assert "Precision: 34/34 (100.0%)" in (tmp_path / "report.md").read_text()


def test_checked_in_overrides_are_valid() -> None:
    # Schema and duplicate checks; CG-ID existence is checked against live data on each run.
    load_network_overrides(ROOT / "overrides/networks.cmc.yaml")
    load_coin_overrides(ROOT / "overrides/coins.cmc.yaml")
