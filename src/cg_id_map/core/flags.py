"""Status, method, confidence and flag vocabularies used in every output."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    ACCEPTED = "accepted"  # cg_id is set and published
    FLAGGED = "flagged"  # a suggestion exists but a guardrail failed; needs review
    AMBIGUOUS = "ambiguous"  # several plausible CG coins; needs review
    UNMATCHED = "unmatched"  # no candidate at all
    EXCLUDED = "excluded"  # an override says this coin has no CG equivalent


class Method(StrEnum):
    OVERRIDE = "override"
    CONTRACT = "matched_contract"
    CONTRACT_OTHER_NETWORK = "matched_contract_other_network"
    NAME_SYMBOL = "matched_name_symbol"
    NAME_PRICE = "matched_name_price"
    NONE = ""


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = ""


class Flag(StrEnum):
    AMBIGUOUS_CONTRACT_MULTIPLE_CG = "ambiguous_contract_multiple_cg"
    MANY_TO_ONE = "many_to_one"
    NETWORK_UNMAPPED = "network_unmapped"
    CONTRACT_OTHER_NETWORK = "matched_contract_other_network"
    PRICE_DISCREPANCY = "price_discrepancy"
    MCAP_DISCREPANCY = "mcap_discrepancy"
    NO_MARKET_DATA = "no_market_data"
    AMBIGUOUS_MULTIPLE_CANDIDATES = "ambiguous_multiple_candidates"
    NAME_MISMATCH = "name_mismatch"
    SYMBOL_MISMATCH = "symbol_mismatch"
