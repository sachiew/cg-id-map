"""Gold set: well-known pairs that must always resolve, used for precision and safety checks.

File format (YAML list):

    - id: "1"            # provider coin ID
      cg_id: bitcoin
      note: why this pair is in the set
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from cg_id_map.core.flags import Status
from cg_id_map.core.matcher import MatchRow
from cg_id_map.core.output import GoldResult


def load_gold(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or []
    gold: dict[str, str] = {}
    for item in data:
        key = str(item["id"])
        if key in gold:
            raise ValueError(f"{path}: duplicate id {key}")
        gold[key] = str(item["cg_id"])
    return gold


def evaluate(rows: Iterable[MatchRow], gold: dict[str, str]) -> GoldResult | None:
    if not gold:
        return None
    by_id = {r.provider_id: r for r in rows}
    failures = []
    for pid, expected in sorted(gold.items()):
        r = by_id.get(pid)
        got = r.cg_id if r is not None and r.status is Status.ACCEPTED else None
        if got != expected:
            failures.append((pid, expected, got))
    return GoldResult(total=len(gold), correct=len(gold) - len(failures), failures=failures)
