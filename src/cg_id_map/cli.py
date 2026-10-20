"""cg-id-map command line."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from cg_id_map.config import Config
from cg_id_map.core.gold import evaluate, load_gold
from cg_id_map.core.matcher import MatchRow
from cg_id_map.core.networks import NetworkMapping
from cg_id_map.core.output import (
    Changes,
    GoldResult,
    diff_slim,
    match_rate,
    read_csv_by_id,
    slim_rows,
    write_full,
    write_published,
)
from cg_id_map.core.safety import RunStats
from cg_id_map.core.safety import check as safety_check
from cg_id_map.http import ApiError
from cg_id_map.pipeline import Pipeline

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)

ProviderOpt = Annotated[str, typer.Option("--provider", "-p", help="Provider to map to CoinGecko.")]
OutOpt = Annotated[Path, typer.Option("--out", help="Published data directory (committed).")]
FullOutOpt = Annotated[Path, typer.Option("--full-out", help="Full-detail output directory.")]
RefreshOpt = Annotated[bool, typer.Option("--refresh", help="Ignore cached API responses.")]


class State:
    config: Config = Config()
    overrides_dir: Path = Path("overrides")
    gold_dir: Path = Path("tests/gold")


@app.callback()
def main(
    config: Annotated[Path, typer.Option(help="Thresholds and HTTP settings.")] = Path(
        "config.toml"
    ),
    overrides: Annotated[Path, typer.Option(help="Overrides directory.")] = Path("overrides"),
    gold: Annotated[Path, typer.Option(help="Gold set directory.")] = Path("tests/gold"),
    price_diff_pct: Annotated[float | None, typer.Option(help="Max price difference, %.")] = None,
    mcap_diff_pct: Annotated[
        float | None, typer.Option(help="Max market cap difference, %.")
    ] = None,
    name_fuzzy_min: Annotated[
        float | None, typer.Option(help="Min fuzzy name score, 0-100.")
    ] = None,
    network_min_overlap: Annotated[
        int | None, typer.Option(help="Min shared addresses to auto-accept a network pair.")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )
    cfg = Config.load(config)
    t = cfg.thresholds
    for attr, value in (
        ("price_diff_pct", price_diff_pct),
        ("mcap_diff_pct", mcap_diff_pct),
        ("name_fuzzy_min", name_fuzzy_min),
        ("network_min_overlap", network_min_overlap),
    ):
        if value is not None:
            setattr(t, attr, value)
    State.config, State.overrides_dir, State.gold_dir = cfg, overrides, gold


def _pipeline(provider: str, refresh: bool) -> Pipeline:
    try:
        return Pipeline.create(
            provider, State.config, refresh=refresh, overrides_dir=State.overrides_dir
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _fail(exc: Exception) -> typer.Exit:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _network_summary(networks: list[NetworkMapping]) -> str:
    c = Counter(n.status.value for n in networks)
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


@app.command()
def fetch(provider: ProviderOpt = "cmc", refresh: RefreshOpt = False) -> None:
    """Download coins, platforms and market data into the local cache."""
    p = _pipeline(provider, refresh)
    try:
        inp = p.load()
        p.provider.fetch_market_data([c.id for c in inp.coins])
        p.cg.markets()
    except ApiError as exc:
        raise _fail(exc) from None
    typer.echo(
        f"{provider}: {len(inp.coins)} coins, {len(inp.platforms)} platforms | "
        f"CoinGecko: {len(inp.cg_coins)} coins, {len(inp.cg_platforms)} platforms"
    )


@app.command()
def networks(
    provider: ProviderOpt = "cmc",
    full_out: FullOutOpt = Path("output"),
    refresh: RefreshOpt = False,
) -> None:
    """Build the provider → CoinGecko network map (Step 1)."""
    from cg_id_map.core.output import network_rows, to_csv

    p = _pipeline(provider, refresh)
    try:
        nets = p.networks(p.load())
    except ApiError as exc:
        raise _fail(exc) from None
    header, rows = network_rows(nets, provider)
    full_out.mkdir(parents=True, exist_ok=True)
    path = full_out / f"networks_{provider}_cg.csv"
    path.write_text(to_csv(header, rows))
    typer.echo(f"{len(nets)} platforms: {_network_summary(nets)} → {path}")


def _match_and_write(
    p: Pipeline, out: Path, full_out: Path, *, check: bool
) -> tuple[list[MatchRow], Changes, GoldResult | None]:
    inp = p.load()
    nets = p.networks(inp)
    rows = p.match(inp, nets)
    t = State.config.thresholds
    gold = evaluate(rows, load_gold(State.gold_dir / f"{p.name}.yaml"))
    now = datetime.now(UTC)
    typer.echo(f"networks: {_network_summary(nets)}")
    # Full detail is always written (CI uploads it as an artifact, also on failure).
    write_full(full_out, p.name, rows, nets, t, now, gold)

    stats_path = out / "stats.json"
    prev_stats = RunStats.load(stats_path)
    new_stats = RunStats.compute(rows, len(inp.cg_coins))
    if check:
        id_col = f"{p.name}_id"
        previous = read_csv_by_id(out / f"{p.name}_to_cg.csv", id_col)
        new_slim = {
            r[id_col]: r for r in slim_rows(rows, p.name, previous, now.strftime("%Y-%m-%d"))
        }
        result = safety_check(
            new_stats, prev_stats, diff_slim(previous, new_slim), len(previous), gold, t
        )
        for note in result.notes:
            typer.echo(f"note: {note}")
        if not result.ok:
            for f in result.failures:
                typer.secho(f"SAFETY CHECK FAILED: {f}", fg=typer.colors.RED, err=True)
            _step_summary(_failure_markdown(p.name, result.failures))
            raise typer.Exit(1)

    changes = write_published(out, p.name, rows, nets, t, now, gold)
    if changes.any or prev_stats is None:
        new_stats.save(stats_path)
    full_out.mkdir(parents=True, exist_ok=True)
    (full_out / "change_summary.txt").write_text(changes.summary() + "\n")
    _step_summary(_success_markdown(p.name, rows, changes, gold))
    return rows, changes, gold


def _step_summary(markdown: str) -> None:
    """Append to the GitHub Actions job summary when running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(markdown + "\n")


def _failure_markdown(provider: str, failures: list[str]) -> str:
    lines = [f"## ❌ {provider} → CoinGecko update blocked by safety checks", ""]
    lines += [f"- {f}" for f in failures]
    lines += ["", "Nothing was published. Full outputs are attached as the `full-output` artifact."]
    return "\n".join(lines)


def _success_markdown(
    provider: str, rows: list[MatchRow], changes: Changes, gold: GoldResult | None
) -> str:
    statuses = Counter(r.status.value for r in rows)
    lines = [f"## ✅ {provider} → CoinGecko update", "", f"**Changes:** {changes.summary()}", ""]
    lines += ["| scope | accepted |", "|---|---:|"]
    for top in (None, 100, 1000, 5000):
        ok, n = match_rate(rows, top)
        label = "all" if top is None else f"top {top:,}"
        lines.append(f"| {label} | {ok}/{n} ({ok / n * 100 if n else 0:.2f}%) |")
    lines += ["", "**Status:** " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items()))]
    if gold is not None:
        lines.append(f"**Gold set:** {gold.correct}/{gold.total}")
    if changes.cg_id_changed:
        lines += ["", "### cg_id changed", ""]
        lines += [f"- `{i}`: `{a}` → `{b}`" for i, a, b in changes.cg_id_changed[:20]]
    if changes.added:
        lines += ["", f"### New mappings (first {min(20, len(changes.added))})", ""]
        lines += [f"- `{i}`" for i in changes.added[:20]]
    if changes.removed:
        lines += ["", f"### Removed mappings (first {min(20, len(changes.removed))})", ""]
        lines += [f"- `{i}`" for i in changes.removed[:20]]
    return "\n".join(lines)


def _print_summary(rows: list[MatchRow], changes: Changes, gold: GoldResult | None) -> None:
    statuses = Counter(r.status.value for r in rows)
    typer.echo("coins: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())))
    for top in (None, 100, 1000, 5000):
        ok, n = match_rate(rows, top)
        label = "all" if top is None else f"top {top}"
        typer.echo(f"  match rate {label:>9}: {ok}/{n} ({ok / n * 100 if n else 0:.2f}%)")
    if gold is not None:
        typer.echo(f"gold set: {gold.correct}/{gold.total}")
        for pid, exp, got in gold.failures:
            typer.secho(f"  MISS {pid}: expected {exp}, got {got or '-'}", fg=typer.colors.YELLOW)
    typer.echo(f"changes vs previous published data: {changes.summary()}")


CheckOpt = Annotated[
    bool,
    typer.Option(
        "--check/--no-check",
        help="Run safety checks against the previous run; on failure publish nothing, exit 1.",
    ),
]


@app.command()
def match(
    provider: ProviderOpt = "cmc",
    out: OutOpt = Path("data"),
    full_out: FullOutOpt = Path("output"),
    refresh: RefreshOpt = False,
    check: CheckOpt = False,
) -> None:
    """Match coins (Steps 2-4) and write outputs, using cached API data where fresh."""
    p = _pipeline(provider, refresh)
    try:
        rows, changes, gold = _match_and_write(p, out, full_out, check=check)
    except ApiError as exc:
        _step_summary(f"## ❌ {provider} → CoinGecko update failed\n\n- API error: {exc}")
        raise _fail(exc) from None
    _print_summary(rows, changes, gold)


@app.command()
def run(
    provider: ProviderOpt = "cmc",
    out: OutOpt = Path("data"),
    full_out: FullOutOpt = Path("output"),
    refresh: RefreshOpt = False,
    check: CheckOpt = False,
) -> None:
    """All steps: fetch, network map, match, outputs. Use --check for unattended runs."""
    match(provider, out, full_out, refresh, check)


@app.command()
def lookup(
    id: Annotated[str, typer.Option("--id", help="Provider coin ID, e.g. 1027.")],
    provider: ProviderOpt = "cmc",
    as_json: Annotated[bool, typer.Option("--json", help="Print the full row as JSON.")] = False,
) -> None:
    """Explain how one coin maps (many-to-one checks need a full run)."""
    p = _pipeline(provider, refresh=False)
    try:
        inp = p.load()
        r = p.lookup(inp, p.networks(inp), id)
    except (ApiError, KeyError) as exc:
        raise _fail(exc) from None
    if as_json:
        typer.echo(json.dumps(r.model_dump(mode="json"), indent=2, ensure_ascii=False))
        return
    typer.echo(f"{provider} {r.provider_id}: {r.name} ({r.symbol}), rank {r.rank}")
    typer.echo(f"  → cg_id:      {r.cg_id or '-'}   (suggested: {r.suggested_cg_id or '-'})")
    typer.echo(
        f"  status:      {r.status.value}  method: {r.method.value or '-'}  "
        f"confidence: {r.confidence.value or '-'}"
    )
    typer.echo(f"  flags:       {', '.join(f.value for f in r.flags) or '-'}")
    typer.echo(f"  price:       {r.price_usd} vs CG {r.cg_price_usd}  (diff {r.price_diff_pct}%)")
    typer.echo(f"  mcap:        {r.mcap_usd} vs CG {r.cg_mcap_usd}  (diff {r.mcap_diff_pct}%)")
    if r.note:
        typer.echo(f"  note:        {r.note}")
    for c in r.candidates:
        typer.echo(
            f"    candidate {c.cg_id:<30} via={c.via:<22} name={c.name_score:5.1f} "
            f"price={c.price_usd} Δ{c.price_diff_pct}%"
        )


if __name__ == "__main__":
    app()
