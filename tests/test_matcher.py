"""Matcher: every status/flag path, many-to-one, ambiguity and override precedence."""

from __future__ import annotations

from cg_id_map.config import Thresholds
from cg_id_map.core.flags import Confidence, Flag, Method, Status
from cg_id_map.core.matcher import Matcher, MatchRow, match_all
from cg_id_map.core.networks import (
    CGAddressIndex,
    NetworkMapping,
    NetworkMethod,
    NetworkStatus,
)
from cg_id_map.core.overrides import CoinOverride
from cg_id_map.models import CGCoin, CGPlatform, MarketData, ProviderCoin

USDT_ETH = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
CG_PLATFORMS = [
    CGPlatform(id="ethereum", name="Ethereum", chain_identifier=1),
    CGPlatform(id="binance-smart-chain", name="BNB Smart Chain", chain_identifier=56),
]


def net(key: str, cg: str | None, status: NetworkStatus = NetworkStatus.ACCEPTED) -> NetworkMapping:
    return NetworkMapping(
        key=key, name=key, slug=None, chain_id=None, token_count=1,
        cg_platform_id=cg if status is NetworkStatus.ACCEPTED else None,
        suggested_cg_platform_id=cg, chain_identifier=None,
        method=NetworkMethod.CHAIN_ID_OVERLAP, status=status, confidence="high",
        overlap_count=1, overlap_share=1.0, runner_up=None, runner_up_count=0, name_score=100,
    )  # fmt: skip


NETWORKS = [
    net("1", "ethereum"),
    net("14", "binance-smart-chain"),
    net("99", None, NetworkStatus.UNMAPPED),
]


def cg(id: str, symbol: str, name: str, **platforms: str) -> CGCoin:
    return CGCoin(
        id=id,
        symbol=symbol,
        name=name,
        platforms={k.replace("_", "-"): v for k, v in platforms.items()},
    )


def pc(
    id: str,
    name: str,
    symbol: str,
    slug: str | None = None,
    contracts: list[tuple[str, str]] | None = None,
) -> ProviderCoin:
    return ProviderCoin(
        id=id, name=name, symbol=symbol, slug=slug, rank=int(id), contracts=contracts or []
    )


def run(
    coins: list[ProviderCoin],
    cg_coins: list[CGCoin],
    prov_md: dict[str, MarketData] | None = None,
    cg_md: dict[str, MarketData] | None = None,
    overrides: dict[str, CoinOverride] | None = None,
) -> dict[str, MatchRow]:
    m = Matcher(
        cg_coins, CGAddressIndex(cg_coins, CG_PLATFORMS), NETWORKS, overrides or {}, Thresholds()
    )
    plans = [m.plan(c) for c in coins]
    rows = match_all(m, plans, prov_md or {}, cg_md or {})
    return {r.provider_id: r for r in rows}


def md(price: float | None, mcap: float | None = None) -> MarketData:
    return MarketData(price_usd=price, mcap_usd=mcap)


# ------------------------------------------------------------------ Step 2: contracts


def test_contract_match_is_high_and_case_insensitive_on_evm() -> None:
    r = run(
        [pc("825", "Tether USDt", "USDT", contracts=[("1", USDT_ETH.lower())])],
        [cg("tether", "usdt", "Tether", ethereum=USDT_ETH)],
    )["825"]
    assert (r.cg_id, r.status, r.method, r.confidence) == (
        "tether",
        Status.ACCEPTED,
        Method.CONTRACT,
        Confidence.HIGH,
    )


def test_contract_match_ignores_name_differences_but_flags_them() -> None:
    r = run(
        [pc("1", "Old Brand", "OLD", contracts=[("1", "0x" + "a" * 40)])],
        [cg("new-brand", "new", "New Brand", ethereum="0x" + "A" * 40)],
    )["1"]
    assert r.status is Status.ACCEPTED and r.method is Method.CONTRACT
    assert Flag.NAME_MISMATCH in r.flags and Flag.SYMBOL_MISMATCH in r.flags


def test_contract_with_multiple_cg_ids_is_ambiguous() -> None:
    addr = "0x" + "b" * 40
    r = run(
        [pc("2", "Foo", "FOO", contracts=[("1", addr)])],
        [cg("foo-a", "fa", "Foo A", ethereum=addr), cg("foo-b", "fb", "Foo B", ethereum=addr)],
    )["2"]
    assert r.status is Status.AMBIGUOUS and r.cg_id is None
    assert Flag.AMBIGUOUS_CONTRACT_MULTIPLE_CG in r.flags
    assert {c.cg_id for c in r.candidates} >= {"foo-a", "foo-b"}


def test_contract_with_multiple_cg_ids_resolved_by_exact_name_symbol() -> None:
    addr = "0x" + "c" * 40
    r = run(
        [pc("3", "Foo", "FOO", contracts=[("1", addr)])],
        [cg("foo", "foo", "Foo", ethereum=addr), cg("foo-old", "foo", "Foo (old)x", ethereum=addr)],
    )["3"]
    assert (r.cg_id, r.status, r.confidence) == ("foo", Status.ACCEPTED, Confidence.MEDIUM)
    assert Flag.AMBIGUOUS_CONTRACT_MULTIPLE_CG in r.flags


def test_contract_on_other_network_with_same_symbol_is_medium() -> None:
    addr = "0x" + "d" * 40
    r = run(
        [pc("4", "Bridged", "BRG", contracts=[("14", addr)])],
        [cg("bridged", "brg", "Bridged Token", ethereum=addr)],
    )["4"]
    assert (r.cg_id, r.method, r.confidence) == (
        "bridged",
        Method.CONTRACT_OTHER_NETWORK,
        Confidence.MEDIUM,
    )
    assert Flag.CONTRACT_OTHER_NETWORK in r.flags


def test_contract_on_other_network_with_different_symbol_is_not_accepted() -> None:
    addr = "0x" + "e" * 40
    r = run(
        [pc("5", "Alpha", "ALP", contracts=[("14", addr)])],
        [cg("beta", "bet", "Beta", ethereum=addr)],
        prov_md={"5": md(1.0)},
        cg_md={"beta": md(9.0)},
    )["5"]
    assert r.status is not Status.ACCEPTED and r.cg_id is None
    assert Flag.CONTRACT_OTHER_NETWORK in r.flags and r.suggested_cg_id == "beta"


def test_unmapped_network_falls_through_to_name_matching() -> None:
    r = run(
        [pc("6", "Runestone", "RUNE", contracts=[("99", "840000:3")])],
        [cg("runestone", "rune", "Runestone")],
    )["6"]
    assert (r.cg_id, r.method) == ("runestone", Method.NAME_SYMBOL)
    assert Flag.NETWORK_UNMAPPED in r.flags


# ------------------------------------------------------------------ Step 3: names


def test_unique_exact_name_and_symbol_needs_no_market_data() -> None:
    r = run(
        [pc("1", "Bitcoin", "BTC", slug="bitcoin")],
        [cg("bitcoin", "btc", "Bitcoin"), cg("bitcoin-cash", "bch", "Bitcoin Cash")],
    )["1"]
    assert (r.cg_id, r.method, r.confidence) == ("bitcoin", Method.NAME_SYMBOL, Confidence.HIGH)
    assert r.flags == []


def test_missing_mcap_never_blocks_an_exact_match() -> None:
    r = run(
        [pc("7", "Novacoin", "NVC")],
        [cg("novacoin", "nvc", "Novacoin")],
        prov_md={"7": md(0.02, None)},
        cg_md={"novacoin": md(0.02, None)},
    )["7"]
    assert r.status is Status.ACCEPTED and Flag.NO_MARKET_DATA not in r.flags


def test_accepted_match_gets_informational_price_discrepancy() -> None:
    r = run(
        [pc("8", "Gizmo", "GIZ")],
        [cg("gizmo", "giz", "Gizmo")],
        prov_md={"8": md(1.0)},
        cg_md={"gizmo": md(2.0)},
    )["8"]
    assert r.status is Status.ACCEPTED and Flag.PRICE_DISCREPANCY in r.flags
    assert r.price_diff_pct == 100.0


def test_duplicate_exact_names_resolved_by_slug() -> None:
    r = run(
        [pc("9", "Pepe", "PEPE", slug="pepe")],
        [cg("pepe", "pepe", "Pepe"), cg("pepe-on-sol", "pepe", "Pepe")],
    )["9"]
    assert (r.cg_id, r.method, r.confidence) == ("pepe", Method.NAME_SYMBOL, Confidence.HIGH)


def test_duplicate_exact_names_resolved_by_price_guardrail() -> None:
    r = run(
        [pc("10", "Pepe", "PEPE", slug="pepe-cmc")],
        [cg("pepe-a", "pepe", "Pepe"), cg("pepe-b", "pepe", "Pepe")],
        prov_md={"10": md(1.00, 100.0)},
        cg_md={"pepe-a": md(1.02, 110.0), "pepe-b": md(5.0, 100.0)},
    )["10"]
    assert (r.cg_id, r.method, r.confidence) == ("pepe-a", Method.NAME_PRICE, Confidence.MEDIUM)


def test_mcap_guardrail_applies_when_both_sides_have_it() -> None:
    r = run(
        [pc("11", "Pepe", "PEPE")],
        [cg("pepe-a", "pepe", "Pepe"), cg("pepe-b", "pepe", "Pepe")],
        prov_md={"11": md(1.0, 100.0)},
        cg_md={"pepe-a": md(1.0, 1000.0), "pepe-b": md(1.0, 105.0)},
    )["11"]
    assert r.cg_id == "pepe-b"


def test_duplicate_exact_names_both_within_price_is_ambiguous() -> None:
    r = run(
        [pc("12", "Pepe", "PEPE")],
        [cg("pepe-a", "pepe", "Pepe"), cg("pepe-b", "pepe", "Pepe")],
        prov_md={"12": md(1.0)},
        cg_md={"pepe-a": md(1.01), "pepe-b": md(0.99)},
    )["12"]
    assert r.status is Status.AMBIGUOUS and Flag.AMBIGUOUS_MULTIPLE_CANDIDATES in r.flags
    assert r.suggested_cg_id in {"pepe-a", "pepe-b"} and len(r.candidates) == 2


def test_fuzzy_name_accepted_by_price_with_name_mismatch() -> None:
    r = run(
        [pc("13", "Tether USDt", "USDT")],
        [cg("tether", "usdt", "Tether")],
        prov_md={"13": md(1.0)},
        cg_md={"tether": md(1.001)},
    )["13"]
    assert (r.cg_id, r.method, r.confidence) == ("tether", Method.NAME_PRICE, Confidence.MEDIUM)
    assert Flag.NAME_MISMATCH in r.flags


def test_rebrand_same_name_different_ticker_needs_price() -> None:
    r = run(
        [pc("14", "Bitcoin", "XBT")],
        [cg("bitcoin", "btc", "Bitcoin")],
        prov_md={"14": md(80000.0)},
        cg_md={"bitcoin": md(80100.0)},
    )["14"]
    assert (r.cg_id, r.method) == ("bitcoin", Method.NAME_PRICE)
    assert Flag.SYMBOL_MISMATCH in r.flags


def test_name_symbol_match_with_price_outside_threshold_is_flagged() -> None:
    r = run(
        [pc("15", "Tether USDt", "USDT")],
        [cg("tether", "usdt", "Tether")],
        prov_md={"15": md(1.0)},
        cg_md={"tether": md(1.5)},
    )["15"]
    assert (r.status, r.cg_id, r.suggested_cg_id) == (Status.FLAGGED, None, "tether")
    assert Flag.PRICE_DISCREPANCY in r.flags


def test_mcap_discrepancy_is_flagged() -> None:
    r = run(
        [pc("16", "Tether USDt", "USDT")],
        [cg("tether", "usdt", "Tether")],
        prov_md={"16": md(1.0, 100.0)},
        cg_md={"tether": md(1.0, 300.0)},
    )["16"]
    assert r.status is Status.FLAGGED and Flag.MCAP_DISCREPANCY in r.flags


def test_uncertain_without_provider_price_is_no_market_data() -> None:
    r = run([pc("17", "Tether USDt", "USDT")], [cg("tether", "usdt", "Tether")])["17"]
    assert (r.status, r.confidence) == (Status.FLAGGED, Confidence.LOW)
    assert Flag.NO_MARKET_DATA in r.flags


def test_uncertain_without_cg_price_is_no_market_data() -> None:
    r = run(
        [pc("18", "Tether USDt", "USDT")], [cg("tether", "usdt", "Tether")], prov_md={"18": md(1.0)}
    )["18"]
    assert r.status is Status.FLAGGED and Flag.NO_MARKET_DATA in r.flags


# ------------------------------------------------------------------ Step 4


def test_symbol_collision_with_unrelated_names_is_ambiguous() -> None:
    r = run(
        [pc("19", "Graph Token", "GRT")],
        [
            cg("the-graph", "grt", "The Graph Protocol"),
            cg("golden-ratio", "grt", "Golden Ratio Token"),
        ],
        prov_md={"19": md(0.1)},
    )["19"]
    assert r.status is Status.AMBIGUOUS and Flag.AMBIGUOUS_MULTIPLE_CANDIDATES in r.flags
    assert len(r.candidates) == 2


def test_no_candidates_is_unmatched() -> None:
    r = run([pc("20", "Nothing", "NOPE")], [cg("bitcoin", "btc", "Bitcoin")])["20"]
    assert (r.status, r.cg_id, r.suggested_cg_id, r.candidates) == (
        Status.UNMATCHED,
        None,
        None,
        [],
    )


# ------------------------------------------------------------------ many-to-one, overrides


def test_many_to_one_contract_matches_stay_accepted_and_flagged() -> None:
    addr = "0x" + "f" * 40
    rows = run(
        [
            pc("21", "Dup", "DUP", contracts=[("1", addr)]),
            pc("22", "Dup v2", "DUP", contracts=[("1", addr.upper().replace("0X", "0x"))]),
        ],
        [cg("dup", "dup", "Dup", ethereum=addr)],
    )
    for r in rows.values():
        assert r.status is Status.ACCEPTED and Flag.MANY_TO_ONE in r.flags


def test_many_to_one_demotes_name_based_rows() -> None:
    addr = "0x" + "1" * 40
    rows = run(
        [pc("23", "Zeta", "ZET", contracts=[("1", addr)]), pc("24", "Zeta", "ZET")],
        [cg("zeta", "zet", "Zeta", ethereum=addr)],
    )
    assert rows["23"].status is Status.ACCEPTED and Flag.MANY_TO_ONE in rows["23"].flags
    assert (rows["24"].status, rows["24"].cg_id) == (Status.FLAGGED, None)
    assert Flag.MANY_TO_ONE in rows["24"].flags


def test_override_beats_contract_and_null_override_excludes() -> None:
    overrides = {
        "825": CoinOverride(id="825", cg_id="tether-pinned", reason="pinned"),
        "26": CoinOverride(id="26", cg_id=None, reason="no CG listing"),
    }
    rows = run(
        [pc("825", "Tether USDt", "USDT", contracts=[("1", USDT_ETH)]), pc("26", "Bitcoin", "BTC")],
        [
            cg("tether", "usdt", "Tether", ethereum=USDT_ETH),
            cg("tether-pinned", "usdt", "Tether"),
            cg("bitcoin", "btc", "Bitcoin"),
        ],
        overrides=overrides,
    )
    assert (rows["825"].cg_id, rows["825"].method, rows["825"].note) == (
        "tether-pinned",
        Method.OVERRIDE,
        "pinned",
    )
    assert (rows["26"].status, rows["26"].method, rows["26"].cg_id) == (
        Status.EXCLUDED,
        Method.OVERRIDE,
        None,
    )


def test_market_ids_cover_candidates_and_overrides() -> None:
    m = Matcher(
        [cg("bitcoin", "btc", "Bitcoin"), cg("x", "x", "X")],
        CGAddressIndex([], CG_PLATFORMS),
        NETWORKS,
        {"2": CoinOverride(id="2", cg_id="x", reason="r")},
        Thresholds(),
    )
    prov, cgids = Matcher.market_ids([m.plan(pc("1", "Bitcoin", "BTC")), m.plan(pc("2", "Y", "Y"))])
    assert prov == {"1", "2"} and cgids == {"bitcoin", "x"}
