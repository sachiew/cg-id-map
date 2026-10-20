# cg-id-map

Map other crypto data providers' coin IDs to **CoinGecko coin IDs**. Every row carries a match
method, a confidence level and review flags, so you can see *why* two IDs were linked and which
links deserve a second look.

The first provider is **CoinMarketCap (CMC → CG)**. CoinGecko is the hub: every provider maps
*to* CG IDs. Adding another provider (CoinPaprika, CryptoCompare, …) takes one adapter file plus
overrides and tests; see [CONTRIBUTING.md](CONTRIBUTING.md).

> Rows with `confidence=medium` or any flags should be checked before production use.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/sachiew/cg-id-map && cd cg-id-map
uv sync
cp .env.example .env        # then fill in your keys
uv run cg-id-map run --provider cmc --out data/
```

| variable | meaning |
|---|---|
| `CG_API_KEY` | CoinGecko API key |
| `CG_API_TIER` | `pro`, `demo` or `public` (keyless; very low rate limit, fine for trying it out) |
| `CMC_API_KEY` | optional; without it the keyless CMC public API is used, which shares a small rate limit across everyone on your IP address |

Keys are read from the environment or a local `.env` file. They are sent in request headers only
and are never logged or cached.

### Commands

| command | does |
|---|---|
| `cg-id-map fetch --provider cmc` | download coins, networks and market data into `.cache/` |
| `cg-id-map networks --provider cmc` | build the network map only (`output/networks_cmc_cg.csv`) |
| `cg-id-map match --provider cmc` | match and write all outputs, reusing cached API data |
| `cg-id-map run --provider cmc` | all of the above |
| `cg-id-map lookup --provider cmc --id 1027` | explain one coin's match and list its candidates |

Common options: `--out` (published files, default `data/`), `--full-out` (full detail, default
`output/`), `--refresh` (ignore the cache), `-v`. Thresholds live in [`config.toml`](config.toml)
and can be overridden per run, e.g. `cg-id-map --price-diff-pct 3 run --provider cmc`.

## How matching works

**Step 1: networks.** Each CMC platform is mapped to a CoinGecko asset platform using three kinds
of evidence: the EVM chain ID, how many token contract addresses both providers list on it
(*contract overlap*), and name similarity. A pair is accepted automatically when the chain IDs
agree, when overlap is high and clearly ahead of the runner-up, or, for small networks, when most
tokens overlap and the names match. Everything else goes to review.

**Step 2: contract address.** A token whose contract address appears on the mapped CoinGecko
network is matched. Addresses are compared per chain family: EVM hex is case-insensitive;
Solana, Tron, TON and others are case-sensitive; Sui/Aptos `0x…::module::Type` addresses are
zero-padded; Hedera `0x…` and `0.0.N` forms are treated as equal. If the address is only found on
a *different* CoinGecko network, the match is kept at medium confidence when the ticker agrees
(usually a bridged token).

**Step 3: name and ticker.** Otherwise, exactly one CoinGecko coin with the same name *and*
ticker (after casefolding and ignoring "token", "coin", "(old)") is a match.

**Step 4: price as the last guardrail.** Only when it's uncertain (several candidates, a fuzzy
name, a different ticker after a rebrand) are USD price (default ±5%) and market cap (±25%, when
both sides have it) used to pick a candidate. Anything still unclear is flagged with every
candidate listed, never guessed.

When two CMC coins claim the same CoinGecko coin (CMC lists some copycats with identical name and
ticker), a contract match wins; otherwise only the claimant whose price agrees keeps the mapping.

Overrides in `overrides/` always win.

## Output files

`--out` (default `data/`) gets the **published** set. It is deterministic: stable sort, no live
prices, rounded numbers. A run with no real changes leaves every file byte-identical.

| file | contents |
|---|---|
| `cmc_to_cg.csv` / `.json` | accepted matches only: `cmc_id, cmc_symbol, cmc_name, cg_id, match_method, confidence, flags, last_verified`, sorted by `cmc_id`. The JSON is `{"generated_at": …, "mappings": [...]}` |
| `review_queue.csv` | flagged, ambiguous and unmatched coins, most important (by CMC rank) first, with `suggested_cg_id` and all `candidates` (JSON) |
| `networks_cmc_cg.csv` | the network map with its evidence: chain IDs, overlap count and share, runner-up, name score |
| `report.md` | counts by status, method and flag; match rate overall and for the top 100/1,000/5,000; gold-set precision; thresholds |
| `CHANGELOG.md` | one section per run that changed something: new and removed mappings, `cg_id` changes, confidence/method/flag changes |

`last_verified` is the date a mapping last changed (new, or its `cg_id`, method, confidence or
flags changed). It does not move on every run, so diffs stay meaningful. `generated_at` is when the
published content last changed.

`--full-out` (default `output/`, gitignored) gets the same files with every column, including
both providers' prices and market caps, the difference percentages and a snapshot timestamp.

### How to read `CHANGELOG.md`

Newest run first. Each section starts with a one-line summary (`+N new, -M removed, ~K changed`),
then lists the coins. A `cg_id changed` entry is the one to look at closely: it means an existing
CMC ID now points to a different CoinGecko coin.

## Glossary

**`status`**

| value | meaning |
|---|---|
| `accepted` | `cg_id` is set and published |
| `flagged` | there is a suggestion, but a guardrail failed (price, market data, many-to-one) |
| `ambiguous` | several plausible CoinGecko coins; all are listed |
| `unmatched` | no candidate at all |
| `excluded` | an override says this coin has no CoinGecko equivalent |

**`match_method`** (accepted rows)

| value | confidence | meaning |
|---|---|---|
| `override` | high | pinned in `overrides/coins.cmc.yaml` |
| `matched_contract` | high | contract address on the mapped network (medium if the address had several CoinGecko coins and name+ticker picked one) |
| `matched_contract_other_network` | medium | same address and ticker on another network (often bridged) |
| `matched_name_symbol` | high | the only CoinGecko coin with the same name and ticker |
| `matched_name_price` | medium | uncertain by name; price (and market cap) picked one candidate |

**`flags`** (pipe-separated)

| flag | meaning |
|---|---|
| `ambiguous_contract_multiple_cg` | one address belongs to several CoinGecko coins |
| `many_to_one` | several CMC IDs claim this CoinGecko coin |
| `network_unmapped` | the token's CMC network has no accepted CoinGecko network |
| `matched_contract_other_network` | address found on a different network than the network map says |
| `price_discrepancy` | prices differ by more than the threshold |
| `mcap_discrepancy` | market caps differ by more than the threshold |
| `no_market_data` | a price was needed to decide but one side has none |
| `ambiguous_multiple_candidates` | several candidates and nothing decisive |
| `name_mismatch` / `symbol_mismatch` | the matched coin's name / ticker differs (rebrands, `XBT` vs `BTC`) |

## Reviewing and contributing fixes

Start at the top of `review_queue.csv`, use `cg-id-map lookup --provider cmc --id <ID>` to see the
evidence, and add an entry with a `reason` to `overrides/coins.cmc.yaml` (or
`overrides/networks.cmc.yaml`). Details in [CONTRIBUTING.md](CONTRIBUTING.md#fixing-a-mapping-overrides).

## Limitations

- **Active coins only**, on both sides: CoinGecko's `/coins/list` returns active coins, and only
  CMC coins with `listing_status=active` are mapped.
- **CMC lists at most one network per token**, while CoinGecko lists every chain a token is on.
  Matching handles this, but CMC's choice of network decides which address is compared.
- **Market cap methodologies differ.** CMC reports no market cap for roughly half its coins, so a
  missing market cap never blocks a match; price is the main guardrail.
- **Network names drift** (e.g. CMC "MultiversX" vs CoinGecko `elrond`). Those pairs land in
  review until someone pins them in `overrides/networks.cmc.yaml`.
- **Tokenized stocks/ETFs and very new listings** often have no CoinGecko equivalent and show up
  as `unmatched`.
- **Rate limits:** the keyless CMC API shares a small, unpublished rate limit across everyone on
  the same IP address. Use a (free) CMC key for anything regular.

## Data sources

CoinGecko API: `/coins/list?include_platform=true`, `/asset_platforms`, `/coins/markets`,
`/simple/price`. CoinMarketCap API: `/v1/cryptocurrency/map`, `/v2/simple/price`,
`/v1/dex/platform/list`.

## License

[MIT](LICENSE)
