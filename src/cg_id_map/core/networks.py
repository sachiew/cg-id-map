"""Step 1: map each provider platform to a CoinGecko asset_platform.

Evidence per (provider platform, CG platform) pair:
  - chain ID equality (EVM only),
  - contract overlap: provider token addresses that CG also lists on that platform,
  - name similarity.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel
from rapidfuzz import fuzz, utils

from cg_id_map.config import Thresholds
from cg_id_map.core.normalize import ChainFamily, chain_family, normalize_address
from cg_id_map.core.overrides import NetworkOverride
from cg_id_map.models import CGCoin, CGPlatform, ProviderCoin, ProviderPlatform


class NetworkMethod(StrEnum):
    OVERRIDE = "override"
    CHAIN_ID_OVERLAP = "chain_id+overlap"
    CHAIN_ID = "chain_id"
    NAME_OVERLAP = "name+overlap"
    OVERLAP_ONLY = "overlap_only"
    NONE = ""


class NetworkStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    UNMAPPED = "unmapped"


class NetworkMapping(BaseModel):
    key: str
    name: str
    slug: str | None
    chain_id: int | None
    token_count: int
    cg_platform_id: str | None  # accepted target (None unless status == accepted)
    suggested_cg_platform_id: str | None  # best candidate, also set for needs_review
    chain_identifier: int | None
    method: NetworkMethod
    status: NetworkStatus
    confidence: str  # high | medium | low | ""
    overlap_count: int
    overlap_share: float
    runner_up: str | None
    runner_up_count: int
    name_score: float
    note: str = ""


class CGAddressIndex:
    """(cg_platform_id, normalized address) -> [cg coin ids], plus a reverse lookup by address."""

    def __init__(self, coins: Iterable[CGCoin], platforms: Iterable[CGPlatform]) -> None:
        self.family = {p.id: chain_family(p.id, p.chain_identifier) for p in platforms}
        self.by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.platforms_by_addr: dict[str, set[str]] = defaultdict(set)
        for c in coins:
            for pid, addr in c.platforms.items():
                norm = normalize_address(addr, self.family_of(pid))
                if norm:
                    self.by_key[(pid, norm)].append(c.id)
                    self.platforms_by_addr[norm].add(pid)

    def family_of(self, cg_platform_id: str) -> ChainFamily:
        return self.family.get(cg_platform_id, ChainFamily.OTHER)

    def lookup(self, cg_platform_id: str, raw_address: str) -> list[str]:
        norm = normalize_address(raw_address, self.family_of(cg_platform_id))
        return self.by_key.get((cg_platform_id, norm), []) if norm else []

    def platforms_for(self, raw_address: str) -> set[str]:
        """Every CG platform listing this address, under each platform's own normalization."""
        found: set[str] = set()
        for fam in ChainFamily:
            norm = normalize_address(raw_address, fam)
            for pid in self.platforms_by_addr.get(norm, ()):
                if self.family_of(pid) is fam:
                    found.add(pid)
        return found


def _names(p: ProviderPlatform) -> list[str]:
    return [n for n in [p.name, *p.aliases] if n]


def _cg_names(p: CGPlatform) -> list[str]:
    return [n for n in (p.name, p.shortname, p.id.replace("-", " ")) if n]


def name_score(p: ProviderPlatform, cp: CGPlatform) -> float:
    return max(
        (
            fuzz.token_set_ratio(a, b, processor=utils.default_process)
            for a in _names(p)
            for b in _cg_names(cp)
        ),
        default=0.0,
    )


@dataclass
class _Evidence:
    platform: ProviderPlatform
    total: int
    votes: Counter[str]

    @property
    def ranked(self) -> list[tuple[str, int]]:
        return self.votes.most_common(2)


def _row(
    ev: _Evidence,
    cg_by_id: dict[str, CGPlatform],
    target: str | None,
    method: NetworkMethod,
    status: NetworkStatus,
    confidence: str,
    note: str = "",
    suggested: str | None = None,
) -> NetworkMapping:
    shown = target or suggested
    cp = cg_by_id.get(shown) if shown else None
    count = ev.votes.get(shown, 0) if shown else 0
    others = [(pid, n) for pid, n in ev.votes.most_common() if pid != shown]
    runner, runner_n = others[0] if others else (None, 0)
    return NetworkMapping(
        key=ev.platform.key,
        name=ev.platform.name,
        slug=ev.platform.slug,
        chain_id=ev.platform.chain_id,
        token_count=ev.total,
        cg_platform_id=target,
        suggested_cg_platform_id=shown,
        chain_identifier=cp.chain_identifier if cp else None,
        method=method,
        status=status,
        confidence=confidence,
        overlap_count=count,
        overlap_share=round(count / ev.total, 4) if ev.total else 0.0,
        runner_up=runner,
        runner_up_count=runner_n,
        name_score=round(name_score(ev.platform, cp), 1) if cp else 0.0,
        note=note,
    )


def build_network_map(
    platforms: list[ProviderPlatform],
    coins: list[ProviderCoin],
    cg_platforms: list[CGPlatform],
    index: CGAddressIndex,
    overrides: dict[str, NetworkOverride],
    t: Thresholds,
) -> list[NetworkMapping]:
    cg_by_id = {p.id: p for p in cg_platforms}
    cg_by_chain = {p.chain_identifier: p for p in cg_platforms if p.chain_identifier is not None}
    addrs: dict[str, list[str]] = defaultdict(list)
    for c in coins:
        for key, addr in c.contracts:
            addrs[key].append(addr)

    A, R, U = NetworkStatus.ACCEPTED, NetworkStatus.NEEDS_REVIEW, NetworkStatus.UNMAPPED
    out = []
    for p in sorted(platforms, key=lambda x: (-len(addrs[x.key]), x.key)):
        votes: Counter[str] = Counter()
        for a in addrs[p.key]:
            votes.update(index.platforms_for(a))
        ev = _Evidence(p, len(addrs[p.key]), votes)
        ranked = ev.ranked
        top, n1 = ranked[0] if ranked else (None, 0)
        n2 = ranked[1][1] if len(ranked) > 1 else 0
        lead_ok = n1 >= t.network_lead_ratio * n2
        strong_overlap = n1 >= t.network_min_overlap and lead_ok
        chain_match = cg_by_chain.get(p.chain_id) if p.chain_id else None

        def emit(
            target: str | None,
            method: NetworkMethod,
            status: NetworkStatus,
            confidence: str,
            note: str = "",
            suggested: str | None = None,
            ev: _Evidence = ev,
        ) -> None:
            out.append(_row(ev, cg_by_id, target, method, status, confidence, note, suggested))

        o = overrides.get(p.key)
        if o is not None:
            if o.cg_platform_id is None:
                emit(None, NetworkMethod.OVERRIDE, U, "high", o.reason)
            else:
                emit(o.cg_platform_id, NetworkMethod.OVERRIDE, A, "high", o.reason)
        elif chain_match is not None:
            if top is None or top == chain_match.id:
                if n1 > 0:
                    emit(chain_match.id, NetworkMethod.CHAIN_ID_OVERLAP, A, "high")
                else:
                    emit(chain_match.id, NetworkMethod.CHAIN_ID, A, "medium")
            elif not strong_overlap:
                note = f"overlap favours {top} ({n1}) but too weakly to override the chain ID"
                emit(chain_match.id, NetworkMethod.CHAIN_ID, A, "medium", note)
            else:
                note = f"chain ID says {chain_match.id}, contract overlap says {top}"
                emit(None, NetworkMethod.NONE, R, "low", note, suggested=top)
        elif top is not None and strong_overlap:
            if name_score(p, cg_by_id[top]) >= t.network_min_name_score:
                emit(top, NetworkMethod.NAME_OVERLAP, A, "high")
            else:
                emit(top, NetworkMethod.OVERLAP_ONLY, A, "medium")
        elif (
            top is not None
            and lead_ok
            and n1 >= t.network_small_min_overlap
            and n1 / ev.total >= t.network_small_min_share
            and name_score(p, cg_by_id[top]) >= t.network_small_min_name_score
        ):
            note = f"small network: {n1}/{ev.total} addresses shared"
            emit(top, NetworkMethod.NAME_OVERLAP, A, "medium", note)
        elif top is not None:
            note = (
                f"only {n1} shared addresses (< {t.network_min_overlap})"
                if lead_ok
                else f"overlap contested: {top} {n1} vs runner-up {n2}"
            )
            emit(None, NetworkMethod.NONE, R, "low", note, suggested=top)
        else:
            named = max(cg_platforms, key=lambda cp: name_score(p, cp), default=None)
            if named is not None and name_score(p, named) >= t.network_min_name_score:
                emit(None, NetworkMethod.NONE, R, "low", "name similarity only", suggested=named.id)
            else:
                emit(None, NetworkMethod.NONE, U, "")
    return out
