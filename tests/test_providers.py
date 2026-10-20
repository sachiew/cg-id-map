"""Provider adapters and HTTP layer, against mocked transports (no live calls)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from cg_id_map import http as http_mod
from cg_id_map.config import Config, Credentials
from cg_id_map.http import ApiError, HttpClient, batch_ids
from cg_id_map.providers import PROVIDERS
from cg_id_map.providers import cmc as cmc_mod
from cg_id_map.providers.base import Provider
from cg_id_map.providers.coingecko import CoinGecko

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)


def cfg(tmp_path: Path | None = None) -> Config:
    c = Config()
    c.http.cache_dir = str(tmp_path) if tmp_path else ""
    return c


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json=data)


def cmc_ok(data: Any) -> httpx.Response:
    return ok({"status": {"error_code": 0, "error_message": None}, "data": data})


# ------------------------------------------------------------------ CMC


def cmc_row(i: int, platform: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": i,
        "name": f"Coin {i}",
        "symbol": f"C{i}",
        "slug": f"coin-{i}",
        "rank": i,
        "is_active": 1,
        "platform": platform,
    }


ETH_PLATFORM = {"id": 1, "name": "Ethereum", "symbol": "ETH", "slug": "ethereum"}


def make_cmc(handler: Handler, key: str | None = None) -> Any:
    return PROVIDERS["cmc"](key, cfg(), transport=httpx.MockTransport(handler))


def test_cmc_is_a_provider() -> None:
    assert isinstance(make_cmc(lambda r: cmc_ok([])), Provider)


def test_cmc_paginates_map_and_builds_coins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cmc_mod, "MAP_PAGE", 2)
    pages = {
        "1": [cmc_row(1), cmc_row(2, {**ETH_PLATFORM, "token_address": "0xAbC"})],
        "3": [cmc_row(3, {**ETH_PLATFORM, "token_address": "  "})],
    }
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/public-api/v1/cryptocurrency/map"
        assert req.url.params["listing_status"] == "active"
        seen.append(req.url.params["start"])
        return cmc_ok(pages[req.url.params["start"]])

    coins = make_cmc(handler).fetch_coins()
    assert seen == ["1", "3"]
    assert [c.id for c in coins] == ["1", "2", "3"]
    assert coins[1].contracts == [("1", "0xAbC")]
    assert coins[2].contracts == []  # blank address dropped
    assert coins[0].rank == 1 and coins[0].slug == "coin-1"


def test_cmc_keyed_uses_v1_root_and_header() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/cryptocurrency/map"
        assert req.headers["X-CMC_PRO_API_KEY"] == "k"
        return cmc_ok([])

    assert make_cmc(handler, key="k").fetch_coins() == []


def test_cmc_platforms_enriched_from_dex_list() -> None:
    bsc = {"id": 14, "name": "BNB Smart Chain (BEP20)", "symbol": "BNB", "slug": "bnb"}
    sol = {"id": 16, "name": "Solana", "symbol": "SOL", "slug": "solana"}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/dex/platform/list"):
            return cmc_ok(
                [
                    {"id": 14, "n": "BNB Smart Chain (BEP20)", "dn": "BSC", "chId": 56},
                    {"id": 16, "n": "Solana", "dn": "Solana", "chId": -1},
                    {"id": 999, "n": "Unused", "chId": 7},
                ]
            )
        return cmc_ok(
            [
                cmc_row(1, {**bsc, "token_address": "0x1"}),
                cmc_row(2, {**sol, "token_address": "So1"}),
                cmc_row(3, {**bsc, "token_address": "0x2"}),
            ]
        )

    plats = make_cmc(handler).fetch_platforms()
    assert [(p.key, p.chain_id, p.aliases) for p in plats] == [
        ("14", 56, ["BSC"]),
        ("16", None, []),
    ]


def test_cmc_platforms_survive_dex_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/dex/platform/list"):
            return httpx.Response(404, json={})
        return cmc_ok([cmc_row(1, {**ETH_PLATFORM, "token_address": "0x1"})])

    plats = make_cmc(handler).fetch_platforms()
    assert [(p.key, p.chain_id) for p in plats] == [("1", None)]


def test_cmc_market_data_parses_list_and_zero_mcap() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/public-api/v2/simple/price"
        assert req.url.params["include_market_cap"] == "true"
        assert req.url.params["id"] == "1,2,3"
        return cmc_ok(
            [
                {"id": 1, "quotes": [{"symbol": "USD", "price": 80000.0, "market_cap": 1.6e12}]},
                {"id": 2, "quotes": [{"symbol": "USD", "price": 0.01, "market_cap": 0}]},
            ]
        )

    md = make_cmc(handler).fetch_market_data(["3", "1", "2", "1"])
    assert md["1"].price_usd == 80000.0 and md["1"].mcap_usd == 1.6e12
    assert md["2"].mcap_usd is None
    assert "3" not in md


def test_cmc_error_status_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return ok({"status": {"error_code": 1022, "error_message": "limit"}, "data": None})

    with pytest.raises(ApiError, match="1022"):
        make_cmc(handler).fetch_coins()


# ------------------------------------------------------------------ CoinGecko


def make_cg(handler: Handler, tier: str = "pro", key: str | None = "k") -> CoinGecko:
    creds = Credentials(key, tier, None)  # type: ignore[arg-type]
    return CoinGecko(creds, cfg(), transport=httpx.MockTransport(handler))


def test_cg_pro_header_and_base() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "pro-api.coingecko.com"
        assert req.headers["x-cg-pro-api-key"] == "k"
        return ok([{"id": "a", "symbol": "a", "name": "A", "platforms": {"": "", "eth": "0x1"}}])

    coins = make_cg(handler).fetch_coins()
    assert coins[0].platforms == {"eth": "0x1"}  # empty keys/values dropped


def test_cg_public_tier_sends_no_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.coingecko.com"
        assert not any(h.startswith("x-cg-") for h in req.headers)
        return ok([])

    assert make_cg(handler, tier="public", key=None).fetch_platforms() == []


def test_cg_markets_pages_then_simple_price_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import cg_id_map.providers.coingecko as cg_mod

    monkeypatch.setattr(cg_mod, "MARKETS_PAGE", 2)
    markets = {
        "1": [
            {"id": "a", "current_price": 1.0, "market_cap": 10.0, "market_cap_rank": 1},
            {"id": "b", "current_price": 2.0, "market_cap": 0, "market_cap_rank": None},
        ],
        "2": [{"id": "c", "current_price": 3.0, "market_cap": 30.0, "market_cap_rank": 2}],
    }
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/coins/markets"):
            return ok(markets[req.url.params["page"]])
        assert req.url.params["ids"] == "d,e"
        return ok({"d": {"usd": 4.0, "usd_market_cap": 0}, "e": {}})

    cg = make_cg(handler)
    md = cg.fetch_market_data(["a", "b", "d", "e"])
    assert md["a"].mcap_usd == 10.0
    assert md["b"].mcap_usd is None
    assert md["d"].price_usd == 4.0 and md["d"].mcap_usd is None
    assert "e" not in md and "c" not in md
    assert cg.markets()["c"][1] == 2
    assert calls.count("/api/v3/coins/markets") == 2  # memoized


# ------------------------------------------------------------------ HTTP layer


def test_http_retries_on_429_then_succeeds() -> None:
    attempts = iter([httpx.Response(429, headers={"retry-after": "1"}), ok({"x": 1})])
    client = HttpClient(
        "t",
        rate_per_min=0,
        cache_dir=None,
        transport=httpx.MockTransport(lambda r: next(attempts)),
    )
    assert client.get_json("https://example.test/a") == {"x": 1}


def test_http_gives_up_after_max_retries() -> None:
    client = HttpClient(
        "t",
        rate_per_min=0,
        cache_dir=None,
        max_retries=2,
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
    )
    with pytest.raises(ApiError, match="503"):
        client.get_json("https://example.test/a")


def test_http_cache_reuses_response_and_never_stores_headers(tmp_path: Path) -> None:
    hits: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(1)
        return ok({"v": 1})

    def client() -> HttpClient:
        return HttpClient(
            "t",
            headers={"x-cg-pro-api-key": "SECRET"},
            rate_per_min=0,
            cache_dir=tmp_path,
            transport=httpx.MockTransport(handler),
        )

    assert client().get_json("https://example.test/a", {"q": 1}) == {"v": 1}
    assert client().get_json("https://example.test/a", {"q": 1}) == {"v": 1}
    assert len(hits) == 1
    files = list((tmp_path / "t").glob("*.json"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text())
    assert "fetched_at" in entry and "SECRET" not in files[0].read_text()


def test_batch_ids_respects_count_and_chars() -> None:
    assert list(batch_ids(["a", "b", "c"], 2, 100)) == [["a", "b"], ["c"]]
    assert list(batch_ids(["aaaa", "bbbb", "cc"], 10, 9)) == [["aaaa"], ["bbbb", "cc"]]


def test_credentials_repr_hides_keys() -> None:
    r = repr(Credentials("SECRETCG", "pro", "SECRETCMC"))
    assert "SECRET" not in r and "set" in r
