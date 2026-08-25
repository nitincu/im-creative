#!/usr/bin/env python3
"""Verify filled variants against the compiled spec and the engine rules.

This is what makes the workflow rule-based instead of trust-based. The session
writes text; this decides whether that text is allowed to exist. A non-zero exit
means the variant may not be written to Console.

COPY slots are compared character for character against the control. That is
deliberate: a single-attribute experiment is only interpretable if every other
slot is genuinely untouched, and "close enough" silently destroys attribution.

Usage
  rules_check.py --compiled compiled.json --filled filled.json
                 [--rules rules/creative-rules.json]
"""

import argparse
import json
import re
import sys

EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF✅⬇️]")
URGENCY = re.compile(r"\b(now|today|instant|instantly|hurry|limited|tonight|"
                     r"deadline|expires|last chance|act fast)\b", re.I)
ABSOLUTE = re.compile(r"\b(guarantee(d|s)?|pre-?approved|100%\s*approv\w*|"
                      r"risk[- ]free|everyone qualifies)\b", re.I)
DOLLAR = re.compile(r"\$\s?\d")
MACRO = re.compile(r"\{\{[^}]+\}\}")


AMOUNT_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")


def _check_amount(slot, text, sspec):
    """Every figure in the copy must be the resolved amount or a documented
    derivation of it.

    Without this, "recipe requires a dollar amount" was satisfied by ANY dollar
    amount, so a session could invent a figure and the gate would pass it. A
    fabricated number in a live ad is a truthfulness problem, not a style one.

    Derivations allowed, because the second challenger may reframe the same value:
      * the amount itself
      * monthly  = amount / 12   (+/- 1 for rounding)
      * annual   = amount * 12
    """
    info = sspec.get("amount_to_use") or {}
    allowed_base = info.get("amount")
    if allowed_base is None:
        return [{"slot": slot, "code": "amount_not_resolvable",
                 "detail": "recipe requires a dollar amount but none could be "
                           "resolved from the control or the Admin's offer_amounts",
                 "fix": "this experiment should not have been selected; report it"}]

    found = [f.replace(",", "") for f in AMOUNT_RE.findall(text)]
    monthly = allowed_base / 12.0
    bad = []
    for raw in found:
        try:
            n = float(raw)
        except ValueError:
            continue
        ok = (abs(n - allowed_base) < 0.01
              or abs(n - monthly) <= 1.0
              or abs(n - allowed_base * 12) < 0.01)
        if not ok:
            bad.append(raw)
    if bad:
        return [{"slot": slot, "code": "fabricated_amount",
                 "detail": f"figure(s) {bad} do not match the resolved amount "
                           f"{allowed_base} (source: {info.get('source')})",
                 "allowed": [allowed_base, round(monthly), allowed_base * 12],
                 "fix": "use the resolved amount, or its monthly or annual "
                        "equivalent. Do not introduce a different number.",
                 "why_it_matters": "an invented figure in live copy is a "
                                   "truthfulness problem, not a style choice"}]
    return []


def check_variant(spec, filled, rules):
    v = []
    hc = rules["hard_constraints"]
    forbidden = [w.lower() for w in rules["approved_vocabulary"]["forbidden_words"]]
    slots = spec["slots"]

    visible = " ".join(
        [filled.get("title") or "", filled.get("subtitle") or ""]
        + [o for o in (filled.get("options") or []) if o])

    for slot, sspec in slots.items():
        action = sspec.get("action")
        got = filled.get(slot)

        if action == "SET_ASSET":
            if not sspec.get("value"):
                v.append({"slot": slot, "code": "asset_not_resolvable",
                          "detail": "image experiment with no asset from the Admin's "
                                    "offer_assets map",
                          "fix": "this experiment should not have been selected"})
            elif filled.get(slot) and filled.get(slot) != sspec.get("value"):
                v.append({"slot": slot, "code": "asset_substituted",
                          "detail": "a different asset was used",
                          "expected": sspec.get("value"), "got": filled.get(slot)})
            continue

        if action in ("COPY", "INHERIT", "SET"):
            want = sspec.get("value")
            if action == "INHERIT" and slot == "template":
                got = filled.get("template")
            if isinstance(want, list):
                same = [str(x) for x in (got or [])] == [str(x) for x in want]
            else:
                same = (str(got or "") == str(want or ""))
            if not same:
                v.append({"slot": slot, "code": f"{action.lower()}_slot_modified",
                          "detail": f"{action} slot was changed",
                          "expected": want, "got": got,
                          "why_it_matters": "a modified control slot destroys "
                                            "single-attribute attribution"})
            continue

        if action == "REWRITE":
            if not got:
                v.append({"slot": slot, "code": "rewrite_slot_empty",
                          "detail": "slot marked REWRITE was left empty"})
                continue
            c = sspec.get("constraints", {})
            text = " ".join(got) if isinstance(got, list) else str(got)

            if slot == "title":
                wc = len(text.split())
                if c.get("max_words") and wc > c["max_words"]:
                    v.append({"slot": slot, "code": "too_long",
                              "detail": f"{wc} words, max {c['max_words']}"})
                if c.get("min_words") and wc < c["min_words"]:
                    v.append({"slot": slot, "code": "too_short",
                              "detail": f"{wc} words, min {c['min_words']}"})
            if c.get("forbid_emoji") and EMOJI.search(text):
                v.append({"slot": slot, "code": "emoji_present",
                          "detail": "emoji not permitted in this slot"})
            if c.get("forbid_urgency"):
                m = URGENCY.search(text)
                if m:
                    v.append({"slot": slot, "code": "urgency_word",
                              "detail": f"urgency term {m.group(0)!r} not permitted"})
            for w in forbidden:
                if w in text.lower():
                    v.append({"slot": slot, "code": "forbidden_word",
                              "detail": f"forbidden term {w!r}"})
            if ABSOLUTE.search(text):
                v.append({"slot": slot, "code": "absolute_claim",
                          "detail": "absolute-certainty claim"})

            requires_amount = any("dollar amount" in r.lower()
                                  for r in sspec.get("must_include", []))
            if requires_amount and not DOLLAR.search(text):
                v.append({"slot": slot, "code": "missing_required_element",
                          "detail": "recipe requires an explicit dollar amount; "
                                    "none present"})
            # Check any figure that IS present, required or not.
            if DOLLAR.search(text):
                v += _check_amount(slot, text, sspec)

            if any("benefit verb" in r.lower() for r in sspec.get("must_include", [])):
                verbs = c.get("approved_benefit_verbs", [])
                if not any(re.search(r"\b" + re.escape(b) + r"\w*\b", text, re.I)
                           for b in verbs):
                    v.append({"slot": slot, "code": "missing_required_element",
                              "detail": "no approved benefit verb present",
                              "approved": verbs})

            if slot == "options":
                opts = got if isinstance(got, list) else [got]
                opts = [o for o in opts if o]
                want_n = sspec.get("count")
                if want_n and isinstance(want_n, int) and len(opts) != want_n:
                    v.append({"slot": slot, "code": "wrong_option_count",
                              "detail": f"{len(opts)} options, recipe wants {want_n}"})
                if not (hc["option_count_min"] <= len(opts) <= hc["option_count_max"]):
                    v.append({"slot": slot, "code": "option_count_out_of_range",
                              "detail": f"{len(opts)} outside "
                                        f"{hc['option_count_min']}-{hc['option_count_max']}"})
                low = [o.strip().lower() for o in opts]
                if hc["require_distinct_options"] and len(set(low)) != len(low):
                    v.append({"slot": slot, "code": "duplicate_options",
                              "detail": "option text repeats"})
                gen = [o for o in low if o in
                       [g.lower() for g in hc["forbid_generic_option_text"]]]
                if gen:
                    v.append({"slot": slot, "code": "generic_option_text",
                              "detail": f"generic CTA: {gen}"})

    # A recipe that switches template while copying N options can ask for more
    # options than the target holds. That produces a creative nobody can build,
    # and the COPY-match check alone will not notice.
    cap = rules.get("template_capacity") or {}
    tpl_spec = slots.get("template") or {}
    eff_tpl = filled.get("template") or tpl_spec.get("value")
    if eff_tpl and eff_tpl in cap:
        limit = cap[eff_tpl]
        n_opts = len([o for o in (filled.get("options") or []) if o])
        if limit == 0 and n_opts:
            v.append({"slot": "template", "code": "template_takes_no_options",
                      "detail": f"{eff_tpl!r} holds no option list, {n_opts} supplied"})
        elif limit and n_opts > limit:
            v.append({"slot": "template", "code": "too_many_options_for_template",
                      "detail": f"{eff_tpl!r} holds at most {limit} option(s), "
                                f"{n_opts} supplied",
                      "fix": "reduce the options, or target a template that fits",
                      "why_it_matters": "this combination cannot be built in Console"})

    if hc.get("require_all_macros_mapped"):
        mapped = set((filled.get("macro_mappings") or {}).keys())
        for tok in set(MACRO.findall(visible)):
            if tok not in mapped:
                v.append({"slot": "macro_mappings", "code": "unmapped_macro",
                          "detail": f"{tok} used but not mapped"})
    return v


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--compiled", required=True)
    ap.add_argument("--filled", required=True)
    ap.add_argument("--rules", default="rules/creative-rules.json")
    a = ap.parse_args()

    compiled = json.load(open(a.compiled))
    filled = json.load(open(a.filled))
    rules = json.load(open(a.rules))
    by_label = {v["label"]: v for v in compiled["variants"]}

    results, all_ok = [], True
    for f in filled["variants"]:
        label = f.get("label")
        spec = by_label.get(label)
        if not spec:
            results.append({"label": label, "may_write": False,
                            "violations": [{"code": "unknown_variant_label",
                                            "detail": f"{label} not in compiled spec"}]})
            all_ok = False
            continue
        viol = check_variant(spec, f, rules)
        if viol:
            all_ok = False
        results.append({"label": label, "may_write": not viol,
                        "violation_count": len(viol), "violations": viol})

    print(json.dumps({
        "ok": all_ok,
        "rules_version": rules["version"],
        "experiment": compiled["selected_experiment"],
        "results": results,
        "verdict": ("all variants may be written to Console" if all_ok else
                    "BLOCKED. Fix the violations and re-run. Do not write to "
                    "Console, and do not relax the rules to make this pass.")
    }, indent=2))
    sys.exit(0 if all_ok else 4)


if __name__ == "__main__":
    main()
