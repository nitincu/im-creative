# im-creative-engine

Champion/challenger creative testing for Interest Media **Linkout** offers.

The control holds 80% of serving weight, challengers share 20%, winners are
promoted by a deterministic test, and every outcome is recorded centrally.

## Start here

**[SETUP.md](SETUP.md)** — about 15 minutes. Read it before anything else.

## How to use it

Name an offer, in Claude:

> test creatives on RH - Merit Platinum $0.75 CPA

The engine resolves the offer, reads its Console state, identifies the control,
pulls the baseline, selects the next queued experiment, builds variants inside
the rules, verifies them, writes them live at an 80/20 split, and records
everything.

To look in on a running test:

> check the creative test on RH - Merit Platinum $0.75 CPA

## What this is

A fixed workflow. Which experiment runs, what a creative may look like, how
weights are set, and when a winner is called are all decided centrally and
encoded in `rules/creative-rules.json`.

**The thinking is done. Your session executes it.** That is what keeps results
comparable across the whole org — every test everywhere varies one attribute
against a control chosen the same way and judged by the same maths.

Three consequences worth knowing up front:

- **It will not invent an experiment.** If nothing in the queue applies to an
  offer, it stops and tells you to ask the Admin.
- **It will not take creative direction.** "Make it punchier" gets declined.
- **It will not skip a failed check.** A variant that breaks a rule is rewritten,
  not waved through.

None of that stops you taking a creative live. It constrains what the creative
looks like, not your ability to ship it.

## What's in here

| Path | Purpose |
|---|---|
| `SETUP.md` | Install and verification steps |
| `skills/creative-testing-engine/SKILL.md` | The workflow, 8 steps |
| `rules/creative-rules.json` | What a creative may look like. Do not edit |
| `agents/offer-recon.md` | Read-only offer diagnosis |
| `agents/repository-keeper.md` | Monitoring and promote/kill |
| `references/console-navigation.md` | Verified Console selectors and traps |
| `references/tableau-fields.md` | Verified datasource and field names |
| `references/repository-schema.md` | What gets recorded, and where |

Judgment is delegated to the model. Arithmetic is not:

| Script | Owns |
|---|---|
| `sequential_test.py` | promote / kill / continue |
| `allocate_weights.py` | control identification and the 80/20 split |
| `compile_variants.py` | which experiment runs and which slots change |
| `rules_check.py` | whether a variant is allowed to exist |
| `compliance_preflight.py` | copy violations |
| `repo_client.py` | all repository reads and writes |

## Three traps that will cost you a test

- **`Weightage` and `Status` gate serving independently.** Weight 10 with Status
  off serves nothing and looks like a null result. Always write both.
- **A datasource named `Linkout Offerwise Data with creative ID` is frozen at
  May 2023** and still queryable. The engine uses `ds_rm_linkout_analytics`.
- **Rows with no `Creative Id` are an attribution gap, not a creative.** Never
  blend them into a control baseline.

## Editing the rules

Don't. `rules/creative-rules.json` is set centrally; a local edit desynchronises
your results from everyone else's and will be overwritten on the next update.
Rules changes go through the Admin.

## Support

Include the offer name, the `test_id` if there is one, and the output of the
`health` command from SETUP.md step 7.
