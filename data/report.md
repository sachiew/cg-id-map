# CMC → CoinGecko mapping report

Generated: 2026-11-25T13:06:59Z

## Match rate

| scope | accepted |
|---|---:|
| all | 6124/7841 (78.10%) |
| top 100 by CMC rank | 100/100 (100.00%) |
| top 1,000 by CMC rank | 975/1000 (97.50%) |
| top 5,000 by CMC rank | 4445/5000 (88.90%) |

## Gold set

Precision: 34/34 (100.0%)


## Coins

### By status

| value | count |
|---|---:|
| accepted | 6124 |
| unmatched | 1091 |
| ambiguous | 495 |
| flagged | 131 |

### By method

| value | count |
|---|---:|
| matched_contract | 5458 |
| matched_name_symbol | 556 |
| matched_name_price | 56 |
| matched_contract_other_network | 52 |
| override | 2 |

### By confidence (accepted)

| value | count |
|---|---:|
| high | 6016 |
| medium | 108 |

### By flag

| value | count |
|---|---:|
| name_mismatch | 1711 |
| ambiguous_multiple_candidates | 615 |
| symbol_mismatch | 140 |
| price_discrepancy | 128 |
| network_unmapped | 84 |
| matched_contract_other_network | 54 |
| many_to_one | 32 |
| mcap_discrepancy | 28 |
| no_market_data | 17 |

## Networks

### By status

| value | count |
|---|---:|
| accepted | 69 |
| needs_review | 31 |
| unmapped | 3 |

### By method (accepted)

| value | count |
|---|---:|
| chain_id+overlap | 55 |
| name+overlap | 13 |
| chain_id | 1 |

## Thresholds

| setting | value |
|---|---:|
| network_min_overlap | 20 |
| network_lead_ratio | 2.0 |
| network_min_name_score | 70.0 |
| network_small_min_overlap | 3 |
| network_small_min_share | 0.5 |
| network_small_min_name_score | 90.0 |
| name_fuzzy_min | 85.0 |
| price_diff_pct | 5.0 |
| mcap_diff_pct | 25.0 |
| price_keep_diff_pct | 10.0 |
| mcap_keep_diff_pct | 50.0 |
| min_coin_count_ratio | 0.9 |
| max_match_rate_drop_pts | 2.0 |
| max_top1000_match_rate_drop_pts | 0.5 |
| max_cg_id_change_ratio | 0.01 |
