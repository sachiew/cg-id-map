# Contributing

Thanks for helping improve cg-id-map. The two most useful contributions are **fixing a mapping**
(an override) and **adding a provider**.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest                      # unit tests + end-to-end dry run on recorded fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

CI runs exactly these on every push and pull request. Tests never call live APIs.

To run against live APIs, copy `.env.example` to `.env` and fill in your keys (`.env` is
gitignored; never commit it). API responses are cached in `.cache/` (also gitignored) for 20 hours,
so repeated runs don't re-hit the APIs; pass `--refresh` to bypass the cache.

## Fixing a mapping (overrides)

Overrides always win over the automatic matcher and are reported as `match_method=override`.

1. Find the row in `data/review_queue.csv` (or `output/review_queue.csv` after a local run, which
   also shows prices). `cg-id-map lookup --provider cmc --id <ID>` explains how one coin was
   matched and lists its candidates.
2. Add an entry to `overrides/coins.cmc.yaml`:

   ```yaml
   - id: "12345"          # CMC ID
     cg_id: some-coin     # CoinGecko ID, or null if the coin has no CoinGecko equivalent
     reason: Same contract on Base; CMC lists the pre-rebrand name
   ```

   A network pair goes in `overrides/networks.cmc.yaml` the same way, with `key` (the CMC
   platform ID) and `cg_platform_id`.
3. Open a pull request. CI checks the file's format; every run checks that each `cg_id` exists on
   CoinGecko and fails loudly on typos. The next scheduled update picks the change up.

Please give a `reason` a reviewer can verify (a contract address, a link, a rebrand date).

## How to add a provider

CoinGecko is the hub: every provider maps *to* CG IDs. A provider is one adapter that turns the
provider's API into three lists of models; the network map, matcher, flags and outputs only use
those models, so you don't touch `core/`.

1. **Verify the API first.** Call every endpoint you plan to use and note its real shape: page
   size limits, batch limits, how missing prices and market caps look (null? 0? absent?), rate
   limits, auth. Record what you verified in the adapter's module docstring with the date.
2. **Copy the template:** `src/cg_id_map/providers/_template.py` →
   `src/cg_id_map/providers/<name>.py`, and implement:
   - `fetch_coins() -> list[ProviderCoin]`: `id`, `name`, `symbol`, `slug`, `rank` and
     `contracts`, a list of `(platform_key, raw_address)` with one entry per chain.
   - `fetch_platforms() -> list[ProviderPlatform]`: every `platform_key` used above, with a
     `name`, optional `aliases`, and `chain_id` only when it's a real EVM chain ID.
   - `fetch_market_data(ids) -> {id: MarketData}`: USD price and market cap. Zero or negative
     values are treated as missing.
   - `from_env(config, *, refresh=False)`: build the adapter, reading its own API key with
     `env_secret("<NAME>_API_KEY")`. Add the variable to `.env.example`.
3. **Register it** in `src/cg_id_map/providers/__init__.py` (`_load_builtin`) and call
   `register("<name>", YourProvider.from_env)` at the bottom of your module.
4. **Add overrides files** `overrides/coins.<name>.yaml` and `overrides/networks.<name>.yaml`
   (an empty list `[]` is fine to start).
5. **Add tests:**
   - adapter tests with `httpx.MockTransport` and tiny inline responses (see
     `tests/test_providers.py`): pagination, batching, missing-value handling, errors;
   - a gold set `tests/gold/<name>.yaml` of at least 30 well-known pairs, each checked by hand
     against both providers (majors, stablecoins, a bridged token, a rebrand, a symbol collision);
   - optionally, recorded fixtures plus an end-to-end test like `tests/test_pipeline_recorded.py`.
6. **Run it:** `cg-id-map run --provider <name> --out output/<name>` and read `report.md`:
   check the gold-set precision, the network map, and a sample of the review queue.

Every output file and column is named after the provider (`<name>_to_cg.csv`, `<name>_id`, …).

## Code style

- Match the surrounding code; ruff and mypy (strict) must pass.
- Never log or cache API keys: send keys in headers via `HttpClient`, never in URLs.
- Don't commit raw API responses or bulk data. Small trimmed fixtures under `tests/fixtures/` are
  fine (see `tests/fixtures/build_fixtures.py`).
