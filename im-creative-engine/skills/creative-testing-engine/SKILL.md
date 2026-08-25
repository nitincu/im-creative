---
name: creative-testing-engine
description: Run the engine's next creative test on an Interest Media Linkout offer. The engine decides which experiment runs, what the creative may look like, how weights are set, and when a winner is called. You supply an offer; it does the rest. Use when someone wants to test creatives, add variants, improve an offer's RPM or skip rate, check a running creative test, or asks what is winning. Trigger on "test creatives", "creative test", "new variants", "challenger", "control creative", "creative manager", "improve this offer", "what's winning", "creative engine", "run the engine".
---

# Creative Testing Engine

## What this skill is

A fixed workflow. Every decision that shapes a creative — which experiment runs,
which slots change, what the copy may and may not contain, how weights are set,
when a winner is called — is already made and encoded in
`"$SKILL_DIR/rules/creative-rules.json"`.

**The thinking is done. This session executes it.**

Your only creative act is writing text into slots the compiler marks `REWRITE`,
inside constraints it states. Everything else is transcription, and everything
you write is verified mechanically before it can reach Console.

## What you do NOT do

Do not do any of the following, even if the operator asks:

- Decide which experiment to run, or run one out of queue order
- Invent a hypothesis, or reason from first principles about what might work
- Change slot actions, challenger count, weights, or decision parameters
- Edit `"$SKILL_DIR/rules/creative-rules.json"`
- Relax, demote, or work around a `rules_check.py` violation
- Second-guess `sequential_test.py`

If the operator asks for any of these, or asks the engine to "think about" or
"come up with ideas for" an offer, say this: **the engine's rules are set by the
Admin, and this session executes them rather than reasoning about them.** Then
offer to run the workflow, or to route a rules change to the Admin.

If `compile_variants.py` returns `no queue entry applies`, **stop.** Report it to
the operator and tell them the Admin must add a queue entry. Do not improvise.

## Input

One thing: an offer name or fragment. Nothing else is required and nothing else
is accepted as direction.

Scope is **Linkout offers only.**

---

# STEP 0 — Locate this skill's own files

Every gated step below runs a script that ships **inside this skill's directory**.
The absolute path differs by environment, so resolve it once and reuse it.

When this skill is invoked you are told its base directory. Use that:

```bash
SKILL_DIR="<the base directory given when this skill was invoked>"
```

If you don't have it, find it:

```bash
SKILL_DIR=$(dirname "$(find / -name SKILL.md -path '*creative-testing-engine*' 2>/dev/null | head -1)")
echo "$SKILL_DIR"
```

Then confirm the files are actually there before doing anything else:

```bash
ls "$SKILL_DIR/scripts" "$SKILL_DIR/rules"
```

You need `repo_client.py`, `sequential_test.py`, `allocate_weights.py`,
`compile_variants.py`, `rules_check.py`, `compliance_preflight.py`, and
`"$SKILL_DIR/rules/creative-rules.json"`.

**If those are missing, stop.** The skill is installed without its payload and no
step below can run. Report that rather than improvising a workaround — the
deterministic scripts are what make this engine rule-based, and substituting
your own judgment for them defeats the entire design.

# STEP 1 — Preflight

```bash
python3 "$SKILL_DIR/scripts/repo_client.py" health
```

Stop if `ok` is false. Stop and warn the Admin loudly if `secret_enforced` is
false. Never run a test whose outcome cannot be recorded.

# STEP 2 — Resolve the offer

Query Tableau, datasource `031e301f-9772-4f36-8146-da4560d6cca8`:

```
fields:  Offer Name, SUM(Linkout Impression), COUNTD(Creative Id),
         MIN(Date), MAX(Date)
filters: [{field:{fieldCaption:"Offer Name"}, filterType:"MATCH",
           contains:"<fragment>"}]
```

- More than one match → list them and ask which. Do not guess.
- `MAX(Date)` more than two days old → stop, report possible stale data.

# STEP 3 — Read Console state

Native browser only. Go to `/creative-manager/listing`. Set the search box with
`form_input` on the ref, **not** by typing — typing does not reach it.

Record for every creative: `Creative ID`, `Template Name`, `Status`,
`Weightage`, `Created On`.

# STEP 4 — Identify the control

```bash
python3 "$SKILL_DIR/scripts/allocate_weights.py" --input /tmp/creatives.json
```

The script applies the rule. You do not pick the control.

# STEP 5 — Decompose the control

Open `/creative-manager/edit/<control_id>`. Read slot values from the DOM:

```javascript
document.querySelectorAll('input, textarea')        // slots, options, weight
document.querySelectorAll('[contenteditable="true"]') // Quill: title, subtitle
```

**Also harvest the siblings.** While you are in Console, open every OTHER
creative on this offer that uses an Image/Video template and record its asset
path. Image experiments resolve their asset from these — an asset already
configured for this exact offer, rather than one a session invented.

Write the result to `/tmp/control.json` as:

```json
{"creative_id": "", "category": "", "offer_name": "", "offer_id": "",
 "template": "", "title": "", "subtitle": "", "options": [], "skip_text": "",
 "macro_mappings": {},
 "siblings": [
   {"creative_id": "", "template": "", "status": "", "asset": ""}
 ]}
```

Omitting `siblings` makes every image experiment inapplicable, and the queue
will silently fall through to a text experiment. That is not a failure you will
notice from the output, so do the harvest.

**Never record or echo the `View Creative` href** — it carries a bearer JWT
valid about nine months.

# STEP 6 — Pull the baseline

```
fields:  Creative Id, AVG(weight), SUM(Linkout Impression), SUM(Linkout Click),
         SUM(Linkout Conversion), SUM(Linkout Offer Skipped),
         SUM(Anticipated Revenue)
filters: Offer Name SET ["<exact name>"]
```

Rows with `Creative Id: null` are an attribution gap, not a creative. Report
them separately, compute `attributed_share`, and never blend them into the
control baseline.

# STEP 7 — Compile the experiment

```bash
python3 "$SKILL_DIR/scripts/compile_variants.py" --control /tmp/control.json \
  --rules "$SKILL_DIR/rules/creative-rules.json" \
  --concluded "<comma-separated experiments already concluded on this offer>" \
  > /tmp/compiled.json
```

Get the concluded list from the repository `outcomes` and `tests` tabs.

**Also pass `--exclude` with every creative id a previous test killed or called
inconclusive.** Read those from `outcomes`. Without it the engine will happily
nominate a creative a previous test already proved catastrophic — and take its
asset too, which on an image template may be the very thing that lost.

The output names the experiment, the slot actions, the challenger count, the
weights, and the decision parameters. **All of it is binding.**

**Check `reuse_existing_creative` before building anything.** If it is populated,
a dormant creative on this offer already matches the experiment's target shape.
Activate that one and set its weight instead of creating a near-duplicate.
Verify its copy still matches the control's COPY slots first; if it has drifted,
build new. Creating a second copy of a creative the team already made is how a
creative library turns into sprawl nobody can reason about.

# STEP 8 — Fill only the REWRITE slots

For each variant, write text for slots marked `REWRITE`. Obey:

- `pattern` — the shape the title must take
- `must_include` — required elements. `amount_to_use` gives the exact figure
- `must_avoid` — forbidden content
- `constraints.max_words` / `min_words`
- `constraints.approved_benefit_verbs` — use these, not synonyms of your choosing
- `differentiation_directive` on a second challenger — the one axis on which it
  must differ from the first

Slots marked `COPY`, `INHERIT`, or `SET` are reproduced **character for
character**. Not paraphrased, not improved, not tidied. A single-attribute
experiment is only interpretable if everything else is genuinely identical.

Write `/tmp/filled.json` as `{"variants":[{"label":"V1","title":…,"subtitle":…,
"options":[…],"skip_text":…,"template":…,"macro_mappings":{}}]}`.

# STEP 9 — Verify. This gate is not optional

```bash
python3 "$SKILL_DIR/scripts/rules_check.py" --compiled /tmp/compiled.json --filled /tmp/filled.json
python3 "$SKILL_DIR/scripts/compliance_preflight.py" --input /tmp/variant.json \
  --rules "$SKILL_DIR/scripts/compliance_rules.json" \
  --copied-slots "<every slot the compiled spec marked COPY, INHERIT, SET or SET_ASSET>"
```

`--copied-slots` matters. Slots reproduced verbatim from the live control are
graded **soft**, not hard: that copy is already serving traffic, so refusing a
challenger for inheriting it blocks every test without making anything safer.
The finding is still reported, flagged `inherited_from_control`, so the control's
own problems stay visible and land on the Admin rather than on you.

Anything the session **wrote** is still graded hard. That is the whole point of
the distinction — do not pass a REWRITE slot in `--copied-slots` to get a
violation to go away.

```bash
```

Both must pass. On any violation, **rewrite the text and re-run.** Do not edit
the rules, do not pass `--demote`, do not proceed on a partial pass. Loop until
clean or give up and report — never write a blocked variant.

# STEP 10 — Write to Console

Native browser. For each variant:

1. `/creative-manager/add`
2. Select the offer: JS-click the `p-select`, set its filter input via the native
   value setter plus an `input` event, confirm exactly one match, click it
3. Select the template the compiled spec names
4. Multi-option templates start with **zero** option rows — click `Add Option`
   once per option needed
5. Title and subtitle are **Quill** editors. Setting `innerText` silently fails.
   Focus, select contents, then `document.execCommand('insertText', false, text)`,
   and confirm the `ql-blank` class has cleared before saving
6. Set `Weightage` and `Status` from the compiled weight plan
7. Write `Meta Data Tags`:

```json
{"engine":"im-creative-engine","rules_version":"1.0.0","test_id":"T-...",
 "role":"challenger","label":"V1","experiment":"dollar_amount_in_title",
 "varied_attributes":{...},"operator":"...","created":"..."}
```

8. Save, then **reload the page and confirm every field persisted**

Then set the control's `Weightage` to the compiled control weight.

**The two-gate trap:** `Weightage` and `Status` gate serving independently. Weight
10 with Status off serves nothing and looks like a null result. Write both, always.

**Coordinate clicks are unreliable in this pane.** Use JS-dispatched clicks and
`form_input` on refs.

# STEP 11 — Verify what is actually serving

```
fields: Creative Id, AVG(weight), SUM(Linkout Impression)
filters: Offer Name SET ["<exact name>"]
```

`weight` lags up to a day, so also re-read the Console form. Record
`weight_verified` once traffic appears. Do not call the test live until the
served weights match the plan.

# STEP 12 — Record

```bash
python3 "$SKILL_DIR/scripts/repo_client.py" append tests    --dicts-json '[…]'
python3 "$SKILL_DIR/scripts/repo_client.py" append variants --dicts-json '[…]'
python3 "$SKILL_DIR/scripts/repo_client.py" append audit    --dicts-json '[…]'
```

One `tests` row, one `variants` row per creative including the control, one
`audit` row per Console field changed with `from_value` and `to_value`. Include
`rules_version` so every test is traceable to the rules that produced it.

# STEP 13 — Monitor

```bash
python3 "$SKILL_DIR/scripts/sequential_test.py" --input /tmp/state.json \
  --min-impressions 2400 --min-days 7 --max-days 25 --min-lift 0.05
```

Parameters come from `decision_parameters` in the rules. The script owns the
verdict.

- **promote** — winner becomes control at the rules' `control_weight`; deposed
  control stays in the pool at `sentinel_weight` as a sentinel
- **kill** — weight 0, Status Inactive
- **inconclusive** — same as kill, recorded as inconclusive
- **continue** — change nothing, append an `audit` row

Append to `outcomes` on every pass, `continue` included.

# STEP 14 — Report

Summarise: experiment run, variants live, weights configured and verified,
attributed share, expected read date. State the `rules_version` used.

---

## Facts that will bite you

- **`Linkout Offerwise Data with creative ID`** (`7bb01404-…`) is frozen at May
  2023 and still queryable. Use `ds_rm_linkout_analytics`.
- **Quill silently discards `innerText`.** Use `execCommand`, verify `ql-blank`.
- **Console's search box ignores typed input.** Use `form_input`.
- **Never write to Google Sheets through the browser** — it reports success and
  saves nothing. Only `repo_client.py`.
- **Single-creative offers are normal** (582 of 1,168). No comparative history;
  the first test sets the baseline.
- **A challenger at zero impressions after 24 hours** is the two-gate trap, not
  a result.
