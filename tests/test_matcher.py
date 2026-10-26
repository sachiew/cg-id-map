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
    assert (rows["24"].status, rows["24"].cg_id) == (Status.UNMATCHED, None)
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


def test_many_to_one_copycat_resolved_by_price() -> None:
    # CMC lists a second "Dogecoin"/DOGE; only the one whose price agrees keeps the mapping.
    rows = run(
        [pc("74", "Dogecoin", "DOGE"), pc("31093", "Dogecoin", "DOGE")],
        [cg("dogecoin", "doge", "Dogecoin")],
        prov_md={"74": md(0.20), "31093": md(0.0001)},
        cg_md={"dogecoin": md(0.2001)},
    )
    assert (rows["74"].status, rows["74"].cg_id) == (Status.ACCEPTED, "dogecoin")
    # The copycat loses the claim; with no other candidate left it is unmatched (no CG equivalent).
    assert (rows["31093"].status, rows["31093"].cg_id) == (Status.UNMATCHED, None)
    assert Flag.MANY_TO_ONE in rows["74"].flags and Flag.MANY_TO_ONE in rows["31093"].flags


def test_many_to_one_without_a_price_winner_demotes_all() -> None:
    rows = run(
        [pc("1", "Dogecoin", "DOGE"), pc("2", "Dogecoin", "DOGE")],
        [cg("dogecoin", "doge", "Dogecoin")],
        prov_md={"1": md(0.20), "2": md(0.20)},
        cg_md={"dogecoin": md(0.20)},
    )
    assert all(r.status is Status.FLAGGED for r in rows.values())


def test_many_to_one_prefers_exact_name_over_price_match() -> None:
    rows = run(
        [pc("30168", "Xertra", "STRAX"), pc("1343", "Stratis [Old]", "STRAX", slug="stratis")],
        [cg("stratis", "strax", "Xertra")],
        prov_md={"30168": md(0.05), "1343": md(0.05)},
        cg_md={"stratis": md(0.05)},
    )
    assert rows["30168"].cg_id == "stratis" and rows["1343"].status is Status.UNMATCHED


def run_prev(
    coins: list[ProviderCoin],
    cg_coins: list[CGCoin],
    prov_md: dict[str, MarketData],
    cg_md: dict[str, MarketData],
    previous: dict[str, str],
) -> dict[str, MatchRow]:
    m = Matcher(
        cg_coins, CGAddressIndex(cg_coins, CG_PLATFORMS), NETWORKS, {}, Thresholds(), previous
    )
    return {r.provider_id: r for r in match_all(m, [m.plan(c) for c in coins], prov_md, cg_md)}


def test_buffer_zone_keeps_a_published_price_match() -> None:
    # "Regen Network" vs "Regen": accepted only on price. 7% apart: too far for a new match,
    # inside the 10% keep threshold for one that is already published.
    coins, cgs = [pc("11646", "Regen Network", "REGEN")], [cg("regen", "regen", "Regen")]
    prov, cgm = {"11646": md(1.07)}, {"regen": md(1.00)}
    assert run_prev(coins, cgs, prov, cgm, {})["11646"].status is Status.FLAGGED
    kept = run_prev(coins, cgs, prov, cgm, {"11646": "regen"})["11646"]
    assert (kept.status, kept.cg_id, kept.method) == (Status.ACCEPTED, "regen", Method.NAME_PRICE)
    # Past the keep threshold it drops out.
    gone = run_prev(coins, cgs, {"11646": md(1.15)}, cgm, {"11646": "regen"})["11646"]
    assert gone.status is Status.FLAGGED


def test_buffer_zone_only_applies_to_the_previously_published_cg_id() -> None:
    coins, cgs = [pc("11646", "Regen Network", "REGEN")], [cg("regen", "regen", "Regen")]
    r = run_prev(coins, cgs, {"11646": md(1.07)}, {"regen": md(1.00)}, {"11646": "other-coin"})
    assert r["11646"].status is Status.FLAGGED


def test_published_match_stays_when_two_candidates_price_alike() -> None:
    # CMC "XBIT"/XBT vs CG "xbt" and "xbt-2", both within 1% on 2026-10-24: kept on "xbt".
    coins = [pc("4813", "XBIT", "XBT")]
    cgs = [cg("xbt", "xbt", "XBT"), cg("xbt-2", "xbt", "XBT")]
    prov, cgm = {"4813": md(9.58e-05)}, {"xbt": md(9.68e-05), "xbt-2": md(9.52e-05)}
    assert run_prev(coins, cgs, prov, cgm, {})["4813"].status is Status.AMBIGUOUS
    kept = run_prev(coins, cgs, prov, cgm, {"4813": "xbt"})["4813"]
    assert (kept.status, kept.cg_id) == (Status.ACCEPTED, "xbt")


MAGA = [
    pc("27872", "MAGA (magamemecoin.com)", "TRUMP"),
    pc("31692", "MAGA", "TRUMP", slug="magatrumponbase"),
]


def test_many_to_one_keeps_the_published_holder_over_an_exact_name_match() -> None:
    rows = run_prev(
        MAGA,
        [cg("maga", "trump", "MAGA")],
        {"27872": md(0.0225), "31692": md(0.0224)},
        {"maga": md(0.0226)},
        {"27872": "maga"},
    )
    assert rows["27872"].cg_id == "maga" and rows["31692"].cg_id is None


def test_copycat_cannot_take_over_a_published_coin_on_name_alone() -> None:
    # 2026-10-24: the real MAGA's CG price jumped 14% so it dropped out, and the Base copycat
    # (exact name+ticker, price 20x off) took "maga". It now needs a matching price to do that.
    rows = run_prev(
        MAGA,
        [cg("maga", "trump", "MAGA")],
        {"27872": md(0.0225), "31692": md(0.00125)},
        {"maga": md(0.0258)},
        {"27872": "maga"},
    )
    assert rows["31692"].status is Status.FLAGGED and rows["31692"].cg_id is None
    assert rows["31692"].suggested_cg_id == "maga" and Flag.MANY_TO_ONE in rows["31692"].flags
    # Without a published holder, the exact name+ticker match is still accepted outright.
    fresh = run_prev(MAGA[1:], [cg("maga", "trump", "MAGA")], {"31692": md(0.00125)},
                     {"maga": md(0.0258)}, {"27872": "maga"})  # fmt: skip
    assert fresh["31692"].cg_id == "maga"


# ------------------------------------------------------------------ second pass: claimed candidates

DRAGON_ADDR = "0x" + "d0" * 20
DRAGON_CG = [
    cg("black-dragon", "blackdragon", "Black Dragon", ethereum=DRAGON_ADDR),
    cg("dragon-4", "dragon", "DRAGON"),
    cg("blackdragon-token", "bdt", "BlackDragon"),
]


def test_candidate_held_by_another_coin_is_excluded_and_price_decides() -> None:
    # CMC lists two tokens: "Black Dragon"/BLACKDRAGON (contract match) and "BLACK DRAGON"/DRAGON.
    rows = run(
        [
            pc("29627", "Black Dragon", "BLACKDRAGON", contracts=[("1", DRAGON_ADDR)]),
            pc("29340", "BLACK DRAGON", "DRAGON", slug="black-dragon"),
        ],
        DRAGON_CG,
        # First pass: black-dragon and dragon-4 both pass on price -> ambiguous. Second pass:
        # black-dragon is held by 29627's contract match, leaving dragon-4.
        prov_md={"29627": md(0.05), "29340": md(0.05)},
        cg_md={"black-dragon": md(0.05), "dragon-4": md(0.0505), "blackdragon-token": md(7.0)},
    )
    assert rows["29627"].cg_id == "black-dragon" and rows["29627"].method is Method.CONTRACT
    r = rows["29340"]
    assert (r.status, r.cg_id, r.method, r.confidence) == (
        Status.ACCEPTED,
        "dragon-4",
        Method.NAME_PRICE,
        Confidence.MEDIUM,
    )
    assert Flag.AMBIGUOUS_MULTIPLE_CANDIDATES not in r.flags
    assert "black-dragon (by 29627)" in r.note
    assert {c.cg_id: c.claimed_by for c in r.candidates}["black-dragon"] == "29627"


def test_claimed_candidates_move_the_suggestion_when_still_unresolved() -> None:
    rows = run(
        [
            pc("29627", "Black Dragon", "BLACKDRAGON", contracts=[("1", DRAGON_ADDR)]),
            pc("29340", "BLACK DRAGON", "DRAGON", slug="black-dragon"),
        ],
        DRAGON_CG,
        prov_md={"29627": md(1.0), "29340": md(0.05)},
        cg_md={"black-dragon": md(1.0), "dragon-4": md(0.0505), "blackdragon-token": md(0.0501)},
    )
    r = rows["29340"]
    assert r.status is Status.AMBIGUOUS and r.cg_id is None
    assert r.suggested_cg_id in {"dragon-4", "blackdragon-token"}  # never the claimed coin


def test_pi_resolves_once_the_iou_listing_is_claimed() -> None:
    rows = run(
        [pc("16193", "Pi Network IOU", "PI"), pc("35697", "Pi", "PI", slug="pi")],
        [cg("pi-network-iou", "pi", "Pi Network IOU"), cg("pi-network", "pi", "Pi Network")],
        prov_md={"16193": md(0.30), "35697": md(0.30)},
        cg_md={"pi-network-iou": md(0.301), "pi-network": md(0.302)},
    )
    assert rows["16193"].cg_id == "pi-network-iou"
    assert (rows["35697"].cg_id, rows["35697"].method) == ("pi-network", Method.NAME_PRICE)


def test_two_rows_resolving_to_the_same_free_coin_stay_in_review() -> None:
    addr = "0x" + "e1" * 20
    rows = run(
        [
            pc("1", "Zed", "ZED", contracts=[("1", addr)]),
            pc("2", "Zed", "ZED", slug="zed-two"),
            pc("3", "Zed", "ZED", slug="zed-three"),
        ],
        [cg("zed", "zed", "Zed", ethereum=addr), cg("zed-free", "zed", "Zed Coin")],
        prov_md={"1": md(1.0), "2": md(2.0), "3": md(2.0)},
        cg_md={"zed": md(1.0), "zed-free": md(2.0)},
    )
    assert rows["2"].status is not Status.ACCEPTED and rows["3"].status is not Status.ACCEPTED
    assert rows["2"].suggested_cg_id == rows["3"].suggested_cg_id == "zed-free"


def test_real_black_dragon_case_no_longer_suggests_the_claimed_coin() -> None:
    # Live data 2026-10-20: CMC 29340 priced 2e-14, nothing on CG is close -> stays in review,
    # but the suggestion must not be black-dragon (held by 29627).
    rows = run(
        [
            pc("29627", "Black Dragon", "BLACKDRAGON", contracts=[("1", DRAGON_ADDR)]),
            pc("29340", "BLACK DRAGON", "DRAGON", slug="black-dragon"),
        ],
        DRAGON_CG,
        prov_md={"29627": md(1.0972e-08), "29340": md(2.0154e-14)},
        cg_md={
            "black-dragon": md(1.0925e-08),
            "dragon-4": md(0.000483),
            "blackdragon-token": md(0.165757),
        },
    )
    r = rows["29340"]
    assert r.status is not Status.ACCEPTED and r.suggested_cg_id == "dragon-4"
    assert {c.cg_id: c.claimed_by for c in r.candidates}["black-dragon"] == "29627"


def test_row_whose_candidates_are_all_taken_becomes_unmatched() -> None:
    rows = run(
        [pc("74", "Dogecoin", "DOGE"), pc("31093", "Dogecoin", "DOGE")],
        [cg("dogecoin", "doge", "Dogecoin")],
        prov_md={"74": md(0.20), "31093": md(0.0001)},
        cg_md={"dogecoin": md(0.2001)},
    )
    r = rows["31093"]
    assert (r.status, r.suggested_cg_id, r.cg_id) == (Status.UNMATCHED, None, None)
    assert r.candidates[0].claimed_by == "74" and "copycat" in r.note
