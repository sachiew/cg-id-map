from __future__ import annotations

from pathlib import Path

from cg_id_map.config import Thresholds
from cg_id_map.core.output import Changes, GoldResult
from cg_id_map.core.safety import RunStats, check

T = Thresholds()


def stats(**kw: float) -> RunStats:
    base = dict(
        provider_coins=8000, cg_coins=22000, accepted=6400, match_rate_pct=80.0,
        top1000_match_rate_pct=98.0,
    )  # fmt: skip
    return RunStats(**{**base, **kw})  # type: ignore[arg-type]


def test_first_run_only_checks_gold() -> None:
    res = check(stats(), None, Changes(), 0, GoldResult(30, 30, []), T)
    assert res.ok and res.notes


def test_healthy_run_passes() -> None:
    res = check(stats(match_rate_pct=79.0), stats(), Changes(), 6400, GoldResult(30, 30, []), T)
    assert res.ok


def test_gold_failure_fails() -> None:
    res = check(stats(), stats(), Changes(), 6400, GoldResult(30, 29, [("1", "bitcoin", None)]), T)
    assert not res.ok and "gold set" in res.failures[0] and "bitcoin" in res.failures[0]


def test_coin_count_drop_fails_for_either_provider() -> None:
    res = check(stats(provider_coins=5000), stats(), Changes(), 6400, None, T)
    assert any("provider coin count" in f for f in res.failures)
    res = check(stats(cg_coins=10000), stats(), Changes(), 6400, None, T)
    assert any("CoinGecko coin count" in f for f in res.failures)


def test_match_rate_drops() -> None:
    res = check(stats(match_rate_pct=77.5), stats(), Changes(), 6400, None, T)
    assert any("overall match rate" in f for f in res.failures)
    # Top-1000 tolerates 0.5 pts (rank shuffles move a coin or two in and out daily).
    assert check(stats(top1000_match_rate_pct=97.9), stats(), Changes(), 6400, None, T).ok
    res = check(stats(top1000_match_rate_pct=97.4), stats(), Changes(), 6400, None, T)
    assert any("top-1000" in f for f in res.failures)


def test_too_many_cg_id_changes_fail() -> None:
    changed = Changes(cg_id_changed=[(str(i), "a", "b") for i in range(65)])
    assert not check(stats(), stats(), changed, 6400, None, T).ok
    few = Changes(cg_id_changed=[(str(i), "a", "b") for i in range(64)])
    assert check(stats(), stats(), few, 6400, None, T).ok


def test_stats_roundtrip(tmp_path: Path) -> None:
    s = stats()
    s.save(tmp_path / "stats.json")
    assert RunStats.load(tmp_path / "stats.json") == s
    assert RunStats.load(tmp_path / "missing.json") is None
