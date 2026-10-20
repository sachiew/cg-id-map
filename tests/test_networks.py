from __future__ import annotations

from cg_id_map.config import Thresholds
from cg_id_map.core.networks import (
    CGAddressIndex,
    NetworkMapping,
    NetworkMethod,
    NetworkStatus,
    build_network_map,
)
from cg_id_map.core.overrides import NetworkOverride
from cg_id_map.models import CGCoin, CGPlatform, ProviderCoin, ProviderPlatform

CG_PLATFORMS = [
    CGPlatform(id="ethereum", name="Ethereum", shortname="Ethereum", chain_identifier=1),
    CGPlatform(
        id="binance-smart-chain", name="BNB Smart Chain", shortname="BSC", chain_identifier=56
    ),
    CGPlatform(id="solana", name="Solana", shortname="Solana"),
    CGPlatform(id="tron", name="TRON"),
    CGPlatform(id="hedera-hashgraph", name="Hedera Hashgraph", chain_identifier=295),
    CGPlatform(id="sui", name="Sui"),
    CGPlatform(id="osmosis", name="Osmosis"),
]


def evm(i: int) -> str:
    return f"0x{i:040x}"


def cg_coins(platform: str, addrs: list[str], prefix: str = "cg") -> list[CGCoin]:
    return [
        CGCoin(id=f"{prefix}-{platform}-{i}", symbol="x", name="x", platforms={platform: a})
        for i, a in enumerate(addrs)
    ]


def provider_coins(key: str, addrs: list[str]) -> list[ProviderCoin]:
    return [
        ProviderCoin(id=f"{key}-{i}", name="x", symbol="x", contracts=[(key, a)])
        for i, a in enumerate(addrs)
    ]


def run(
    platforms: list[ProviderPlatform],
    pcoins: list[ProviderCoin],
    cgcoins: list[CGCoin],
    overrides: dict[str, NetworkOverride] | None = None,
    t: Thresholds | None = None,
) -> dict[str, NetworkMapping]:
    index = CGAddressIndex(cgcoins, CG_PLATFORMS)
    rows = build_network_map(
        platforms, pcoins, CG_PLATFORMS, index, overrides or {}, t or Thresholds()
    )
    return {r.key: r for r in rows}


def test_index_normalizes_per_family() -> None:
    coins = [
        CGCoin(
            id="hbar-tok",
            symbol="t",
            name="t",
            platforms={"hedera-hashgraph": "0x00000000000000000000000000000000007872cb"},
        ),
        CGCoin(id="sui-tok", symbol="t", name="t", platforms={"sui": "0x2::sui::SUI"}),
        CGCoin(
            id="usdt",
            symbol="usdt",
            name="Tether",
            platforms={"ethereum": "0xdAC17F958D2ee523a2206206994597C13D831ec7"},
        ),
    ]
    idx = CGAddressIndex(coins, CG_PLATFORMS)
    assert idx.lookup("hedera-hashgraph", "0.0.7893707") == ["hbar-tok"]
    assert idx.lookup(
        "sui", "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI"
    ) == ["sui-tok"]
    assert idx.lookup("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7") == ["usdt"]
    assert idx.platforms_for("0xDAC17F958D2EE523A2206206994597C13D831EC7") == {"ethereum"}


def test_chain_id_plus_overlap_is_high() -> None:
    addrs = [evm(i) for i in range(5)]
    m = run(
        [ProviderPlatform(key="1", name="Ethereum", chain_id=1)],
        provider_coins("1", addrs),
        cg_coins("ethereum", addrs),
    )["1"]
    assert (m.cg_platform_id, m.method, m.status, m.confidence) == (
        "ethereum",
        NetworkMethod.CHAIN_ID_OVERLAP,
        NetworkStatus.ACCEPTED,
        "high",
    )
    assert m.overlap_count == 5 and m.overlap_share == 1.0 and m.chain_identifier == 1


def test_chain_id_alone_is_accepted_medium() -> None:
    m = run(
        [ProviderPlatform(key="14", name="BNB Smart Chain (BEP20)", chain_id=56)],
        provider_coins("14", [evm(1)]),
        [],
    )["14"]
    assert (m.cg_platform_id, m.method, m.confidence) == (
        "binance-smart-chain",
        NetworkMethod.CHAIN_ID,
        "medium",
    )


def test_weak_overlap_cannot_override_chain_id() -> None:
    # One bridged token also on ethereum must not move a BSC platform.
    m = run(
        [ProviderPlatform(key="14", name="BSC", chain_id=56)],
        provider_coins("14", [evm(1)]),
        cg_coins("ethereum", [evm(1)]),
    )["14"]
    assert m.cg_platform_id == "binance-smart-chain" and m.method == NetworkMethod.CHAIN_ID


def test_strong_overlap_conflicting_with_chain_id_needs_review() -> None:
    addrs = [evm(i) for i in range(25)]
    m = run(
        [ProviderPlatform(key="9", name="Mystery", chain_id=56)],
        provider_coins("9", addrs),
        cg_coins("ethereum", addrs),
    )["9"]
    assert m.status == NetworkStatus.NEEDS_REVIEW and m.cg_platform_id is None
    assert m.suggested_cg_platform_id == "ethereum"


def test_name_plus_overlap_without_chain_id() -> None:
    addrs = [f"So1Addr{i}" for i in range(25)]
    noise = cg_coins("tron", addrs[:2], prefix="other")
    m = run(
        [ProviderPlatform(key="16", name="Solana")],
        provider_coins("16", addrs),
        cg_coins("solana", addrs) + noise,
    )["16"]
    assert (m.cg_platform_id, m.method, m.confidence) == (
        "solana",
        NetworkMethod.NAME_OVERLAP,
        "high",
    )
    assert m.runner_up == "tron" and m.runner_up_count == 2


def test_overlap_only_when_names_differ() -> None:
    addrs = [f"T{i}" for i in range(25)]
    m = run(
        [ProviderPlatform(key="47", name="Zzqx20")],
        provider_coins("47", addrs),
        cg_coins("tron", addrs),
    )["47"]
    assert (m.cg_platform_id, m.method, m.confidence) == (
        "tron",
        NetworkMethod.OVERLAP_ONLY,
        "medium",
    )


def test_overlap_without_clear_lead_needs_review() -> None:
    addrs = [f"A{i}" for i in range(30)]
    m = run(
        [ProviderPlatform(key="5", name="Qqq")],
        provider_coins("5", addrs),
        cg_coins("solana", addrs[:22]) + cg_coins("tron", addrs[:20]),
    )["5"]
    assert m.status == NetworkStatus.NEEDS_REVIEW


def test_small_overlap_needs_review_with_suggestion() -> None:
    addrs = [f"T{i}" for i in range(5)]
    m = run(
        [ProviderPlatform(key="47", name="Tron20")],
        provider_coins("47", addrs),
        cg_coins("tron", addrs),
    )["47"]
    assert m.status == NetworkStatus.NEEDS_REVIEW and m.suggested_cg_platform_id == "tron"
    assert m.overlap_count == 5


def test_name_only_needs_review() -> None:
    m = run([ProviderPlatform(key="90", name="Osmosis")], provider_coins("90", ["ibc/abc"]), [])[
        "90"
    ]
    assert m.status == NetworkStatus.NEEDS_REVIEW and m.suggested_cg_platform_id == "osmosis"


def test_nothing_is_unmapped() -> None:
    m = run([ProviderPlatform(key="219", name="Runes")], provider_coins("219", ["840000:3"]), [])[
        "219"
    ]
    assert m.status == NetworkStatus.UNMAPPED and m.suggested_cg_platform_id is None


def test_override_wins_over_evidence() -> None:
    addrs = [evm(i) for i in range(25)]
    overrides = {
        "1": NetworkOverride(key="1", cg_platform_id="binance-smart-chain", reason="test pin"),
        "2": NetworkOverride(key="2", cg_platform_id=None, reason="no CG equivalent"),
    }
    res = run(
        [
            ProviderPlatform(key="1", name="Ethereum", chain_id=1),
            ProviderPlatform(key="2", name="Ethereum", chain_id=1),
        ],
        provider_coins("1", addrs) + provider_coins("2", addrs),
        cg_coins("ethereum", addrs),
        overrides,
    )
    assert (res["1"].cg_platform_id, res["1"].method, res["1"].note) == (
        "binance-smart-chain",
        NetworkMethod.OVERRIDE,
        "test pin",
    )
    assert res["2"].status == NetworkStatus.UNMAPPED and res["2"].method == NetworkMethod.OVERRIDE


def test_threshold_is_configurable() -> None:
    addrs = [f"T{i}" for i in range(5)]
    m = run(
        [ProviderPlatform(key="47", name="Tron20")],
        provider_coins("47", addrs),
        cg_coins("tron", addrs),
        t=Thresholds(network_min_overlap=5),
    )["47"]
    assert m.status == NetworkStatus.ACCEPTED
