# cg-id-map

Map other crypto data providers' coin IDs to **CoinGecko coin IDs**, with a match method,
confidence level and review flags on every row.

The first provider is **CoinMarketCap (CMC → CG)**. CoinGecko is the hub: every provider maps
*to* CG IDs, and you add a new provider (CoinPaprika, CryptoCompare, …) by writing one adapter,
without touching the matching engine.

> **Status: work in progress.** The core engine (normalization, network mapping, matcher,
> outputs) is built and tested. The CLI, the published data files and the daily auto-update
> are coming next, and this README will be expanded with them.

## How matching works

1. **Networks first.** Each CMC platform is mapped to a CG asset platform using the EVM chain
   ID, the number of token contract addresses both providers list on it, and name similarity.
   Humans can pin any pair in `overrides/networks.cmc.yaml`.
2. **Contract address.** A token whose contract address is on the mapped network is matched
   (`matched_contract`, high confidence). Addresses are compared per chain family: EVM hex is
   case-insensitive; Solana, Tron, TON and others are case-sensitive; Sui/Aptos type tags and
   Hedera `0.0.N` IDs are normalized.
3. **Name and ticker.** Otherwise, exactly one CG coin with the same name *and* ticker is a
   match (`matched_name_symbol`, high confidence).
4. **Price as a last guardrail.** Only when it's uncertain (several candidates, a fuzzy name,
   or a different ticker) are price and market cap used to pick a candidate
   (`matched_name_price`, medium). Anything still unclear goes to a review queue rather than
   being guessed.

Manual coin pins live in `overrides/coins.cmc.yaml`, and an override always wins.

## Development

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest
uv run ruff check . && uv run mypy src
```

API keys are read from environment variables, or from a local `.env` file (copy
`.env.example`; never commit `.env`):

| variable | meaning |
|---|---|
| `CG_API_KEY` | CoinGecko API key |
| `CG_API_TIER` | `pro`, `demo` or `public` (keyless, heavily rate-limited) |
| `CMC_API_KEY` | optional; without it the keyless CMC public API is used |

## Data sources

CoinGecko API (`/coins/list`, `/asset_platforms`, `/coins/markets`, `/simple/price`) and
CoinMarketCap API (`/v1/cryptocurrency/map`, `/v2/simple/price`, `/v1/dex/platform/list`).
Only active coins are mapped.

## License

[MIT](LICENSE)
