#!/usr/bin/env python3
"""Control identification and share-based weight allocation for a Linkout offer.

WEIGHTS ARE RELATIVE, NOT PERCENTAGES. This is the single most important fact
about serving. A creative's share of traffic is its weight divided by the sum of
weights across all ACTIVE creatives on the offer. Weights need not sum to 100
and routinely do not.

  one active creative        -> it takes 100% whatever its weight says
  weights 50 and 5           -> 50/55 = 90.9% and 5/55 = 9.1%
  weights 80, 10, 10         -> 80% / 10% / 10%
  weights 80, 10, 10, 5      -> 76.2%. The control has fallen below its floor.

Two rules follow, and the second is why this script computes shares rather than
checking that numbers add to 100:

  1. The control's share must never fall below --min-control-share (default 0.80).
  2. Any creative left Active outside the plan dilutes the control. So the pool
     of non-control weight is a BUDGET derived from the floor, shared by
     challengers and any sentinel, not a fixed 20.

Inactive creatives take no traffic regardless of weight, so a weight-50 creative
that is switched off is irrelevant to shares. Status and Weightage gate serving
independently -- see references/console-navigation.md.

Usage
  allocate_weights.py --input creatives.json --challengers 7455,7456
                      [--sentinel 4557] [--keep-active 3093=5]
                      [--min-control-share 0.80] [--control-weight 80]
"""

import argparse
import json
import sys

CONTROL_WEIGHT = 80
MAX_CHALLENGERS = 3
MIN_CONTROL_SHARE = 0.80
SENTINEL_INTENT = 3          # relative intent, not a final weight
CHALLENGER_INTENT = {0: [], 1: [20], 2: [10, 10], 3: [7, 7, 6]}


def _norm_status(v):
    return str(v or "").strip().lower()


def is_active(c):
    return _norm_status(c.get("status")) in ("active", "1", "true", "on")


def shares(weights):
    """Share of traffic per creative. Weights are relative; this is the only
    number that describes what actually serves."""
    total = sum(weights.values())
    if total <= 0:
        return {}, 0
    return {k: v / total for k, v in weights.items()}, total


def pick_control(creatives):
    active = [c for c in creatives if is_active(c)]
    if not active:
        return None
    return sorted(active,
                  key=lambda c: (-int(c.get("weight") or 0),
                                 str(c.get("created_on") or "")))[0]


def _tie(creatives, control):
    top = int(control.get("weight") or 0)
    return sum(1 for c in creatives
               if is_active(c) and int(c.get("weight") or 0) == top) > 1


def allocate(control_id, members, control_weight, min_share):
    """Weights that hold the control at or above min_share.

    members: list of (creative_id, relative_intent). The pool budget comes from
    the floor itself -- at 0.80 the control's 80 permits 20 of non-control weight
    in total, however many creatives share it.
    """
    weights = {control_id: control_weight}
    intent_total = sum(w for _, w in members)
    if intent_total <= 0:
        return weights

    budget = control_weight * (1 - min_share) / min_share
    for cid, intent in members:
        weights[cid] = max(1, int(round(budget * intent / intent_total)))

    # Rounding, and the max(1,...) floor for tiny intents, can nudge the control
    # under. Raise the control until the floor genuinely holds.
    guard = 0
    while True:
        s, _ = shares(weights)
        if s.get(control_id, 0) >= min_share - 1e-9 or guard > 500:
            break
        weights[control_id] += 1
        guard += 1
    return weights


def plan(data, challenger_ids=None, allow_auto=False, sentinel=None,
         keep_active=None, control_weight=CONTROL_WEIGHT,
         min_share=MIN_CONTROL_SHARE):
    creatives = data.get("creatives") or []
    if not creatives:
        return {"ok": False, "error": "no creatives supplied"}

    by_id = {str(c["creative_id"]): c for c in creatives}
    warnings = []
    control = pick_control(creatives)
    if control is None:
        return {"ok": False,
                "error": "no ACTIVE creative on this offer, so there is no control",
                "remedy": "activate the intended control in Console first"}
    control_id = str(control["creative_id"])

    # What is serving right now.
    current_active = {str(c["creative_id"]): int(c.get("weight") or 0)
                      for c in creatives if is_active(c)}
    current_shares, current_total = shares(current_active)

    if len(current_active) == 1:
        warnings.append(
            f"only one active creative ({control_id}), so its weight of "
            f"{current_active.get(control_id)} is irrelevant -- it takes 100% "
            "either way. Weight starts mattering the moment a second creative "
            "goes Active.")

    if len(creatives) == 1:
        warnings.append("single-creative offer: no comparative history exists. "
                        "The first test establishes the baseline.")

    # Challengers
    if challenger_ids:
        requested = [str(c).strip() for c in challenger_ids if str(c).strip()]
        unknown = [c for c in requested if c not in by_id]
        if unknown:
            return {"ok": False, "error": f"challenger ids not on this offer: {unknown}"}
        if control_id in requested:
            return {"ok": False,
                    "error": f"creative {control_id} is the control and cannot "
                             "also be a challenger"}
        chosen = requested[:MAX_CHALLENGERS]
        if len(requested) > MAX_CHALLENGERS:
            warnings.append(f"{len(requested)} challengers requested, capped at "
                            f"{MAX_CHALLENGERS}. Dropped: "
                            f"{requested[MAX_CHALLENGERS:]}. More arms means less "
                            "power per arm and a longer read.")
    elif allow_auto:
        chosen = [str(c["creative_id"]) for c in creatives
                  if str(c["creative_id"]) != control_id][:MAX_CHALLENGERS]
        warnings.append(
            "challengers auto-selected. This picks dormant creatives with no "
            "regard for whether a previous test already killed them, which is how "
            "a proven loser gets resurrected. Pass --challengers explicitly.")
    else:
        return {"ok": False, "error": "no challengers given",
                "control_creative_id": control_id,
                "current_shares": {k: round(v, 4) for k, v in current_shares.items()},
                "remedy": ("pass --challengers with the ids to test. They come from "
                           "the creatives you just built, or from compile_variants' "
                           "reuse_existing_creative flag -- never from 'whatever "
                           "else is on the offer'."),
                "warnings": warnings}

    # Pool members: challengers, then any sentinel, then anything held Active.
    intents = CHALLENGER_INTENT.get(len(chosen), [])
    members = list(zip(chosen, intents))
    if sentinel:
        sentinel = str(sentinel)
        if sentinel == control_id:
            return {"ok": False, "error": "the sentinel cannot be the control"}
        if sentinel in chosen:
            return {"ok": False, "error": "the sentinel cannot also be a challenger"}
        if sentinel not in by_id:
            return {"ok": False, "error": f"sentinel {sentinel} is not on this offer"}
        members.append((sentinel, SENTINEL_INTENT))
    keep_active = keep_active or {}
    for cid, w in keep_active.items():
        if cid in (control_id, sentinel) or cid in chosen:
            continue
        if cid not in by_id:
            return {"ok": False, "error": f"keep-active id {cid} is not on this offer"}
        members.append((cid, max(1, int(w))))
        warnings.append(
            f"creative {cid} is held Active outside the test. It dilutes the "
            "control, so the pool was rebalanced to protect the floor. Park it "
            "unless it is there for a reason.")

    if not chosen:
        warnings.append("no challengers: the control serves alone and no test runs.")

    target = allocate(control_id, members, control_weight, min_share)
    target_shares, target_total = shares(target)

    keep_ids = set(target)
    writes = []
    for creative in creatives:
        cid = str(creative["creative_id"])
        now_w = int(creative.get("weight") or 0)
        now_act = is_active(creative)
        if cid in keep_ids:
            want_w, want_act = target[cid], True
            role = ("control" if cid == control_id else
                    "sentinel" if cid == sentinel else
                    "held_active" if cid in keep_active else "challenger")
        else:
            want_w, want_act, role = 0, False, "parked"
        if now_w != want_w or now_act != want_act:
            writes.append({"creative_id": cid, "role": role,
                           "set_weight": want_w,
                           "set_status": "Active" if want_act else "Inactive",
                           "from_weight": now_w,
                           "from_status": "Active" if now_act else "Inactive",
                           "both_fields_required": True})

    control_share = target_shares.get(control_id, 0)
    floor_ok = control_share >= min_share - 1e-9
    if not floor_ok:
        warnings.append(f"control share {control_share:.1%} is below the "
                        f"{min_share:.0%} floor and could not be corrected")

    return {
        "ok": floor_ok,
        "offer_id": data.get("offer_id"),
        "offer_name": data.get("offer_name"),
        "control_creative_id": control_id,
        "control_selection_basis":
            f"largest Weightage ({control.get('weight')}) among Active"
            + (", oldest Created On on tie" if _tie(creatives, control) else ""),
        "challenger_creative_ids": chosen,
        "sentinel_creative_id": sentinel,
        "weights_are_relative": True,
        "current": {"active_weights": current_active,
                    "weight_total": current_total,
                    "shares": {k: round(v, 4) for k, v in current_shares.items()}},
        "target": {"weights": target,
                   "weight_total": target_total,
                   "shares": {k: round(v, 4) for k, v in target_shares.items()}},
        "control_share": round(control_share, 4),
        "min_control_share": min_share,
        "floor_respected": floor_ok,
        "writes_required": writes,
        "no_change_needed": not writes,
        "verification":
            "After writing, read AVG(weight) by Creative Id from "
            "ds_rm_linkout_analytics for the ACTIVE creatives, recompute "
            "share = weight / sum(weights), and confirm the control's share "
            "matches. Comparing raw weights is not enough -- weights are "
            "relative, so a stray Active creative changes every share without "
            "changing any weight you wrote.",
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    ap.add_argument("--challengers")
    ap.add_argument("--sentinel")
    ap.add_argument("--keep-active", default="",
                    help="comma-separated id=weight for creatives that must stay "
                         "Active outside the test")
    ap.add_argument("--allow-auto-challengers", action="store_true")
    ap.add_argument("--control-weight", type=int, default=CONTROL_WEIGHT)
    ap.add_argument("--min-control-share", type=float, default=MIN_CONTROL_SHARE)
    a = ap.parse_args()

    raw = open(a.input).read() if a.input else sys.stdin.read()
    ids = a.challengers.split(",") if a.challengers else None
    keep = {}
    for pair in a.keep_active.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            keep[k.strip()] = v.strip()
    res = plan(json.loads(raw), ids, a.allow_auto_challengers, a.sentinel,
               keep, a.control_weight, a.min_control_share)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
