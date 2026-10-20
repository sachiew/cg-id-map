from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from cg_id_map.config import Thresholds
from cg_id_map.core.flags import Confidence, Flag, Method, Status
from cg_id_map.core.matcher import Candidate, MatchRow
from cg_id_map.core.output import (
    GoldResult,
    match_rate,
    sig,
    write_full,
    write_published,
)

DAY1 = datetime(2026, 10, 20, 3, 17, tzinfo=UTC)
DAY2 = datetime(2026, 10, 21, 3, 17, tzinfo=UTC)


def row(
    pid: str,
    cg_id: str | None,
    status: Status = Status.ACCEPTED,
    method: Method = Method.CONTRACT,
    confidence: Confidence = Confidence.HIGH,
    flags: list[Flag] | None = None,
    rank: int | None = None,
    price: float | None = 1.23456789,
) -> MatchRow:
    return MatchRow(
        provider_id=pid, name=f"Coin {pid}", symbol=f"C{pid}", slug=f"coin-{pid}",
        rank=rank if rank is not None else int(pid), cg_id=cg_id,
        suggested_cg_id=cg_id or (f"maybe-{pid}" if status is not Status.UNMATCHED else None),
        status=status, method=method if status is Status.ACCEPTED else Method.NONE,
        confidence=confidence, flags=flags or [], price_usd=price, mcap_usd=1e9 / 3,
        cg_price_usd=price, cg_mcap_usd=1e9 / 3, price_diff_pct=0.0, mcap_diff_pct=0.0,
        candidates=[Candidate(cg_id=f"maybe-{pid}", name="M", symbol="m", via="symbol",
                              name_score=50.0, name_equal=False, symbol_equal=True,
                              slug_equal=False, price_usd=price)]
        if status in (Status.FLAGGED, Status.AMBIGUOUS) else [],
    )  # fmt: skip


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def base_rows() -> list[MatchRow]:
    return [
        row("1027", "ethereum"),
        row("1", "bitcoin", method=Method.NAME_SYMBOL),
        row("5", None, Status.FLAGGED, flags=[Flag.PRICE_DISCREPANCY]),
        row("6", None, Status.AMBIGUOUS, rank=2),
        row("7", None, Status.UNMATCHED),
        row("8", None, Status.EXCLUDED, method=Method.OVERRIDE),
    ]


def publish(tmp: Path, rows: list[MatchRow], now: datetime) -> object:
    return write_published(tmp, "cmc", rows, [], Thresholds(), now, GoldResult(2, 2, []))


def test_slim_csv_has_only_accepted_sorted_numerically(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    rows = read(tmp_path / "cmc_to_cg.csv")
    assert [r["cmc_id"] for r in rows] == ["1", "1027"]
    assert list(rows[0]) == ["cmc_id", "cmc_symbol", "cmc_name", "cg_id", "match_method",
                             "confidence", "flags", "last_verified"]  # fmt: skip
    assert rows[0]["last_verified"] == "2026-10-20"
    payload = json.loads((tmp_path / "cmc_to_cg.json").read_text())
    assert payload["generated_at"] == "2026-10-20T03:17:00Z" and payload["mappings"] == rows


def test_rerun_without_changes_rewrites_nothing(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    changes = publish(tmp_path, base_rows(), DAY2)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert before == after
    assert not changes.any  # type: ignore[attr-defined]


def test_price_moves_do_not_touch_published_files(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    moved = [r.model_copy(update={"price_usd": 9.99, "cg_price_usd": 9.98}) for r in base_rows()]
    publish(tmp_path, moved, DAY2)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_last_verified_changes_only_for_changed_rows(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    rows2 = base_rows()
    rows2[0] = row("1027", "ethereum", confidence=Confidence.MEDIUM)
    changes = publish(tmp_path, rows2, DAY2)
    by_id = {r["cmc_id"]: r for r in read(tmp_path / "cmc_to_cg.csv")}
    assert by_id["1"]["last_verified"] == "2026-10-20"
    assert by_id["1027"]["last_verified"] == "2026-10-21"
    assert changes.summary() == "+0 new, -0 removed, ~1 changed"  # type: ignore[attr-defined]


def test_changelog_lists_new_removed_and_cg_id_changes(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    rows2 = [row("1027", "ethereum-new"), row("825", "tether")]  # 1 removed, 825 new, 1027 changed
    changes = publish(tmp_path, rows2, DAY2)
    assert changes.summary() == "+1 new, -1 removed, ~1 changed"  # type: ignore[attr-defined]
    log = (tmp_path / "CHANGELOG.md").read_text()
    assert log.startswith("# Changelog")
    day2 = log.index("## 2026-10-21")
    assert day2 < log.index("## 2026-10-20")  # newest first
    section = log[day2 : log.index("## 2026-10-20")]
    assert "`825` C825 (Coin 825) → `tether`" in section
    assert "### Removed mappings (1)" in section and "`1` C1" in section
    assert "`1027` C1027: `ethereum` → `ethereum-new`" in section


def test_review_queue_sorted_by_rank_and_published_without_prices(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    rq = read(tmp_path / "review_queue.csv")
    assert [r["cmc_id"] for r in rq] == ["6", "5", "7"]  # rank 2 first; excluded not queued
    assert "cmc_price_usd" not in rq[0]
    assert "price_usd" not in rq[0]["candidates"]
    assert json.loads(rq[0]["candidates"])[0]["cg_id"] == "maybe-6"


def test_full_output_has_market_columns_and_rounding(tmp_path: Path) -> None:
    write_full(tmp_path, "cmc", base_rows(), [], Thresholds(), DAY1)
    full = {r["cmc_id"]: r for r in read(tmp_path / "cmc_to_cg.csv")}
    assert full["1"]["cmc_price_usd"] == "1.23457"
    assert full["1"]["cmc_mcap_usd"] == "333333333"
    assert full["5"]["status"] == "flagged" and full["5"]["candidates"]
    assert "price_usd" in read(tmp_path / "review_queue.csv")[0]["candidates"]


def test_report_has_rates_and_gold(tmp_path: Path) -> None:
    publish(tmp_path, base_rows(), DAY1)
    rep = (tmp_path / "report.md").read_text()
    assert "| all | 2/5 (40.00%) |" in rep  # excluded rows are not counted
    assert "Precision: 2/2 (100.0%)" in rep
    assert "price_diff_pct" in rep


def test_match_rate_top_n() -> None:
    rows = base_rows()
    assert match_rate(rows, 100) == (1, 4)  # rank 1, 2, 5, 7 (1027 and excluded 8 out)


def test_sig() -> None:
    assert sig(None) == "" and sig(0) == "0"
    assert sig(82390.123456) == "82390.1"
    assert sig(0.000012345678) == "1.23457e-05"
    assert sig(0.1 + 0.2) == "0.3"


def test_market_flags_are_not_published_on_accepted_rows(tmp_path: Path) -> None:
    rows = [row("1", "bitcoin", flags=[Flag.PRICE_DISCREPANCY, Flag.NAME_MISMATCH])]
    publish(tmp_path, rows, DAY1)
    assert read(tmp_path / "cmc_to_cg.csv")[0]["flags"] == "name_mismatch"
    # A price move that only toggles the market flag changes nothing published.
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    changes = publish(tmp_path, [row("1", "bitcoin", flags=[Flag.NAME_MISMATCH])], DAY2)
    assert not changes.any  # type: ignore[attr-defined]
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    write_full(tmp_path / "full", "cmc", rows, [], Thresholds(), DAY1)
    assert "price_discrepancy" in read(tmp_path / "full" / "cmc_to_cg.csv")[0]["flags"]
