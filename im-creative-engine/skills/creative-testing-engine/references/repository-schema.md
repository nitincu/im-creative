# Repository schema

Five tabs. Column order is the sheet's column order and **must not change** —
the Apps Script appends positionally, so reordering silently shifts every value
into the wrong column.

Access only via `scripts/repo_client.py`. It validates row width before sending,
because `setValues` rejects ragged rows, and it mirrors every write to
`~/.im-creative-engine/mirror/<tab>.jsonl` so nothing is lost if the endpoint is
unreachable.

## `tests` — one row per launched test

| column | notes |
|---|---|
| `test_id` | `T-<offer_short>-<yyyymmdd>-<n>` |
| `created_at` | UTC ISO 8601 |
| `operator` | who ran it |
| `offer_id` | Console offer UUID |
| `offer_name` | exact Tableau/Console name |
| `advertiser`, `category`, `tier` | tier A/B/C by 60-day volume |
| `control_creative_id` | largest weight among Active at launch |
| `control_template` | |
| `control_conv_per_impr` | **the baseline**, attributed bucket only |
| `control_ctr`, `control_skip_rate`, `control_click_to_conv` | |
| `attributed_share` | share of impressions carrying a `Creative Id`. Below 0.8, every result on this offer is caveated |
| `mode` | `incremental` or `berserk` |
| `brief` | the operator's stated intent, verbatim |
| `status` | `running`, `concluded`, `killed` |
| `min_days`, `max_days`, `target_mde` | decision parameters in force |

## `variants` — one row per creative in a test

| column | notes |
|---|---|
| `test_id`, `creative_id` | |
| `role` | `control`, `challenger`, `sentinel` |
| `hypothesis` | what this variant claims |
| `varied_attributes` | JSON, `{"hook_type":"benefit -> urgency"}` |
| `template` | |
| `weight_configured` | what was written to Console |
| `weight_verified` | what Tableau's `weight` measure actually reports. **A mismatch means the write did not take** |
| `status` | Console Status at write time |
| `created_at` | |
| `compliance_hard`, `compliance_soft` | pre-flight findings. `compliance_hard` must be empty for anything live |

## `outcomes` — one row per arm per evaluation

Append on **every** monitoring pass, including `continue` verdicts. The time
series is what makes creative decay visible; only recording conclusions throws
that away.

| column | notes |
|---|---|
| `test_id`, `creative_id`, `decided_at` | |
| `impressions`, `clicks`, `conversions`, `revenue` | |
| `conv_per_impr`, `ctr`, `skip_rate`, `click_to_conv` | |
| `p_beat_control` | from `sequential_test.py` |
| `rel_lift` | relative, vs control |
| `verdict` | `promote`, `kill`, `continue`, `inconclusive` |
| `reason` | the script's stated reason, verbatim |
| `guardrail_breach` | non-empty means a guardrail vetoed a statistical result |

## `elements` — the learning library

This is the tab that stops repeated darts. Everything else is bookkeeping.

| column | notes |
|---|---|
| `element_key` | `<attribute>::<value>::<category>` |
| `attribute` | e.g. `hook_type` |
| `value` | e.g. `urgency` |
| `category`, `tag`, `template` | scope of the finding |
| `n_tests`, `n_wins`, `n_losses` | |
| `total_impressions` | denominator behind the claim |
| `weighted_rel_lift` | impression-weighted mean across tests |
| `confidence` | `low` under 3 tests, `medium` 3–6, `high` above 6 |
| `last_updated` | |

Query it server-side rather than pulling it whole:

```
&tq=select * where D = 'financial' order by K desc
```

## `audit` — every Console field change

| column | notes |
|---|---|
| `timestamp`, `operator`, `action` | |
| `offer_id`, `creative_id`, `field` | |
| `from_value`, `to_value` | |
| `test_id`, `notes` | |

With full-auto write authority and no role gate, this tab is the only record of
who changed what. Append before the write, not after — a failed write with an
audit row is diagnosable; a successful write with no audit row is not.
