# CMC → CoinGecko mapping report

Generated: 2026-11-17T12:00:56Z

## Match rate

| scope | accepted |
|---|---:|
| all | 6250/7962 (78.50%) |
| top 100 by CMC rank | 100/100 (100.00%) |
| top 1,000 by CMC rank | 977/1000 (97.70%) |
| top 5,000 by CMC rank | 4467/5000 (89.34%) |

## Gold set

Precision: 34/34 (100.0%)


## Coins

### By status

| value | count |
|---|---:|
| accepted | 6250 |
| unmatched | 1086 |
| ambiguous | 499 |
| flagged | 127 |

### By method

| value | count |
|---|---:|
| matched_contract | 5552 |
| matched_name_symbol | 579 |
| matched_name_price | 60 |
| matched_contract_other_network | 57 |
| override | 2 |

### By confidence (accepted)

| value | count |
|---|---:|
| high | 6133 |
| medium | 117 |

### By flag

| value | count |
|---|---:|
| name_mismatch | 1713 |
| ambiguous_multiple_candidates | 613 |
| symbol_mismatch | 146 |
| price_discrepancy | 126 |
| network_unmapped | 94 |
| matched_contract_other_network | 59 |
| many_to_one | 32 |
| mcap_discrepancy | 26 |
| no_market_data | 17 |

## Networks

### By status

| value | count |
|---|---:|
| accepted | 67 |
| needs_review | 32 |
| unmapped | 3 |

### By method (accepted)

| value | count |
|---|---:|
| chain_id+overlap | 54 |
| name+overlap | 12 |
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
