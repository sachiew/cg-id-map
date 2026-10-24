# CMC → CoinGecko mapping report

Generated: 2026-10-24T08:14:20Z

## Match rate

| scope | accepted |
|---|---:|
| all | 6440/8114 (79.37%) |
| top 100 by CMC rank | 100/100 (100.00%) |
| top 1,000 by CMC rank | 986/1000 (98.60%) |
| top 5,000 by CMC rank | 4525/5000 (90.50%) |

## Gold set

Precision: 34/34 (100.0%)


## Coins

### By status

| value | count |
|---|---:|
| accepted | 6440 |
| unmatched | 1026 |
| ambiguous | 507 |
| flagged | 141 |

### By method

| value | count |
|---|---:|
| matched_contract | 5722 |
| matched_name_symbol | 597 |
| matched_contract_other_network | 61 |
| matched_name_price | 60 |

### By confidence (accepted)

| value | count |
|---|---:|
| high | 6319 |
| medium | 121 |

### By flag

| value | count |
|---|---:|
| name_mismatch | 1726 |
| ambiguous_multiple_candidates | 611 |
| symbol_mismatch | 154 |
| price_discrepancy | 135 |
| network_unmapped | 100 |
| matched_contract_other_network | 63 |
| many_to_one | 45 |
| mcap_discrepancy | 26 |
| no_market_data | 21 |

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
