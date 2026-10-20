import pytest

from cg_id_map.core.normalize import (
    ChainFamily,
    chain_family,
    name_key,
    normalize_address,
    symbol_key,
)
from cg_id_map.models import MarketData

E, M, H, X = ChainFamily.EVM, ChainFamily.MOVE, ChainFamily.HEDERA, ChainFamily.OTHER


@pytest.mark.parametrize(
    ("platform", "chain_id", "family"),
    [
        ("ethereum", 1, E),
        ("base", 8453, E),
        ("sui", None, M),
        ("aptos", None, M),
        ("hedera-hashgraph", 295, H),
        ("solana", None, X),
        ("tron", None, X),
    ],
)
def test_chain_family(platform: str, chain_id: int | None, family: ChainFamily) -> None:
    assert chain_family(platform, chain_id) is family


@pytest.mark.parametrize(
    ("raw", "family", "expected"),
    [
        # EVM: lowercase hex, trim
        (
            "0x7046933234A82AF77F14625e8d0fA9Bcc5044a7E",
            E,
            "0x7046933234a82af77f14625e8d0fa9bcc5044a7e",
        ),
        (
            "  0xdAC17F958D2ee523a2206206994597C13D831ec7 \n",
            E,
            "0xdac17f958d2ee523a2206206994597c13d831ec7",
        ),
        # EVM platform but non-hex value is left alone
        ("native", E, "native"),
        # Non-EVM: case preserved, whitespace trimmed
        (
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            X,
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        ),
        (" TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t ", X, "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
        (
            "EQC7rnHHtMVBKyhiGnAbtYIlzGxS0dfi3ZbHExFX0LYi9cAH",
            X,
            "EQC7rnHHtMVBKyhiGnAbtYIlzGxS0dfi3ZbHExFX0LYi9cAH",
        ),
        ("abr.a11bd.near", X, "abr.a11bd.near"),
        ("388592191", X, "388592191"),
        # Move: address part lowercased + zero-padded, module/type case kept
        (
            "0x2::sui::SUI",
            M,
            "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI",
        ),
        (
            "0xF325CE1300E8DAC124071D3152C5C5EE6174914F8BC2161E88329CF579246EFC::afsui::AFSUI",
            M,
            "0xf325ce1300e8dac124071d3152c5c5ee6174914f8bc2161e88329cf579246efc::afsui::AFSUI",
        ),
        (
            "0xb36527754eb54d7ff55daf13bcb54b42b88ec484bd6f0e3b2e0d1db169de6451",
            M,
            "0xb36527754eb54d7ff55daf13bcb54b42b88ec484bd6f0e3b2e0d1db169de6451",
        ),
        # Hedera: long-zero 0x form and 0.0.N form compare equal
        ("0x00000000000000000000000000000000007872cb", H, "0.0.7893707"),
        ("0.0.7893707", H, "0.0.7893707"),
        (
            "0xAbCdEf0000000000000000000000000000000001",
            H,
            "0xabcdef0000000000000000000000000000000001",
        ),
        # Cosmos IBC denoms: hash uppercased on any family
        (
            "ibc/0cd3a0285e1341859b5e86b6ab7682f023d03e97607ccc1dc95706411d866df7",
            X,
            "ibc/0CD3A0285E1341859B5E86B6AB7682F023D03E97607CCC1DC95706411D866DF7",
        ),
        # Empty
        ("", E, ""),
        ("   ", X, ""),
    ],
)
def test_normalize_address(raw: str, family: ChainFamily, expected: str) -> None:
    assert normalize_address(raw, family) == expected


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Bitcoin", "bitcoin"),
        ("USD Coin", "usd"),
        ("Shiba Inu", "ShibaInu"),
        ("Matic Token (old)", "Matic"),
        ("Polygon [OLD]", "polygon"),
        ("Wrapped  Bitcoin", "wrapped-bitcoin"),
    ],
)
def test_name_key_equal(a: str, b: str) -> None:
    assert name_key(a) == name_key(b)


def test_name_key_keeps_lone_noise_word_and_substrings() -> None:
    assert name_key("Coin") == "coin"
    assert name_key("Bitcoin") == "bitcoin"  # "coin" inside a word is not stripped
    assert name_key("Token Coin") == "token"


def test_name_key_distinguishes_different_names() -> None:
    assert name_key("Ethereum") != name_key("Ethereum Classic")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("BTC", "btc"), (" eth ", "eth"), ("MATIC(old)", "matic"), ("ＵＳＤＴ", "usdt")],
)
def test_symbol_key(raw: str, expected: str) -> None:
    assert symbol_key(raw) == expected


def test_market_data_zero_means_missing() -> None:
    md = MarketData(price_usd=0.0, mcap_usd=0)
    assert md.price_usd is None and md.mcap_usd is None
    assert MarketData(price_usd=1.5, mcap_usd=None).price_usd == 1.5
