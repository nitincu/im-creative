#!/usr/bin/env python3
"""Control identification and 80/20 weight allocation for a Linkout offer.

Two rules, both from the operator spec:
  1. The control is the creative with the largest Weightage among ACTIVE
     creatives. Ties break to the oldest Created On.
  2. The control holds 80. Challengers perpetually share the remaining 20.

CRITICAL -- the two-gate trap. In Console, `Weightage` and `Status` gate serving
INDEPENDENTLY. A challenger given weight 10 with Status off serves nothing at
all, and the test returns zero data that looks like a null result rather than a
misconfiguration. Every plan this script emits therefore names BOTH fields for
every creative it touches, and every write must be verified afterwards against
the `weight` measure in ds_rm_linkout_analytics.

Usage
  allocate_weights.py --input creatives.json [--challengers 7140,5059]
  cat creatives.json | allocate_weights.py

Input shape
  {"offer_id":"...","offer_name":"...",
   "creatives":[{"creative_id":"5060","status":"Active","weight":100,
                 "created_on":"2025-09-30 14:37:20","template":"..."}]}
"""

import argparse
import json
import sys

CONTROL_WEIGHT = 80
TEST_POOL = 20
MAX_CHALLENGERS = 3

# Integer splits of the 20% pool. Sums are exact; no rounding drift.
SPLITS = {0: [], 1: [20], 2: [10, 10], 3: [7, 7, 6]}


def _norm_status(value):
    return str(value or "").strip().lower()


def is_active(creative):
    return _norm_status(creative.get("status")) in ("active", "1", "true", "on")


def pick_control(creatives):
    """Largest weight among Active; ties to oldest created_on."""
    active = [c for c in creatives if is_active(c)]
    if not active:
        return None
    return sorted(
        active,
        key=lambda c: (-int(c.get("weight") or 0), str(c.get("created_on") or "")),
    )[0]


def plan(data, challenger_ids=None, allow_auto=False):
    creatives = data.get("creatives") or []
    if not creatives:
        return {"ok": False, "error": "no creatives supplied"}

    by_id = {str(c["creative_id"]): c for c in creatives}
    control = pick_control(creatives)

    warnings = []
    if control is None:
        return {
            "ok": False,
            "error": "no ACTIVE creative on this offer, so there is no control",
            "remedy": "activate the intended control in Console first, then rerun",
        }

    control_id = str(control["creative_id"])

    # Cold start: 582 of 1,168 Linkout offers carry exactly one creative, so
    # this is the common case, not the exception.
    if len(creatives) == 1:
        warnings.append(
            "single-creative offer: no comparative history exists. The first "
            "test establishes the baseline rather than beating a known one.")

    if challenger_ids:
        requested = [str(c).strip() for c in challenger_ids if str(c).strip()]
        unknown = [c for c in requested if c not in by_id]
        if unknown:
            return {"ok": False,
                    "error": f"challenger ids not on this offer: {unknown}"}
        if control_id in requested:
            return {"ok": False,
                    "error": f"creative {control_id} is the control and cannot "
                             "also be a challenger"}
        chosen = requested[:MAX_CHALLENGERS]
        if len(requested) > MAX_CHALLENGERS:
            warnings.append(
                f"{len(requested)} challengers requested; capped at "
                f"{MAX_CHALLENGERS}. Dropped: {requested[MAX_CHALLENGERS:]}. "
                "More arms means less power per arm and a longer read.")
    elif allow_auto:
        chosen = [str(c["creative_id"]) for c in creatives
                  if str(c["creative_id"]) != control_id][:MAX_CHALLENGERS]
        warnings.append(
            "challengers auto-selected. This picks dormant creatives with no "
            "regard for whether a previous test already killed them, which is "
            "how a proven loser gets resurrected. Pass --challengers explicitly.")
    else:
        return {"ok": False,
                "error": "no challengers given",
                "control_creative_id": control_id,
                "remedy": ("pass --challengers with the ids to test. They come from "
                           "compile_variants (new variants) or from its "
                           "reuse_existing_creative flag -- never from 'whatever "
                           "else is on the offer', because that resurrects "
                           "creatives previous tests already killed."),
                "warnings": warnings}

    split = SPLITS[len(chosen)]
    if not chosen:
        warnings.append(
            "no challengers: control goes to 100 and no test runs. Generate "
            "variants before allocating, or the 20% test pool sits idle.")

    writes = []
    target = {control_id: CONTROL_WEIGHT if chosen else 100}
    for cid, w in zip(chosen, split):
        target[cid] = w

    for creative in creatives:
        cid = str(creative["creative_id"])
        now_w = int(creative.get("weight") or 0)
        now_active = is_active(creative)

        if cid in target:
            want_w, want_active = target[cid], True
            role = "control" if cid == control_id else "challenger"
        else:
            # Not in this test. Park it: weight 0 and inactive, so it cannot
            # quietly absorb traffic and dilute the comparison.
            want_w, want_active = 0, False
            role = "parked"

        if now_w != want_w or now_active != want_active:
            writes.append({
                "creative_id": cid, "role": role,
                "set_weight": want_w,
                "set_status": "Active" if want_active else "Inactive",
                "from_weight": now_w,
                "from_status": "Active" if now_active else "Inactive",
                "both_fields_required": True,
            })

    total = sum(target.values())
    if total != 100:
        warnings.append(f"target weights sum to {total}, not 100 -- investigate")

    return {
        "ok": True,
        "offer_id": data.get("offer_id"),
        "offer_name": data.get("offer_name"),
        "control_creative_id": control_id,
        "control_selection_basis":
            f"largest Weightage ({control.get('weight')}) among Active"
            + (", oldest Created On on tie" if _tie(creatives, control) else ""),
        "challenger_creative_ids": chosen,
        "target_weights": target,
        "weights_sum": total,
        "writes_required": writes,
        "no_change_needed": not writes,
        "verification":
            "After writing, read SUM(weight) by Creative Id from "
            "ds_rm_linkout_analytics and confirm it matches target_weights. "
            "Do not trust the Console form alone.",
        "warnings": warnings,
    }


def _tie(creatives, control):
    top = int(control.get("weight") or 0)
    return sum(1 for c in creatives
               if is_active(c) and int(c.get("weight") or 0) == top) > 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    ap.add_argument("--challengers",
                    help="comma-separated creative ids to use as challengers")
    ap.add_argument("--allow-auto-challengers", action="store_true",
                    help="pick dormant creatives automatically. Unsafe: ignores "
                         "whether a previous test already killed them.")
    a = ap.parse_args()

    raw = open(a.input).read() if a.input else sys.stdin.read()
    ids = a.challengers.split(",") if a.challengers else None
    res = plan(json.loads(raw), ids, a.allow_auto_challengers)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
