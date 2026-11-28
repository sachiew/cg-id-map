# CMC → CoinGecko mapping report

Generated: 2026-11-28T11:56:56Z

## Match rate

| scope | accepted |
|---|---:|
| all | 6116/7816 (78.25%) |
| top 100 by CMC rank | 100/100 (100.00%) |
| top 1,000 by CMC rank | 975/1000 (97.50%) |
| top 5,000 by CMC rank | 4442/4999 (88.86%) |

## Gold set

Precision: 34/34 (100.0%)


## Coins

### By status

| value | count |
|---|---:|
| accepted | 6116 |
| unmatched | 1084 |
| ambiguous | 489 |
| flagged | 127 |

### By method

| value | count |
|---|---:|
| matched_contract | 5448 |
| matched_name_symbol | 556 |
| matched_name_price | 59 |
| matched_contract_other_network | 51 |
| override | 2 |

### By confidence (accepted)

| value | count |
|---|---:|
| high | 6006 |
| medium | 110 |

### By flag

| value | count |
|---|---:|
| name_mismatch | 1717 |
| ambiguous_multiple_candidates | 613 |
| symbol_mismatch | 139 |
| price_discrepancy | 127 |
| network_unmapped | 83 |
| matched_contract_other_network | 53 |
| many_to_one | 30 |
| mcap_discrepancy | 27 |
| no_market_data | 16 |

## Networks

### By status

| value | count |
|---|---:|
| accepted | 69 |
| needs_review | 30 |
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
