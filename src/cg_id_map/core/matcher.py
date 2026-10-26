"""Steps 2-4: match each provider coin to a CoinGecko coin.

Acceptance rules:
  1. Contract address on the mapped network                 -> matched_contract (high)
  2. Exactly one CG coin with equal name key AND symbol key  -> matched_name_symbol (high)
  3. Anything uncertain uses price/mcap as the last guardrail: one candidate within the price
     threshold (and mcap threshold when both sides have mcap)  -> matched_name_price (medium)
  Everything else is flagged / ambiguous / unmatched and never auto-accepted.

Matching is two-phase so market data is fetched only for coins that need it:
`plan()` gathers candidates, then `decide()` runs with the fetched market data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, utils

from cg_id_map.config import Thresholds
from cg_id_map.core.flags import Confidence, Flag, Method, Status
from cg_id_map.core.networks import CGAddressIndex, NetworkMapping, NetworkStatus
from cg_id_map.core.normalize import name_key, symbol_key
from cg_id_map.core.overrides import CoinOverride
from cg_id_map.models import CGCoin, MarketData, ProviderCoin


class Candidate(BaseModel):
    cg_id: str
    name: str
    symbol: str
    via: str  # contract | contract_other_network | name_symbol | symbol | name | slug
    name_score: float
    name_equal: bool
    symbol_equal: bool
    slug_equal: bool
    price_usd: float | None = None
    mcap_usd: float | None = None
    price_diff_pct: float | None = None
    mcap_diff_pct: float | None = None
    # Provider ID of another coin whose accepted mapping already holds this CG coin.
    claimed_by: str | None = None


class MatchRow(BaseModel):
    provider_id: str
    name: str
    symbol: str
    slug: str | None
    rank: int | None
    cg_id: str | None = None
    suggested_cg_id: str | None = None
    status: Status = Status.UNMATCHED
    method: Method = Method.NONE
    confidence: Confidence = Confidence.NONE
    flags: list[Flag] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    price_usd: float | None = None
    mcap_usd: float | None = None
    cg_price_usd: float | None = None
    cg_mcap_usd: float | None = None
    price_diff_pct: float | None = None
    mcap_diff_pct: float | None = None
    note: str = ""

    def flag(self, f: Flag) -> None:
        if f not in self.flags:
            self.flags.append(f)


class CoinPlan(BaseModel):
    """Phase-1 result for one coin: candidates found without market data."""

    coin: ProviderCoin
    contract_ids: list[str] = Field(default_factory=list)
    other_network_ids: list[str] = Field(default_factory=list)
    network_unmapped: bool = False
    candidates: list[Candidate] = Field(default_factory=list)
    override: CoinOverride | None = None


def diff_pct(a: float | None, b: float | None) -> float | None:
    """Relative difference against the smaller value, in percent (conservative)."""
    if a is None or b is None:
        return None
    return round(abs(a - b) / min(a, b) * 100, 2)


class Matcher:
    def __init__(
        self,
        cg_coins: Iterable[CGCoin],
        index: CGAddressIndex,
        networks: Iterable[NetworkMapping],
        overrides: dict[str, CoinOverride],
        t: Thresholds,
        previous: dict[str, str] | None = None,
    ) -> None:
        self.cg = {c.id: c for c in cg_coins}
        self.index = index
        self.networks = {n.key: n for n in networks}
        self.overrides = overrides
        self.t = t
        # Last published {provider id: cg_id}. Price-gated matches already published keep their
        # mapping inside the wider *_keep_* thresholds, so borderline coins don't flip daily.
        self.previous = previous or {}
        self.by_symbol: dict[str, list[str]] = defaultdict(list)
        self.by_name: dict[str, list[str]] = defaultdict(list)
        for c in self.cg.values():
            self.by_symbol[symbol_key(c.symbol)].append(c.id)
            self.by_name[name_key(c.name)].append(c.id)

    # ------------------------------------------------------------------ phase 1

    def plan(self, coin: ProviderCoin) -> CoinPlan:
        p = CoinPlan(coin=coin, override=self.overrides.get(coin.id))
        if p.override is not None:
            return p
        for key, addr in coin.contracts:
            net = self.networks.get(key)
            if net is None or net.status is not NetworkStatus.ACCEPTED or not net.cg_platform_id:
                p.network_unmapped = True
            else:
                p.contract_ids += self.index.lookup(net.cg_platform_id, addr)
            if not p.contract_ids:
                for pid in sorted(self.index.platforms_for(addr)):
                    p.other_network_ids += self.index.lookup(pid, addr)
        p.contract_ids = sorted(set(p.contract_ids))
        p.other_network_ids = sorted(set(p.other_network_ids) - set(p.contract_ids))

        ids: dict[str, str] = {}
        for cid in p.contract_ids:
            ids.setdefault(cid, "contract")
        for cid in p.other_network_ids:
            ids.setdefault(cid, "contract_other_network")
        nk, sk = name_key(coin.name), symbol_key(coin.symbol)
        for cid in self.by_symbol.get(sk, []):
            ids.setdefault(cid, "name_symbol" if name_key(self.cg[cid].name) == nk else "symbol")
        for cid in self.by_name.get(nk, []):
            ids.setdefault(cid, "name")
        if coin.slug and coin.slug in self.cg:
            ids.setdefault(coin.slug, "slug")
        p.candidates = [self._candidate(coin, cid, via) for cid, via in ids.items()]
        return p

    def _candidate(self, coin: ProviderCoin, cg_id: str, via: str) -> Candidate:
        c = self.cg[cg_id]
        return Candidate(
            cg_id=cg_id,
            name=c.name,
            symbol=c.symbol,
            via=via,
            name_score=round(
                fuzz.token_set_ratio(coin.name, c.name, processor=utils.default_process), 1
            ),
            name_equal=name_key(coin.name) == name_key(c.name),
            symbol_equal=symbol_key(coin.symbol) == symbol_key(c.symbol),
            slug_equal=bool(coin.slug) and coin.slug == cg_id,
        )

    @staticmethod
    def market_ids(plans: Iterable[CoinPlan]) -> tuple[set[str], set[str]]:
        """(provider IDs, CG IDs) whose market data phase 2 may use."""
        prov: set[str] = set()
        cg: set[str] = set()
        for p in plans:
            prov.add(p.coin.id)
            cg.update(c.cg_id for c in p.candidates)
            if p.override and p.override.cg_id:
                cg.add(p.override.cg_id)
        return prov, cg

    # ------------------------------------------------------------------ phase 2

    def decide(
        self, p: CoinPlan, prov_md: dict[str, MarketData], cg_md: dict[str, MarketData]
    ) -> MatchRow:
        coin = p.coin
        md = prov_md.get(coin.id, MarketData())
        row = MatchRow(
            provider_id=coin.id,
            name=coin.name,
            symbol=coin.symbol,
            slug=coin.slug,
            rank=coin.rank,
            price_usd=md.price_usd,
            mcap_usd=md.mcap_usd,
        )
        for c in p.candidates:
            cmd = cg_md.get(c.cg_id, MarketData())
            c.price_usd, c.mcap_usd = cmd.price_usd, cmd.mcap_usd
            c.price_diff_pct = diff_pct(md.price_usd, cmd.price_usd)
            c.mcap_diff_pct = diff_pct(md.mcap_usd, cmd.mcap_usd)
        row.candidates = sorted(p.candidates, key=_candidate_order)
        if p.network_unmapped:
            row.flag(Flag.NETWORK_UNMAPPED)

        if p.override is not None:
            if p.override.cg_id is None:
                row.status, row.method, row.note = (
                    Status.EXCLUDED,
                    Method.OVERRIDE,
                    p.override.reason,
                )
            else:
                self._accept(row, p.override.cg_id, Method.OVERRIDE, Confidence.HIGH, cg_md)
                row.note = p.override.reason
            return row

        by_id = {c.cg_id: c for c in row.candidates}

        # Step 2: contract on the mapped network.
        if p.contract_ids:
            if len(p.contract_ids) == 1:
                self._accept(row, p.contract_ids[0], Method.CONTRACT, Confidence.HIGH, cg_md)
                return row
            row.flag(Flag.AMBIGUOUS_CONTRACT_MULTIPLE_CG)
            exact_ids = [i for i in p.contract_ids if by_id[i].name_equal and by_id[i].symbol_equal]
            if len(exact_ids) == 1:
                self._accept(row, exact_ids[0], Method.CONTRACT, Confidence.MEDIUM, cg_md)
                return row
            return self._unresolved(row, [by_id[i] for i in p.contract_ids], Status.AMBIGUOUS)

        # Step 2b: same address on another CG network (bridged token or a wrong network map).
        if p.other_network_ids:
            row.flag(Flag.CONTRACT_OTHER_NETWORK)
            same_sym = [i for i in p.other_network_ids if by_id[i].symbol_equal]
            if len(same_sym) == 1:
                self._accept(
                    row, same_sym[0], Method.CONTRACT_OTHER_NETWORK, Confidence.MEDIUM, cg_md
                )
                return row
            # Different symbol or several hits: fall through to name matching with this context.

        # Step 3: unique exact name + symbol.
        exact = [c for c in row.candidates if c.name_equal and c.symbol_equal]
        if len(exact) == 1:
            self._accept(row, exact[0].cg_id, Method.NAME_SYMBOL, Confidence.HIGH, cg_md)
            return row
        if len(exact) > 1:
            slugged = [c for c in exact if c.slug_equal]
            if len(slugged) == 1:
                self._accept(row, slugged[0].cg_id, Method.NAME_SYMBOL, Confidence.HIGH, cg_md)
                return row

        # Step 3-4: uncertain -> price/mcap guardrail over plausible candidates.
        plausible = exact or [c for c in row.candidates if self._plausible(c)]
        if not plausible:
            if row.candidates:  # symbol-only collisions with unrelated names
                row.flag(Flag.AMBIGUOUS_MULTIPLE_CANDIDATES)
                return self._unresolved(row, row.candidates, Status.AMBIGUOUS)
            return row  # unmatched
        if md.price_usd is None:
            row.flag(Flag.NO_MARKET_DATA)
            return self._unresolved(row, plausible, Status.FLAGGED, Confidence.LOW)
        passing = [c for c in plausible if self._market_ok(c, keep=self._was(coin.id, c.cg_id))]
        if len(passing) > 1:
            # Several candidates price alike: stay on the one already published.
            passing = [c for c in passing if self._was(coin.id, c.cg_id)] or passing
        if len(passing) == 1:
            c = passing[0]
            self._accept(row, c.cg_id, Method.NAME_PRICE, Confidence.MEDIUM, cg_md)
            if not c.name_equal:
                row.flag(Flag.NAME_MISMATCH)
            if not c.symbol_equal:
                row.flag(Flag.SYMBOL_MISMATCH)
            return row
        if len(plausible) > 1 or len(passing) > 1:
            row.flag(Flag.AMBIGUOUS_MULTIPLE_CANDIDATES)
            return self._unresolved(row, plausible, Status.AMBIGUOUS)
        c = plausible[0]
        if c.price_usd is None:
            row.flag(Flag.NO_MARKET_DATA)
            return self._unresolved(row, plausible, Status.FLAGGED, Confidence.LOW)
        self._flag_market(row, c)
        if not c.name_equal:
            row.flag(Flag.NAME_MISMATCH)
        if not c.symbol_equal:
            row.flag(Flag.SYMBOL_MISMATCH)
        return self._unresolved(row, plausible, Status.FLAGGED, Confidence.LOW)

    # ------------------------------------------------------------------ helpers

    def _plausible(self, c: Candidate) -> bool:
        """Worth a price check: same ticker with a close name, same name, or slug == CG id."""
        return (
            (c.symbol_equal and (c.name_score >= self.t.name_fuzzy_min or c.slug_equal))
            or (c.name_equal and not c.symbol_equal)
            or c.slug_equal
            or c.via == "contract_other_network"
        )

    def _was(self, provider_id: str, cg_id: str) -> bool:
        return self.previous.get(provider_id) == cg_id

    def _market_ok(self, c: Candidate, keep: bool = False) -> bool:
        return within(c.price_diff_pct, c.mcap_diff_pct, self.t, keep)

    def _flag_market(self, row: MatchRow, c: Candidate) -> None:
        if c.price_diff_pct is not None and c.price_diff_pct > self.t.price_diff_pct:
            row.flag(Flag.PRICE_DISCREPANCY)
        if c.mcap_diff_pct is not None and c.mcap_diff_pct > self.t.mcap_diff_pct:
            row.flag(Flag.MCAP_DISCREPANCY)

    def _accept(
        self,
        row: MatchRow,
        cg_id: str,
        method: Method,
        confidence: Confidence,
        cg_md: dict[str, MarketData],
    ) -> None:
        cmd = cg_md.get(cg_id, MarketData())
        row.cg_id = row.suggested_cg_id = cg_id
        row.status, row.method, row.confidence = Status.ACCEPTED, method, confidence
        row.cg_price_usd, row.cg_mcap_usd = cmd.price_usd, cmd.mcap_usd
        row.price_diff_pct = diff_pct(row.price_usd, cmd.price_usd)
        row.mcap_diff_pct = diff_pct(row.mcap_usd, cmd.mcap_usd)
        # Informational only: an accepted match stays accepted (D1).
        if row.price_diff_pct is not None and row.price_diff_pct > self.t.price_diff_pct:
            row.flag(Flag.PRICE_DISCREPANCY)
        if row.method is not Method.OVERRIDE and cg_id in self.cg:
            c = self.cg[cg_id]
            if name_key(c.name) != name_key(row.name):
                row.flag(Flag.NAME_MISMATCH)
            if symbol_key(c.symbol) != symbol_key(row.symbol):
                row.flag(Flag.SYMBOL_MISMATCH)

    def _unresolved(
        self,
        row: MatchRow,
        cands: list[Candidate],
        status: Status,
        confidence: Confidence = Confidence.LOW,
    ) -> MatchRow:
        best = sorted(cands, key=_candidate_order)[0]
        row.status, row.confidence, row.suggested_cg_id = status, confidence, best.cg_id
        row.cg_price_usd, row.cg_mcap_usd = best.price_usd, best.mcap_usd
        row.price_diff_pct, row.mcap_diff_pct = best.price_diff_pct, best.mcap_diff_pct
        return row


def _candidate_order(c: Candidate) -> tuple[int, float, float, str]:
    """Best first: contract > exact name+symbol > slug > name score, then closest price."""
    tier = (
        0
        if c.via == "contract"
        else 1
        if c.name_equal and c.symbol_equal
        else 2
        if c.slug_equal
        else 3
    )
    price = c.price_diff_pct if c.price_diff_pct is not None else float("inf")
    return (tier, -c.name_score, price, c.cg_id)


def within(price_diff: float | None, mcap_diff: float | None, t: Thresholds, keep: bool) -> bool:
    """Price (required) and mcap (when known) within the entry or the wider keep thresholds."""
    max_price = t.price_keep_diff_pct if keep else t.price_diff_pct
    max_mcap = t.mcap_keep_diff_pct if keep else t.mcap_diff_pct
    if price_diff is None or price_diff > max_price:
        return False
    return mcap_diff is None or mcap_diff <= max_mcap


def resolve_many_to_one(
    rows: list[MatchRow], t: Thresholds, previous: dict[str, str] | None = None
) -> None:
    """Flag every row sharing an accepted cg_id and keep at most one name-based claimant.

    Providers often list copycats with the same name and ticker (a second "Dogecoin"), so a
    name-based claim survives only if no contract/override row claims the same coin and it is the
    single claimant whose price agrees (the previously published holder preferred, then an exact
    name+symbol match). The rest are demoted. A name-based row also can't take over a CG coin
    published for another, still active, provider coin unless its own price agrees.
    """
    previous = previous or {}
    active = {r.provider_id for r in rows}
    holders: dict[str, str] = {}
    for pid, cg_id in sorted(previous.items()):
        if pid in active:
            holders.setdefault(cg_id, pid)
    for r in rows:
        holder = holders.get(r.cg_id or "")
        if (
            r.status is Status.ACCEPTED
            and r.method in (Method.NAME_SYMBOL, Method.NAME_PRICE)
            and holder not in (None, r.provider_id)
            and not within(r.price_diff_pct, None, t, keep=False)
        ):
            r.flag(Flag.MANY_TO_ONE)
            r.note = f"{r.cg_id} is published for {holder}; taking it over needs a matching price"
            r.status, r.confidence, r.cg_id = Status.FLAGGED, Confidence.LOW, None

    by_cg: dict[str, list[MatchRow]] = defaultdict(list)
    for r in rows:
        if r.status is Status.ACCEPTED and r.cg_id:
            by_cg[r.cg_id].append(r)
    for group in by_cg.values():
        if len(group) < 2:
            continue
        for r in group:
            r.flag(Flag.MANY_TO_ONE)
        by_name = [r for r in group if r.method in (Method.NAME_SYMBOL, Method.NAME_PRICE)]
        keep: MatchRow | None = None
        if len(by_name) == len(group):
            priced = [
                r
                for r in by_name
                if within(r.price_diff_pct, None, t, keep=previous.get(r.provider_id) == r.cg_id)
            ]
            sticky = [r for r in priced if previous.get(r.provider_id) == r.cg_id]
            exact = [r for r in priced if r.method is Method.NAME_SYMBOL]
            if len(sticky) == 1:
                keep = sticky[0]
            elif len(exact) == 1:
                keep = exact[0]
            elif not exact and len(priced) == 1:
                keep = priced[0]
        for r in by_name:
            if r is not keep:
                r.status, r.confidence, r.cg_id = Status.FLAGGED, Confidence.LOW, None


# Flags describing why a row was unresolved; cleared when the second pass resolves it.
_UNRESOLVED_FLAGS = frozenset(
    {
        Flag.AMBIGUOUS_MULTIPLE_CANDIDATES,
        Flag.MANY_TO_ONE,
        Flag.PRICE_DISCREPANCY,
        Flag.MCAP_DISCREPANCY,
        Flag.NAME_MISMATCH,
        Flag.SYMBOL_MISMATCH,
        Flag.NO_MARKET_DATA,
    }
)


def resolve_claimed(rows: list[MatchRow], m: Matcher) -> None:
    """Second pass: a CG coin already held by another provider coin can't also be this one.

    For every flagged/ambiguous row, candidates claimed by another accepted row are marked
    (`claimed_by`) and taken out of play. If exactly one remaining plausible candidate passes the
    price guardrail, it is accepted (matched_name_price, medium). Otherwise the suggestion moves to
    the best unclaimed candidate. Two rows resolving to the same coin are both left for review.
    """
    claimed = {r.cg_id: r.provider_id for r in rows if r.status is Status.ACCEPTED and r.cg_id}
    resolved: dict[str, list[tuple[MatchRow, Candidate]]] = defaultdict(list)
    for r in rows:
        if r.status not in (Status.FLAGGED, Status.AMBIGUOUS):
            continue
        for c in r.candidates:
            holder = claimed.get(c.cg_id)
            c.claimed_by = holder if holder != r.provider_id else None
        free = [c for c in r.candidates if c.claimed_by is None]
        if not free:
            # Every candidate already belongs to another coin: usually a duplicate or copycat
            # listing with no CoinGecko equivalent. Don't point reviewers at a taken coin.
            r.status, r.confidence, r.suggested_cg_id = Status.UNMATCHED, Confidence.NONE, None
            r.cg_price_usd = r.cg_mcap_usd = r.price_diff_pct = r.mcap_diff_pct = None
            r.note = "all candidates already mapped to other coins (duplicate or copycat listing?)"
            continue
        if len(free) == len(r.candidates):
            continue  # nothing eliminated: the first pass already judged this set
        passing = [
            c
            for c in free
            if m._plausible(c) and m._market_ok(c, keep=m._was(r.provider_id, c.cg_id))
        ]
        if len(passing) == 1 and r.price_usd is not None:
            resolved[passing[0].cg_id].append((r, passing[0]))
            continue
        _point_at(r, sorted(free, key=_candidate_order)[0])

    for claims in resolved.values():
        if len(claims) > 1:
            for r, c in claims:
                _point_at(r, c)
            continue
        r, c = claims[0]
        held = sorted(f"{x.cg_id} (by {x.claimed_by})" for x in r.candidates if x.claimed_by)
        r.flags = [f for f in r.flags if f not in _UNRESOLVED_FLAGS]
        md = {c.cg_id: MarketData(price_usd=c.price_usd, mcap_usd=c.mcap_usd)}
        m._accept(r, c.cg_id, Method.NAME_PRICE, Confidence.MEDIUM, md)
        r.note = "other candidates already mapped: " + ", ".join(held)


def _point_at(r: MatchRow, c: Candidate) -> None:
    r.suggested_cg_id = c.cg_id
    r.cg_price_usd, r.cg_mcap_usd = c.price_usd, c.mcap_usd
    r.price_diff_pct, r.mcap_diff_pct = c.price_diff_pct, c.mcap_diff_pct


def match_all(
    matcher: Matcher,
    plans: list[CoinPlan],
    prov_md: dict[str, MarketData],
    cg_md: dict[str, MarketData],
) -> list[MatchRow]:
    rows = [matcher.decide(p, prov_md, cg_md) for p in plans]
    resolve_many_to_one(rows, matcher.t, matcher.previous)
    resolve_claimed(rows, matcher)
    return rows
