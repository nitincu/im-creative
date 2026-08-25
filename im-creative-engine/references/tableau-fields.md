# Tableau reference — Linkout creative performance (verified 2026-08-24)

## The datasource to use

**`ds_rm_linkout_analytics`**
LUID: `031e301f-9772-4f36-8146-da4560d6cca8`
Underlying: `reports.vw_rpt_linkout_analytics`
Observed window: rolling ~60 days (2026-06-24 → 2026-08-24 at time of writing).

Query it with `mcp__Tableau__query-datasource`.

## THE TRAP: a stale decoy datasource

**`Linkout Offerwise Data with creative ID`** (`7bb01404-7105-43f6-9d5e-705d3f784926`)
has an almost identical schema and a name that makes it look like the obvious
choice. It is **frozen at 2023-04-17 → 2023-05-16** — over three years stale —
and is still published and queryable. Anything built on it returns
confident-looking numbers about creatives that no longer exist.

**Never use it.** Always confirm freshness with `MAX(Date)` before trusting any
result from any datasource.

## Field captions

Captions are **Title Case with spaces** (`Creative Id`, not `creative_id`),
except for a handful of lower-snake fields noted below. Case matters.

### Identity and structure
`Creative Id`, `Creative Name`, `Creative Title`, `Offer Id`, `Offer Name`,
`Offer Type`, `Advertiser Name`, `Account Manager`, `sales_representative`,
`Category Name`, `Payout Type`, `Hasoffer Id`, `Campaign Slug`

### Creative content exposed as dimensions
`template_type`, `creative_option_text`, `skip_cta_name`,
`creative_nothanks_text`, `lo_creative_click`

This is unusually useful: the actual rendered copy is queryable, so outcomes can
be attributed to specific wording without joining back to Console.

### The served weight
`weight` (INTEGER measure)

Use this to verify that configured weights match served weights.

### Funnel measures
`Linkout Impression`, `Linkout Click`, `Linkout Click Verified`,
`Linkout Conversion`, `Linkout Offer Skipped`, `Linkout Offer User Returned`,
`Anticipated Revenue`, `Payout`, `Hasoffers Clicks`, `Hasoffers Unique Clicks`,
`Hasoffers Webhook Redirect`, `Total Hasoffers Clicks`, `is_exit_linkout`

### Experiment context
`Experiment Id`, `Experiment Name`, `Experiment Type`, `Experiment Slug`,
`Experiment Group Name`, `Exp Variant Id`, `Ab Experiment Id`,
`Ab Experiment Name`, `Ab Experiment Variation Name`

### Segmentation
`Site Name`, `Site Id`, `Trafficsource`, `Traffic Source Id`,
`Traffic Source Parent`, `Age Group`, `Gender`, `State`, `Os`, `device`,
`browser_name`, `usabledisplaywidth`, `usabledisplayheight`,
`diagonalscreensize`

### Position and dedup
`Offer Position`, `Offer Position Session`, `Offer Position Cookie`,
`Offer Dup Count Session`, `Offer Dup Count Cookie`, `Dup Interday`,
`Is Dup Master`, `Is Phone Email Hash Duplicate`, `Visit Num`,
`Offer Exploration Type`, `Is Fallback`, `Is Vlo`, `is_active`,
`Dimension Group Id`, `Disc Setting`

### Timing
`Date`, `created_on_date`, `updated_on_date`, `impression_eltime`,
`terminal_eltime`, `time_spent_on_offer_sec`, `time_spent_terminal_event`

### Identifiers
`Cookie Id`, `Session Id`, `User Id`, `Tag`, `Comments`

## Query patterns that work

Filter an offer exactly:
```json
{"field": {"fieldCaption": "Offer Name"}, "filterType": "SET",
 "values": ["RH - Merit Platinum $0.70 CPC (as CPA) - Linkout"], "exclude": false}
```

Find an offer when the exact name is unknown:
```json
{"field": {"fieldCaption": "Offer Name"}, "filterType": "MATCH",
 "contains": "Merit Platinum"}
```

A `SET` filter with a value that does not exist returns a helpful validation
error listing near-misses. Use that to resolve names — it is cheaper than
listing every offer.

## Query patterns that FAIL

1. **Filtering on an aggregate measure returns an empty result, not an error.**
   `QUANTITATIVE_NUMERICAL` with `MIN` against `Linkout Impression` silently
   returned `{"data": []}`. Aggregate in a script instead of in the filter.

2. **High-cardinality dimension combinations blow the token limit.** Adding
   `Experiment Name` + `Ab Experiment Name` + `Ab Experiment Variation Name` to
   one offer produced 1,936 rows and 529 KB, which is spilled to a file rather
   than returned. Keep dimensions minimal, or query wide and aggregate the
   spilled file with Python.

3. **`get-workbook` needs a LUID, not the numeric id in the Tableau UI URL.**
   `/#/workbooks/356/views` → `356` returns 404. Use `list-datasources` or
   `search-content` instead.

## Baseline established for the pilot offer

`RH - Merit Platinum $0.70 CPC (as CPA) - Linkout`, 62 days:

| bucket | impressions | CTR | skips | conv/impr | revenue | RPM |
|---|---|---|---|---|---|---|
| Creative 5060 | 84,343 | 34.0% | 50,455 (59.8%) | 29.4% | $17,444 | $206.82 |
| no `Creative Id` | 40,548 | 83.7% | 22 (0.05%) | 72.6% | $20,728 | $511.19 |

## THE OPEN QUESTION: the unattributed bucket

About a third of this offer's impressions carry **no `Creative Id`** and behave
completely differently. Investigation ruled out: a different site (both appear
on all six), fallback traffic (`Is Fallback = 0` for the bulk), a different
template (`template_type` is null, not different), and a distinct experiment arm
(both span `TnD Default Flow V5`, `FRU-Custom-Branded-Flow`, and the same A/B
experiments).

Where the two buckets are *identical* is telling: click→conversion is 86.6% vs
86.7%, and revenue per conversion is $0.703 vs $0.704. Same offer, same payout,
same downstream behaviour. The entire divergence is impression→click, plus
50,455 skips versus 22.

**This has not been identified.** It requires someone who knows the event
pipeline. Three consequences every agent must respect:

1. Offer-level RPM is a blend of two very different populations. Never quote it
   as a creative baseline.
2. A creative test only ever moves the attributed share. Always report the
   attributed share alongside any result.
3. If the unattributed share drifts week to week it will contaminate
   before/after comparisons. Always compare creative-to-creative within the
   attributed bucket, never period-over-period on offer totals.

## Org-wide context (60 days, 1,168 Linkout offers)

41.4M impressions, $9.5M anticipated revenue.

| creatives per offer | offers | % of impressions | revenue |
|---|---|---|---|
| 0 | 409 | 5.3% | $304K |
| **1** | **582** | **68.8%** | **$6.46M** |
| 2 | 99 | 10.7% | $998K |
| 3–4 | 73 | 12.7% | $1.48M |
| 5+ | 5 | 2.5% | $266K |

Volume tiers for test feasibility:
- **Tier A** — ≥250K impressions/60d: 23 offers, 13.2M impressions, $2.25M
- **Tier B** — 60K–250K: 166 offers, 19.4M impressions, $4.82M
- **Tier C** — below 60K: everything else. Do not run per-offer tests here;
  inherit from the element library instead.
