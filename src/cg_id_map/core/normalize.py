"""Address, name and symbol normalization.

Normalized values are comparison keys only; outputs always keep the provider's original strings.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum


class ChainFamily(StrEnum):
    EVM = "evm"
    MOVE = "move"  # Sui, Aptos: 0x<addr>::module::Type
    HEDERA = "hedera"  # 0.0.N entity IDs, also exposed as "long-zero" 0x addresses
    OTHER = "other"  # Solana, Tron, TON, NEAR, Stellar, Cardano, Algorand, ...: case-sensitive


# CG platform IDs whose address rules differ from what chain_identifier alone implies.
MOVE_PLATFORMS = frozenset({"sui", "aptos"})
HEDERA_PLATFORMS = frozenset({"hedera-hashgraph"})

_HEX40 = re.compile(r"0x[0-9a-fA-F]{40}")
_HEX_ANY = re.compile(r"0x[0-9a-fA-F]{1,64}")
_HEDERA_ENTITY = re.compile(r"\d+\.\d+\.\d+")


def chain_family(cg_platform_id: str, chain_identifier: int | None) -> ChainFamily:
    """Pick the address rules for a CG platform."""
    if cg_platform_id in MOVE_PLATFORMS:
        return ChainFamily.MOVE
    if cg_platform_id in HEDERA_PLATFORMS:
        return ChainFamily.HEDERA
    if chain_identifier is not None:
        return ChainFamily.EVM
    return ChainFamily.OTHER


def normalize_address(address: str, family: ChainFamily) -> str:
    """Return a comparison key for a contract address. Empty input gives ""."""
    a = address.strip()
    if not a:
        return ""
    # Cosmos IBC denoms appear on several cosmos-family platforms; the hash is case-insensitive.
    if a[:4].lower() == "ibc/":
        return "ibc/" + a[4:].upper()
    if family is ChainFamily.EVM:
        return a.lower() if _HEX40.fullmatch(a) else a
    if family is ChainFamily.MOVE:
        return _normalize_move(a)
    if family is ChainFamily.HEDERA:
        return _normalize_hedera(a)
    return a


def _normalize_move(a: str) -> str:
    # Only the address part is case-insensitive; module and type names keep their case.
    addr, sep, rest = a.partition("::")
    if _HEX_ANY.fullmatch(addr):
        addr = "0x" + addr[2:].lower().rjust(64, "0")
    return addr + sep + rest


def _normalize_hedera(a: str) -> str:
    if _HEDERA_ENTITY.fullmatch(a):
        return a
    if _HEX40.fullmatch(a):
        value = int(a[2:], 16)
        # Long-zero address: shard (4 bytes) and realm (8 bytes) are zero, low 8 bytes = entity num.
        if value < 2**64:
            return f"0.0.{value}"
        return a.lower()
    return a


# ---------------------------------------------------------------- names and symbols

_OLD_MARKER = re.compile(r"[\(\[]\s*old\s*[\)\]]", re.IGNORECASE)
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_NOISE_WORDS = ("token", "coin")


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def name_key(name: str) -> str:
    """Casefold, drop "(old)"/"[old]", punctuation and trailing "token"/"coin" words.

    Words are joined without spaces so "Shiba Inu" and "ShibaInu" compare equal.
    """
    s = _OLD_MARKER.sub(" ", _fold(name))
    words = [w for w in _NON_WORD.split(s) if w]
    while len(words) > 1 and words[-1] in _NOISE_WORDS:
        words.pop()
    return "".join(words)


def symbol_key(symbol: str) -> str:
    """Casefold and drop whitespace and "(old)"/"[old]" markers."""
    s = _OLD_MARKER.sub("", _fold(symbol))
    return "".join(s.split())
