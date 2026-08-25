#!/usr/bin/env python3
"""Compile the next experiment for an offer into an exact, fillable spec.

This removes interpretation from the session. It decides WHICH experiment runs,
WHICH slots change, and WHAT constraints apply. The session's only remaining job
is to write text into slots marked "rewrite", inside stated constraints, and
that output is then verified mechanically by rules_check.py.

The session does not choose the experiment, the slot set, the challenger count,
the weights, or the decision parameters. Those come from rules/creative-rules.json.

Usage
  compile_variants.py --control control.json --rules rules/creative-rules.json
                      [--concluded dollar_amount_in_title,benefit_hook]
"""

import argparse
import json
import re
import sys

BENEFIT = re.compile(r"\b(save|saving|savings|lower|cheaper|discount|free|earn|"
                     r"qualify|compare|unlock)\b", re.I)
DOLLAR = re.compile(r"\$\s?\d")
INTENT_PHRASING = re.compile(r"\b(cheapest|lowest|show me|quotes?|coverage|"
                             r"compare|looking for|i want|i need)\b", re.I)


def predicates(control, rules=None):
    title = control.get("title") or ""
    template = control.get("template") or ""
    options = [o for o in (control.get("options") or []) if o]
    intent_like = sum(1 for o in options if INTENT_PHRASING.search(o))
    return {
        "control_title_has_dollar_amount": bool(DOLLAR.search(title)),
        "control_title_has_benefit_word": bool(BENEFIT.search(title)),
        "control_template_is_image": "image" in template.lower(),
        "control_options_describe_user_state": intent_like < max(1, len(options) // 2),
        "control_option_count": len(options),
        "control_has_resolvable_amount":
            largest_dollar(control, rules)["amount"] is not None,
    }


def applies(entry, preds):
    cond = entry.get("applies_when") or {}
    for key, want in cond.items():
        if key == "control_option_count_gte":
            if preds["control_option_count"] < want:
                return False, f"option count {preds['control_option_count']} < {want}"
        else:
            have = preds.get(key)
            if have != want:
                return False, f"{key}={have}, needs {want}"
    return True, "applies"


def largest_dollar(control, rules=None):
    """Resolve the figure the dollar-amount experiment may use.

    Order: control options, subtitle, title, then the Admin's offer_amounts map.
    Returns amount None when nothing resolves -- which makes the experiment
    inapplicable rather than licensing an invented number.
    """
    for field in ("options", "subtitle", "title"):
        vals = control.get(field)
        blob = " ".join(vals) if isinstance(vals, list) else (vals or "")
        found = re.findall(r"\$\s?([\d,]+)", blob)
        if found:
            nums = sorted(int(f.replace(",", "")) for f in found)
            return {"amount": nums[-1], "source": field, "all_found": nums}

    amounts = ((rules or {}).get("offer_amounts") or {}).get("by_offer_name") or {}
    for key in (control.get("offer_name"), control.get("offer_id")):
        if key and key in amounts:
            try:
                return {"amount": int(amounts[key]), "source": "admin_offer_amounts",
                        "all_found": [int(amounts[key])]}
            except (TypeError, ValueError):
                pass
    return {"amount": None, "source": None, "all_found": []}


def resolve_slot(slot, spec, control, rules, amount_info):
    action = spec.get("action")
    if action == "copy_verbatim_from_control":
        return {"action": "COPY", "value": control.get(slot),
                "instruction": "use exactly this, character for character"}
    if action == "inherit_from_control":
        return {"action": "INHERIT", "value": control.get("template")}
    if action == "set":
        return {"action": "SET", "value": spec.get("value")}
    if action == "reduce_to_single":
        return {"action": "REWRITE", "count": 1, "rule": spec.get("rule"),
                "constraints": {
                    "forbid_generic": rules["hard_constraints"]["forbid_generic_option_text"],
                    "forbidden_words": rules["approved_vocabulary"]["forbidden_words"]}}
    if action == "rewrite":
        hc = rules["hard_constraints"]
        out = {"action": "REWRITE",
               "must_include": spec.get("must_include", []),
               "must_avoid": spec.get("must_avoid", []),
               "pattern": spec.get("pattern"),
               "rule": spec.get("rule"),
               "count": spec.get("count"),
               "constraints": {
                   "max_words": spec.get("max_words", hc["title_max_words"]),
                   "min_words": hc["title_min_words"],
                   "forbid_emoji": hc["title_forbid_emoji"],
                   "forbid_urgency": hc["forbid_urgency_words"],
                   "forbidden_words": rules["approved_vocabulary"]["forbidden_words"],
                   "approved_benefit_verbs": rules["approved_vocabulary"]["benefit_verbs"]}}
        if "an explicit dollar amount" in spec.get("must_include", []):
            out["amount_to_use"] = amount_info
        return {k: v for k, v in out.items() if v not in (None, [], {})}
    return {"action": "UNKNOWN:" + str(action)}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--control", required=True)
    ap.add_argument("--rules", default="rules/creative-rules.json")
    ap.add_argument("--concluded", default="",
                    help="comma-separated experiment names already concluded")
    a = ap.parse_args()

    control = json.load(open(a.control))
    rules = json.load(open(a.rules))
    done = {x.strip() for x in a.concluded.split(",") if x.strip()}
    preds = predicates(control, rules)

    evaluated, chosen = [], None
    for entry in sorted(rules["test_queue"]["entries"], key=lambda e: e["priority"]):
        if entry["experiment"] in done:
            evaluated.append({"priority": entry["priority"],
                              "experiment": entry["experiment"],
                              "verdict": "skipped: already concluded"})
            continue
        ok, why = applies(entry, preds)
        if not ok:
            verdict = "not applicable: " + why
        elif chosen is None:
            verdict = "SELECTED"
            chosen = entry
        else:
            verdict = "applicable, queued behind priority %d" % chosen["priority"]
        evaluated.append({"priority": entry["priority"],
                          "experiment": entry["experiment"], "verdict": verdict})

    if chosen is None:
        print(json.dumps({
            "ok": False,
            "error": "no queue entry applies to this control",
            "predicates": preds, "queue_evaluation": evaluated,
            "action": "report to the Admin. Do not improvise an experiment.",
            "likely_cause": (
                "If dollar_amount_in_title was skipped for a missing amount, the "
                "control states no figure and this offer has no entry in the "
                "Admin's offer_amounts map. The Admin either adds one or the queue "
                "needs an experiment that applies to this offer."
            )
        }, indent=2))
        sys.exit(2)

    amount_info = largest_dollar(control, rules)
    dp = rules["decision_parameters"]
    n = min(chosen.get("n_challengers", 1), rules["hard_constraints"]["max_challengers"])
    pool = dp["test_pool"]
    split = ([pool] if n == 1 else
             [pool // 2] * 2 if n == 2 else
             [7, 7, 6])

    slots = {s: resolve_slot(s, spec, control, rules, amount_info)
             for s, spec in chosen["recipe"].items()}

    variants = []
    for i in range(n):
        v = {"label": f"V{i+1}", "slots": json.loads(json.dumps(slots)),
             "weight": split[i]}
        if i == 1 and chosen.get("second_challenger"):
            v["differentiation_directive"] = chosen["second_challenger"]
        variants.append(v)

    print(json.dumps({
        "ok": True,
        "rules_version": rules["version"],
        "predicates": preds,
        "queue_evaluation": evaluated,
        "selected_experiment": chosen["experiment"],
        "varied_attribute": chosen["varied_attribute"],
        "target_mde": chosen.get("target_mde", dp.get("min_lift")),
        "weight_plan": {"control": dp["control_weight"],
                        "challengers": split, "sums_to": dp["control_weight"] + sum(split)},
        "decision_parameters": dp,
        "variants": variants,
        "session_may_only": ["fill slots marked REWRITE, inside the stated constraints"],
        "session_may_not": ["choose a different experiment", "change slot actions",
                            "change challenger count", "change weights",
                            "change decision parameters",
                            "edit rules/creative-rules.json"]
    }, indent=2))


if __name__ == "__main__":
    main()
