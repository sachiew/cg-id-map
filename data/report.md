# CMC → CoinGecko mapping report

Generated: 2026-11-06T11:02:51Z

## Match rate

| scope | accepted |
|---|---:|
| all | 6377/8025 (79.46%) |
| top 100 by CMC rank | 100/100 (100.00%) |
| top 1,000 by CMC rank | 983/1000 (98.30%) |
| top 5,000 by CMC rank | 4529/4992 (90.73%) |

## Gold set

Precision: 34/34 (100.0%)


## Coins

### By status

| value | count |
|---|---:|
| accepted | 6377 |
| unmatched | 1004 |
| ambiguous | 504 |
| flagged | 140 |

### By method

| value | count |
|---|---:|
| matched_contract | 5663 |
| matched_name_symbol | 593 |
| matched_name_price | 62 |
| matched_contract_other_network | 59 |

### By confidence (accepted)

| value | count |
|---|---:|
| high | 6256 |
| medium | 121 |

### By flag

| value | count |
|---|---:|
| name_mismatch | 1721 |
| ambiguous_multiple_candidates | 607 |
| symbol_mismatch | 152 |
| price_discrepancy | 130 |
| network_unmapped | 97 |
| matched_contract_other_network | 61 |
| many_to_one | 34 |
| mcap_discrepancy | 25 |
| no_market_data | 20 |

## Networks

### By status

| value | count |
|---|---:|
| accepted | 66 |
| needs_review | 33 |
| unmapped | 3 |

### By method (accepted)

| value | count |
|---|---:|
| chain_id+overlap | 53 |
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
