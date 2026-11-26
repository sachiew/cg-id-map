# CMC → CoinGecko mapping report

Generated: 2026-11-26T12:47:00Z

## Match rate

| scope | accepted |
|---|---:|
| all | 6117/7824 (78.18%) |
| top 100 by CMC rank | 100/100 (100.00%) |
| top 1,000 by CMC rank | 975/1000 (97.50%) |
| top 5,000 by CMC rank | 4440/5000 (88.80%) |

## Gold set

Precision: 34/34 (100.0%)


## Coins

### By status

| value | count |
|---|---:|
| accepted | 6117 |
| unmatched | 1084 |
| ambiguous | 494 |
| flagged | 129 |

### By method

| value | count |
|---|---:|
| matched_contract | 5451 |
| matched_name_symbol | 556 |
| matched_name_price | 57 |
| matched_contract_other_network | 51 |
| override | 2 |

### By confidence (accepted)

| value | count |
|---|---:|
| high | 6009 |
| medium | 108 |

### By flag

| value | count |
|---|---:|
| name_mismatch | 1712 |
| ambiguous_multiple_candidates | 616 |
| symbol_mismatch | 140 |
| price_discrepancy | 128 |
| network_unmapped | 84 |
| matched_contract_other_network | 53 |
| many_to_one | 31 |
| mcap_discrepancy | 29 |
| no_market_data | 16 |

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
