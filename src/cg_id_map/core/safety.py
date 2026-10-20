"""Safety checks for unattended runs: fail (and publish nothing) when a run looks broken.

The baseline is `<out>/stats.json`, written alongside the published files. Like report.md it is
only rewritten when the published mappings change, so quiet days produce no commit.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cg_id_map.config import Thresholds
from cg_id_map.core.matcher import MatchRow
from cg_id_map.core.output import Changes, GoldResult, match_rate


@dataclass
class RunStats:
    provider_coins: int
    cg_coins: int
    accepted: int
    match_rate_pct: float
    top1000_match_rate_pct: float

    @classmethod
    def compute(cls, rows: Sequence[MatchRow], cg_coins: int) -> RunStats:
        ok, n = match_rate(rows)
        ok1k, n1k = match_rate(rows, 1000)
        return cls(
            provider_coins=len(rows),
            cg_coins=cg_coins,
            accepted=ok,
            match_rate_pct=round(ok / n * 100, 2) if n else 0.0,
            top1000_match_rate_pct=round(ok1k / n1k * 100, 2) if n1k else 0.0,
        )

    @classmethod
    def load(cls, path: Path) -> RunStats | None:
        return cls(**json.loads(path.read_text())) if path.is_file() else None

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1, sort_keys=True) + "\n")


@dataclass
class SafetyResult:
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def check(
    new: RunStats,
    prev: RunStats | None,
    changes: Changes,
    previous_accepted: int,
    gold: GoldResult | None,
    t: Thresholds,
) -> SafetyResult:
    res = SafetyResult()
    if gold is not None and gold.failures:
        shown = ", ".join(f"{i} (expected {e}, got {g or '-'})" for i, e, g in gold.failures)
        res.failures.append(f"gold set: {len(gold.failures)}/{gold.total} pairs wrong: {shown}")

    if prev is None:
        res.notes.append("no previous stats.json: count and match-rate checks skipped (first run)")
        return res

    for label, now, before in (
        ("provider coin count", new.provider_coins, prev.provider_coins),
        ("CoinGecko coin count", new.cg_coins, prev.cg_coins),
    ):
        if now < before * t.min_coin_count_ratio:
            res.failures.append(
                f"{label} fell to {now} from {before} "
                f"(< {t.min_coin_count_ratio:.0%}; API outage or pagination bug?)"
            )

    drop = prev.match_rate_pct - new.match_rate_pct
    if drop > t.max_match_rate_drop_pts:
        res.failures.append(
            f"overall match rate dropped {drop:.2f} pts "
            f"({prev.match_rate_pct}% → {new.match_rate_pct}%, max {t.max_match_rate_drop_pts})"
        )
    drop1k = prev.top1000_match_rate_pct - new.top1000_match_rate_pct
    if drop1k > t.max_top1000_match_rate_drop_pts:
        res.failures.append(
            f"top-1000 match rate dropped {drop1k:.2f} pts "
            f"({prev.top1000_match_rate_pct}% → {new.top1000_match_rate_pct}%, "
            f"max {t.max_top1000_match_rate_drop_pts})"
        )

    if previous_accepted:
        ratio = len(changes.cg_id_changed) / previous_accepted
        if ratio > t.max_cg_id_change_ratio:
            res.failures.append(
                f"{len(changes.cg_id_changed)} existing mappings changed cg_id "
                f"({ratio:.2%} > {t.max_cg_id_change_ratio:.0%})"
            )
    return res
