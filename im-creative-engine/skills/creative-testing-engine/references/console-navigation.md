# Console navigation reference (verified 2026-08-24)

Everything here was observed directly in a live session. Nothing is inferred.
If you find reality differs, update this file rather than improvising.

## Access

- Base URL: `https://console.im-reporting.com`
- App name in header: **LeadGen**
- Auth: Cloudflare Access in front of an app session. Operators must already be
  logged in via **Claude's native browser** (`mcp__Claude_Browser__*`).
- Do NOT use `console.customer-acquisition.co`. It is a different Cloudflare
  Access app and rejected a valid Google identity with "That account does not
  have access." It is not the ops interface.

## Reading pages

Use `read_page` with `filter: "interactive"`. This is the only reliable way to
read Creative Manager: the meaningful data lives in form **input values**, and
`get_page_text` returns labels without values. Screenshots in the native browser
render small and are poor for dense tables.

## Navigation

Left nav is collapsed by default; the chevron at roughly `(20, 64)` expands it.
It contains a **"Search Menu"** textbox — typing a term filters the tree, which
is faster and more robust than clicking through sections.

Top-level sections: `Publisher`, `Advertiser`, `Survey Management`,
`Data Tools`, `AdHoc`, `Owned & Operated`.

`Advertiser` submenu: HostPost Offers, Linkout Offers, Offerwall Offers,
Offerwall, Advertiser, Upload Conversion, Aged Leads, Branded TCPA Optin,
**Creative Manager**, Jobs Creative Preview.

`AdHoc` submenu: **Profanity Check**, Table CRUD.

There is **no creative-level performance report anywhere in Console.** All
performance data comes from Tableau. See `tableau-fields.md`.

## Creative Manager

### Listing — `/creative-manager/listing`

Columns: `Creative ID`, `Creative Name`, `Offer Name`, `Template Name`,
`Status`, `Weightage`, `Created On`, `Created By`, `Action`.

Controls: a `Search keyword` box (matches offer name and creative name), a
per-column filter row, an `Include Archived` toggle, `Add New`, a column
selector, an export button, and pagination defaulting to 20 rows.

The `Action` column has two icons: **edit** (pencil, opens a new tab) and
**duplicate**. Duplicate is the cheapest way to seed a challenger from the
control, because it clones every slot value.

Creative names are auto-generated as `Creative <id>` — they carry no meaning.
Do not attempt to encode hypotheses in the name; use `Meta Data Tags`.

### Edit — `/creative-manager/edit/{creative_id}`

Header buttons: `Activity Log`, `Generate Preview Link`, `Cancel`, `Save`.

**General** section fields:

| Field | Type | Notes |
|---|---|---|
| Select Offer Type | combobox | `Linkout` for this plugin's scope |
| Select Offer | combobox | full offer name |
| Weightage | number input | relative serving weight |
| Creative Template | combobox | see templates below |
| Creative ID | number input, read-only | |
| Status | toggle | green = Active |
| Meta Data Tags | textarea | free JSON, **empty on every creative observed** |
| Archive this creative | checkbox | present on inactive creatives |

Also two links: `View Creative` and `Test Link`.

> **Security note.** The `View Creative` href embeds a bearer JWT in its query
> string with an expiry roughly nine months out. Never log, echo, paste, or
> store that URL. Use `Generate Preview Link` or `Test Link` for QA instead.

**Creative Offer Details** section — the slot structure:

- `Offer Title` — rich text, with font size and colour controls
- `Offer Subtitle` — rich text
- `Offer Option N Text` — repeating, each with `Linkout URL ID`,
  `Option Type` (`CTA` | `Skip`), and an animation dropdown, plus a remove `X`
- `Add Option` button
- `Disclaimer` — plain textarea
- `Skip Link / Button Text` — e.g. `No, Thanks!`
- `Add Skip Link as Option` — toggle
- `Enable PII Fields` — toggle
- `Benefit Tags` — multi-select
- `Macro Mappings` — `{{macroN}}` mapped to a macro such as `{user_first_name}`,
  with `Show Available Macros` and `Add Macro Mapping`
- `Show Preview` button

**Custom Template variant.** When `Creative Template` is `Custom Template` or
`Custom Template - AI`, the slot fields are replaced by a single
`Creative HTML` textarea with a live preview pane. An `AI Assistant` button and
an `AI Generated` badge appear on this variant. Console therefore already has
its own AI generation path; this plugin generates independently and does not
depend on it.

### Templates observed

`Single Option + No Thanks`, `Multiple Options + No Thanks`,
`Image/Video + Single Option + No Thanks`,
`Image/Video + Multiple Options + No Thanks`, `Iframe + No Thanks`,
`Custom Template`, `Custom Template - AI`.

## Weights are relative, not percentages

A creative's share of traffic is its weight divided by the sum of weights across
all **Active** creatives on that offer. Weights need not sum to 100.

| Active weights | Actual shares |
|---|---|
| `7` alone | 100% — the weight is irrelevant |
| `50`, `5` | 90.9%, 9.1% |
| `80`, `10`, `10` | 80%, 10%, 10% |
| `80`, `10`, `10`, `5` | **76.2%** — the control has breached its floor |

Inactive creatives take no traffic whatever their weight, so a switched-off
creative sitting at weight 50 does not affect shares at all. That is why raw
weights in reporting mislead: `ds_rm_linkout_analytics` carries the weight
regardless of status.

The consequence for the engine: the control's share must never fall below 80%,
so the non-control weight is a budget derived from that floor, shared by
challengers and any sentinel. Adding an Active creative outside the plan dilutes
the control and has to be paid for by rebalancing.

## THE TRAP: two independent serving gates

`Weightage` and `Status` gate serving **independently**. A challenger given
weight 10 while its `Status` toggle is off serves nothing at all — the test
returns zero data and looks like a null result rather than a misconfiguration.

**Always write both fields, and always verify afterwards.** Verification is not
optional: `ds_rm_linkout_analytics` carries a `weight` measure, so the served
weight can be read back from Tableau and compared to what was configured. Do
that before trusting any test.

## Backend API endpoints (observed, not usable directly)

Seen in network traffic on the edit page:

- `GET /backend/api/admin/creative/get-creative/{id}`
- `GET /backend/api/admin/creative/get-html-templates`
- `GET /backend/api/admin/creative/get-ai-models`
- `GET /backend/api/admin/offer/get-offer-list?type=linkout&includeChildOffers=1`
- `GET /backend/api/admin/offer/get-offer-field?type=requestDataMacros`
- `GET /backend/api/admin/offer/get-offer-field?type=userDetailMacros`
- `GET /backend/api/admin/site/site-list?live=1`
- `GET /backend/api/admin/get-access-role`
- `GET /backend/api/admin/get-notifications`

A same-origin `fetch()` from the page context **failed** — the SPA attaches auth
headers that are not available to injected script. All Console reads and writes
in this plugin therefore go through UI automation, not the API. If someone
obtains a service token later, the write path can be swapped for these
endpoints without changing anything else in the design.
