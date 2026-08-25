#!/usr/bin/env python3
"""Sequential champion/challenger decision for Linkout creative tests.

Deterministic by construction: no sampling, no randomness, no model judgment.
The same input always produces the same verdict, so a promotion can be defended
to an advertiser or to finance months later.

PRIMARY METRIC: conversions per impression.
For CPA and CPC-as-CPA Linkout offers the advertiser payout per conversion is
flat (measured at $0.703 vs $0.704 across two independent buckets on the pilot
offer), so revenue is a deterministic function of conversions. Optimising
conversions per impression IS optimising RPM, which removes the usual
clicks-versus-revenue tension. If you ever apply this to an offer with variable
payout, revisit this choice first.

METHOD: Beta-Binomial posteriors, normal-approximated, compared analytically.
Posterior for each arm is Beta(1 + conversions, 1 + impressions - conversions).
A Beta is approximated by a normal with matched mean and variance; the
difference of two independent normals is normal, so P(challenger > control) is
a single closed-form Phi() evaluation. At the impression counts these tests
run at (thousands), the approximation error is far below the decision
thresholds. It needs no scipy and no seed.

GUARDRAILS (either can veto a statistical winner):
  * click-to-conversion ratio must not fall more than --max-c2c-drop-pp
  * skip rate must not rise more than --max-skip-rise-pp
A challenger that lifts clicks while degrading either is not a winner: it is
buying volume with lead quality.

Usage
  sequential_test.py --input state.json
  cat state.json | sequential_test.py

Input shape
  {
    "test_id": "...",
    "days_running": 9,
    "control":    {"creative_id":"5060","impressions":84343,"clicks":28649,
                   "conversions":24799,"skips":50455,"revenue":17444.0},
    "challengers":[{"creative_id":"7140","impressions":6100,"clicks":2400,
                    "conversions":2050,"skips":3400,"revenue":1441.0}]
  }
"""

import argparse
import json
import math
import sys

# Defaults chosen against the pilot offer's real volume: creative 5060 runs
# ~1,361 impressions/day, so a challenger at 10% weight gets ~136/day and
# clears min_impressions in ~16 days for a 10% relative MDE.
DEFAULTS = {
    "confidence": 0.95,
    "min_lift": 0.05,          # relative; below this a "win" is not worth the churn
    "min_impressions": 2000,   # per challenger, before any promote decision
    "min_days": 7,             # spans day-of-week and on/off-peak
    "max_days": 21,            # past this, call it and free the slot
    "early_kill_p": 0.05,      # P(beat control) below this is a fast loss
    "early_min_impressions": 500,
    "max_c2c_drop_pp": 3.0,    # percentage points
    "max_skip_rise_pp": 5.0,   # percentage points
    "max_rev_per_conv_drop": 0.10,  # relative; for variable-payout offers
    "bonferroni": True,
}


def _phi(z):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _beta_moments(successes, trials):
    """Mean and variance of Beta(1+s, 1+f) -- Laplace prior, weakly informative."""
    a = 1.0 + successes
    b = 1.0 + max(trials - successes, 0)
    n = a + b
    return a / n, (a * b) / (n * n * (n + 1.0))


def p_beats(chal, ctrl):
    """P(challenger conversion rate > control conversion rate)."""
    m_t, v_t = _beta_moments(chal["conversions"], chal["impressions"])
    m_c, v_c = _beta_moments(ctrl["conversions"], ctrl["impressions"])
    sd = math.sqrt(v_t + v_c)
    if sd == 0:
        return 0.5
    return _phi((m_t - m_c) / sd)


def _safe_div(n, d):
    return (n / d) if d else 0.0


def metrics(arm):
    impr = arm.get("impressions", 0) or 0
    return {
        "impressions": impr,
        "clicks": arm.get("clicks", 0) or 0,
        "conversions": arm.get("conversions", 0) or 0,
        "revenue": round(float(arm.get("revenue", 0) or 0), 2),
        "conv_per_impr": round(_safe_div(arm.get("conversions", 0), impr), 6),
        "ctr": round(_safe_div(arm.get("clicks", 0), impr), 6),
        "skip_rate": round(_safe_div(arm.get("skips", 0), impr), 6),
        "click_to_conv": round(
            _safe_div(arm.get("conversions", 0), arm.get("clicks", 0)), 6),
        "rpm": round(_safe_div(float(arm.get("revenue", 0) or 0), impr) * 1000, 2),
        "rev_per_conv": round(
            _safe_div(float(arm.get("revenue", 0) or 0),
                      arm.get("conversions", 0)), 4),
    }


def evaluate(state, cfg):
    ctrl = state["control"]
    cm = metrics(ctrl)
    challengers = state.get("challengers") or []
    k = max(len(challengers), 1)

    threshold = cfg["confidence"]
    if cfg["bonferroni"] and k > 1:
        # Guard against a false positive appearing simply because several
        # challengers were tested against one shared control.
        threshold = 1.0 - (1.0 - cfg["confidence"]) / k

    days = state.get("days_running", 0)
    results = []

    for chal in challengers:
        m = metrics(chal)
        p = p_beats(chal, ctrl)
        rel_lift = _safe_div(m["conv_per_impr"] - cm["conv_per_impr"],
                             cm["conv_per_impr"])

        breaches = []
        c2c_drop_pp = (cm["click_to_conv"] - m["click_to_conv"]) * 100.0
        if m["clicks"] > 0 and c2c_drop_pp > cfg["max_c2c_drop_pp"]:
            breaches.append(
                f"click-to-conversion down {c2c_drop_pp:.1f}pp "
                f"(limit {cfg['max_c2c_drop_pp']}pp)")
        skip_rise_pp = (m["skip_rate"] - cm["skip_rate"]) * 100.0
        if skip_rise_pp > cfg["max_skip_rise_pp"]:
            breaches.append(
                f"skip rate up {skip_rise_pp:.1f}pp "
                f"(limit {cfg['max_skip_rise_pp']}pp)")

        # Revenue per conversion. On RSOC and other variable-payout offers the
        # payout is NOT flat, so conversions per impression is no longer a proxy
        # for RPM: a challenger can win conversions while routing lower-value
        # traffic. Without this, the engine would optimise into cheaper clicks.
        if cm["rev_per_conv"] > 0 and m["conversions"] > 0:
            rpc_drop = _safe_div(cm["rev_per_conv"] - m["rev_per_conv"],
                                 cm["rev_per_conv"])
            if rpc_drop > cfg["max_rev_per_conv_drop"]:
                breaches.append(
                    f"revenue per conversion down {rpc_drop:.1%} "
                    f"(${cm['rev_per_conv']:.2f} -> ${m['rev_per_conv']:.2f}, "
                    f"limit {cfg['max_rev_per_conv_drop']:.0%})")

        verdict, reason = _decide(p, rel_lift, m, days, breaches, threshold, cfg)

        results.append({
            "creative_id": chal.get("creative_id"),
            **m,
            "p_beat_control": round(p, 4),
            "rel_lift": round(rel_lift, 4),
            "threshold_applied": round(threshold, 4),
            "verdict": verdict,
            "reason": reason,
            "guardrail_breach": "; ".join(breaches),
        })

    return {
        "test_id": state.get("test_id"),
        "days_running": days,
        "bonferroni_applied": bool(cfg["bonferroni"] and k > 1),
        "threshold": round(threshold, 4),
        "control": {"creative_id": ctrl.get("creative_id"), **cm},
        "challengers": results,
        "promote": [r["creative_id"] for r in results if r["verdict"] == "promote"],
        "kill": [r["creative_id"] for r in results if r["verdict"] == "kill"],
    }


def _decide(p, rel_lift, m, days, breaches, threshold, cfg):
    # Fast loss first: stop paying for a clear loser before the minimum window.
    if (p < cfg["early_kill_p"]
            and m["impressions"] >= cfg["early_min_impressions"]):
        return "kill", (f"P(beat control)={p:.3f} below early-kill "
                        f"{cfg['early_kill_p']} at {m['impressions']} impressions")

    # A guardrail breach is fatal regardless of the primary metric.
    if breaches and m["impressions"] >= cfg["early_min_impressions"]:
        return "kill", "guardrail breach: " + "; ".join(breaches)

    if days < cfg["min_days"]:
        return "continue", (f"day {days} of minimum {cfg['min_days']} "
                            "(day-of-week coverage incomplete)")

    if m["impressions"] < cfg["min_impressions"]:
        return "continue", (f"{m['impressions']} of {cfg['min_impressions']} "
                            "impressions needed")

    if p >= threshold and rel_lift >= cfg["min_lift"]:
        return "promote", (f"P(beat control)={p:.3f} >= {threshold:.3f} "
                           f"with relative lift {rel_lift:+.1%}")

    if p >= threshold and rel_lift < cfg["min_lift"]:
        return "continue", (f"statistically ahead (p={p:.3f}) but lift "
                            f"{rel_lift:+.1%} is under the {cfg['min_lift']:.0%} "
                            "minimum worth promoting for")

    if days >= cfg["max_days"]:
        return "inconclusive", (f"{days} days elapsed at p={p:.3f}; "
                                "freeing the slot")

    return "continue", f"p={p:.3f}, lift {rel_lift:+.1%}, still accruing"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="path to state JSON (default: stdin)")
    for key, val in DEFAULTS.items():
        if isinstance(val, bool):
            ap.add_argument(f"--no-{key.replace('_','-')}",
                            dest=key, action="store_false", default=val)
        else:
            ap.add_argument(f"--{key.replace('_','-')}",
                            type=type(val), default=val)
    a = ap.parse_args()

    raw = open(a.input).read() if a.input else sys.stdin.read()
    state = json.loads(raw)
    cfg = {k: getattr(a, k) for k in DEFAULTS}

    if "control" not in state:
        print(json.dumps({"ok": False, "error": "input needs a 'control' arm"}),
              file=sys.stderr)
        sys.exit(1)

    print(json.dumps(evaluate(state, cfg), indent=2))


if __name__ == "__main__":
    main()
