"""Output files.

Two sets:
  - published (`data/`, committed by the daily workflow): deterministic, no live prices, stable
    sort, so a run with no real changes leaves every file byte-identical.
  - full (`output/`, gitignored / CI artifact): every column including prices and diff pcts.

`last_verified` is carried forward from the previous published file while a row's
(cg_id, method, confidence, flags) is unchanged; it is set to the run date when the row is new or
any of those change. Files whose only change would be a timestamp are not rewritten.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from cg_id_map.config import Thresholds
from cg_id_map.core.flags import Status
from cg_id_map.core.matcher import Candidate, MatchRow
from cg_id_map.core.networks import NetworkMapping, NetworkStatus

REVIEW_STATUSES = (Status.FLAGGED, Status.AMBIGUOUS, Status.UNMATCHED)
TRACKED = ("cg_id", "match_method", "confidence", "flags")
LIST_LIMIT = 50


# ------------------------------------------------------------------ formatting


def sig(x: float | None, digits: int = 6) -> str:
    """Round to significant figures without float noise; '' for None."""
    if x is None:
        return ""
    if x == 0:
        return "0"
    rounded = round(x, digits - 1 - int(math.floor(math.log10(abs(x)))))
    return f"{rounded:.15g}"


def whole(x: float | None) -> str:
    return "" if x is None else str(round(x))


def pct(x: float | None) -> str:
    return "" if x is None else f"{x:.2f}"


def id_key(provider_id: str) -> tuple[int, str]:
    """Numeric IDs sort numerically, others lexically after them."""
    return (int(provider_id), "") if provider_id.isdigit() else (2**63, provider_id)


def to_csv(header: Sequence[str], rows: Iterable[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(header), lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_if_changed(path: Path, content: str) -> bool:
    if path.is_file() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _cands(cands: list[Candidate], with_market: bool) -> str:
    out = []
    for c in cands:
        d: dict[str, Any] = {
            "cg_id": c.cg_id,
            "name": c.name,
            "symbol": c.symbol,
            "via": c.via,
            "name_score": c.name_score,
        }
        if with_market:
            d |= {
                "price_usd": sig(c.price_usd) or None,
                "mcap_usd": whole(c.mcap_usd) or None,
                "price_diff_pct": c.price_diff_pct,
                "mcap_diff_pct": c.mcap_diff_pct,
            }
        out.append(d)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ published set


@dataclass
class Changes:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    cg_id_changed: list[tuple[str, str, str]] = field(default_factory=list)
    other_changed: list[tuple[str, str]] = field(default_factory=list)  # (id, description)

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.cg_id_changed or self.other_changed)

    def summary(self) -> str:
        changed = len(self.cg_id_changed) + len(self.other_changed)
        return f"+{len(self.added)} new, -{len(self.removed)} removed, ~{changed} changed"


def read_csv_by_id(path: Path, id_col: str) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(newline="") as f:
        return {r[id_col]: r for r in csv.DictReader(f)}


def slim_rows(
    rows: Iterable[MatchRow], p: str, previous: dict[str, dict[str, str]], today: str
) -> list[dict[str, str]]:
    out = []
    for r in sorted(rows, key=lambda r: id_key(r.provider_id)):
        if r.status is not Status.ACCEPTED or not r.cg_id:
            continue
        row = {
            f"{p}_id": r.provider_id,
            f"{p}_symbol": r.symbol,
            f"{p}_name": r.name,
            "cg_id": r.cg_id,
            "match_method": r.method.value,
            "confidence": r.confidence.value,
            "flags": "|".join(sorted(f.value for f in r.flags)),
        }
        prev = previous.get(r.provider_id)
        unchanged = prev is not None and all(prev.get(k) == row[k] for k in TRACKED)
        row["last_verified"] = prev["last_verified"] if prev and unchanged else today
        out.append(row)
    return out


def diff_slim(prev: dict[str, dict[str, str]], new: dict[str, dict[str, str]]) -> Changes:
    ch = Changes()
    ch.added = sorted(new.keys() - prev.keys(), key=id_key)
    ch.removed = sorted(prev.keys() - new.keys(), key=id_key)
    for i in sorted(new.keys() & prev.keys(), key=id_key):
        a, b = prev[i], new[i]
        if a["cg_id"] != b["cg_id"]:
            ch.cg_id_changed.append((i, a["cg_id"], b["cg_id"]))
            continue
        diffs = [f"{k}: {a.get(k) or '-'} → {b[k] or '-'}" for k in TRACKED[1:] if a.get(k) != b[k]]
        if diffs:
            ch.other_changed.append((i, "; ".join(diffs)))
    return ch


def changelog_section(
    date: str, ch: Changes, prev: dict[str, dict[str, str]], new: dict[str, dict[str, str]], p: str
) -> str:
    def label(i: str, rows: dict[str, dict[str, str]]) -> str:
        r = rows[i]
        return f"`{i}` {r[f'{p}_symbol']} ({r[f'{p}_name']}) → `{r['cg_id']}`"

    def block(title: str, items: list[str]) -> list[str]:
        if not items:
            return []
        shown = items[:LIST_LIMIT]
        more = [f"- … and {len(items) - LIST_LIMIT} more"] if len(items) > LIST_LIMIT else []
        return [f"### {title} ({len(items)})", "", *(f"- {s}" for s in shown), *more, ""]

    lines = [f"## {date}", "", ch.summary(), ""]
    lines += block("New mappings", [label(i, new) for i in ch.added])
    lines += block("Removed mappings", [label(i, prev) for i in ch.removed])
    lines += block(
        "cg_id changed",
        [f"`{i}` {prev[i][f'{p}_symbol']}: `{a}` → `{b}`" for i, a, b in ch.cg_id_changed],
    )
    lines += block(
        "Confidence / method / flag changes", [f"`{i}` {d}" for i, d in ch.other_changed]
    )
    return "\n".join(lines) + "\n"


def prepend_changelog(path: Path, section: str) -> None:
    title = "# Changelog\n\nOne section per run that changed the published mappings.\n\n"
    body = (
        path.read_text()[len(title) :]
        if path.is_file() and path.read_text().startswith(title)
        else ""
    )
    path.write_text(title + section + ("\n" + body if body else ""))


def review_rows(rows: Iterable[MatchRow], p: str, with_market: bool) -> list[dict[str, str]]:
    todo = [r for r in rows if r.status in REVIEW_STATUSES]
    # Most important first: by provider rank (unranked last), then ID.
    todo.sort(key=lambda r: (r.rank is None, r.rank or 0, id_key(r.provider_id)))
    out = []
    for r in todo:
        d = {
            f"{p}_rank": "" if r.rank is None else str(r.rank),
            f"{p}_id": r.provider_id,
            f"{p}_symbol": r.symbol,
            f"{p}_name": r.name,
            f"{p}_slug": r.slug or "",
            "status": r.status.value,
            "suggested_cg_id": r.suggested_cg_id or "",
            "flags": "|".join(sorted(f.value for f in r.flags)),
            "candidates": _cands(r.candidates, with_market),
        }
        if with_market:
            d |= _market(r, p)
        out.append(d)
    return out


def _market(r: MatchRow, p: str) -> dict[str, str]:
    return {
        f"{p}_price_usd": sig(r.price_usd),
        f"{p}_mcap_usd": whole(r.mcap_usd),
        "cg_price_usd": sig(r.cg_price_usd),
        "cg_mcap_usd": whole(r.cg_mcap_usd),
        "price_diff_pct": pct(r.price_diff_pct),
        "mcap_diff_pct": pct(r.mcap_diff_pct),
    }


NETWORK_HEADER = [
    "{p}_platform_id", "{p}_platform_name", "{p}_platform_slug", "{p}_chain_id", "token_count",
    "cg_platform_id", "suggested_cg_platform_id", "chain_identifier", "status", "method",
    "confidence", "overlap_count", "overlap_share", "runner_up", "runner_up_count", "name_score",
    "note",
]  # fmt: skip


def network_rows(
    networks: Iterable[NetworkMapping], p: str
) -> tuple[list[str], list[dict[str, str]]]:
    header = [h.format(p=p) for h in NETWORK_HEADER]
    rows = []
    for n in sorted(networks, key=lambda n: id_key(n.key)):
        vals = [
            n.key, n.name, n.slug or "", n.chain_id or "", n.token_count, n.cg_platform_id or "",
            n.suggested_cg_platform_id or "", n.chain_identifier or "", n.status.value,
            n.method.value, n.confidence, n.overlap_count, f"{n.overlap_share:.4f}",
            n.runner_up or "", n.runner_up_count, f"{n.name_score:.1f}", n.note,
        ]  # fmt: skip
        rows.append({h: str(v) for h, v in zip(header, vals, strict=True)})
    return header, rows


# ------------------------------------------------------------------ report


@dataclass
class GoldResult:
    total: int
    correct: int
    failures: list[tuple[str, str, str | None]]  # (provider id, expected, got)

    @property
    def precision(self) -> float:
        return self.correct / self.total if self.total else 0.0


def match_rate(rows: Sequence[MatchRow], top: int | None = None) -> tuple[int, int]:
    pool = [r for r in rows if r.status is not Status.EXCLUDED]
    if top is not None:
        pool = [r for r in pool if r.rank is not None and r.rank <= top]
    return sum(r.status is Status.ACCEPTED for r in pool), len(pool)


def render_report(
    rows: Sequence[MatchRow],
    networks: Sequence[NetworkMapping],
    p: str,
    t: Thresholds,
    gold: GoldResult | None,
    generated_at: str,
) -> str:
    def table(title: str, counts: Counter[str]) -> list[str]:
        lines = [f"### {title}", "", "| value | count |", "|---|---:|"]
        lines += [
            f"| {k or '(none)'} | {v} |"
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return [*lines, ""]

    def rate(top: int | None) -> str:
        ok, n = match_rate(rows, top)
        return f"{ok}/{n} ({ok / n * 100:.2f}%)" if n else "n/a"

    lines = [
        f"# {p.upper()} → CoinGecko mapping report",
        "",
        f"Generated: {generated_at}",
        "",
        "## Match rate",
        "",
        "| scope | accepted |",
        "|---|---:|",
        f"| all | {rate(None)} |",
        *(f"| top {n:,} by {p.upper()} rank | {rate(n)} |" for n in (100, 1000, 5000)),
        "",
    ]
    if gold is not None:
        lines += [
            "## Gold set",
            "",
            f"Precision: {gold.correct}/{gold.total} ({gold.precision * 100:.1f}%)",
            "",
            *(f"- `{i}` expected `{exp}`, got `{got or '-'}`" for i, exp, got in gold.failures),
            "",
        ]
    lines += ["## Coins", ""]
    lines += table("By status", Counter(r.status.value for r in rows))
    lines += table(
        "By method", Counter(r.method.value for r in rows if r.status is Status.ACCEPTED)
    )
    lines += table(
        "By confidence (accepted)",
        Counter(r.confidence.value for r in rows if r.status is Status.ACCEPTED),
    )
    lines += table("By flag", Counter(f.value for r in rows for f in r.flags))
    lines += ["## Networks", ""]
    lines += table("By status", Counter(n.status.value for n in networks))
    lines += table(
        "By method (accepted)",
        Counter(n.method.value for n in networks if n.status is NetworkStatus.ACCEPTED),
    )
    lines += ["## Thresholds", "", "| setting | value |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in vars(t).items()]
    return "\n".join(lines) + "\n"


def _without_timestamp(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("Generated: "))


# ------------------------------------------------------------------ writers


def write_published(
    out_dir: Path,
    p: str,
    rows: Sequence[MatchRow],
    networks: Sequence[NetworkMapping],
    t: Thresholds,
    now: datetime,
    gold: GoldResult | None = None,
) -> Changes:
    out_dir.mkdir(parents=True, exist_ok=True)
    today, stamp = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H:%M:%SZ")
    slim_path = out_dir / f"{p}_to_cg.csv"
    id_col = f"{p}_id"
    previous = read_csv_by_id(slim_path, id_col)
    slim = slim_rows(rows, p, previous, today)
    new = {r[id_col]: r for r in slim}
    changes = diff_slim(previous, new)

    header = [
        id_col,
        f"{p}_symbol",
        f"{p}_name",
        "cg_id",
        "match_method",
        "confidence",
        "flags",
        "last_verified",
    ]
    write_if_changed(slim_path, to_csv(header, slim))

    json_path = out_dir / f"{p}_to_cg.json"
    old_json = json.loads(json_path.read_text()) if json_path.is_file() else {}
    if old_json.get("mappings") != slim:
        payload = {"generated_at": stamp, "mappings": slim}
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")

    rq = review_rows(rows, p, with_market=False)
    write_if_changed(out_dir / "review_queue.csv", to_csv(list(rq[0]) if rq else [id_col], rq))
    nh, nrows = network_rows(networks, p)
    write_if_changed(out_dir / f"networks_{p}_cg.csv", to_csv(nh, nrows))

    report_path = out_dir / "report.md"
    report = render_report(rows, networks, p, t, gold, stamp)
    old = report_path.read_text() if report_path.is_file() else ""
    if _without_timestamp(old) != _without_timestamp(report):
        report_path.write_text(report)

    if changes.any:
        prepend_changelog(
            out_dir / "CHANGELOG.md", changelog_section(today, changes, previous, new, p)
        )
    return changes


def write_full(
    out_dir: Path,
    p: str,
    rows: Sequence[MatchRow],
    networks: Sequence[NetworkMapping],
    t: Thresholds,
    now: datetime,
    gold: GoldResult | None = None,
) -> None:
    """Everything, including market numbers, for local review and CI artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    full = []
    for r in sorted(rows, key=lambda r: id_key(r.provider_id)):
        full.append({
            f"{p}_id": r.provider_id, f"{p}_name": r.name, f"{p}_symbol": r.symbol,
            f"{p}_slug": r.slug or "", f"{p}_rank": "" if r.rank is None else str(r.rank),
            "cg_id": r.cg_id or "", "suggested_cg_id": r.suggested_cg_id or "",
            "status": r.status.value, "match_method": r.method.value,
            "confidence": r.confidence.value, "flags": "|".join(sorted(f.value for f in r.flags)),
            "candidates": _cands(r.candidates, True) if r.status in REVIEW_STATUSES else "",
            **_market(r, p), "note": r.note, "snapshot": stamp,
        })  # fmt: skip
    (out_dir / f"{p}_to_cg.csv").write_text(to_csv(list(full[0]) if full else [], full))
    (out_dir / f"{p}_to_cg.json").write_text(
        json.dumps({"generated_at": stamp, "rows": full}, ensure_ascii=False, indent=1) + "\n"
    )
    rq = review_rows(rows, p, with_market=True)
    (out_dir / "review_queue.csv").write_text(to_csv(list(rq[0]) if rq else [], rq))
    nh, nrows = network_rows(networks, p)
    (out_dir / f"networks_{p}_cg.csv").write_text(to_csv(nh, nrows))
    (out_dir / "report.md").write_text(render_report(rows, networks, p, t, gold, stamp))
