#!/usr/bin/env python3
"""Compliance and quality pre-flight for a generated Linkout creative.

This is a heuristic net, NOT legal review. It exists because the engine runs on
full auto: without it, a generated creative for a regulated financial offer
reaches live traffic with no human or automated check in between. It catches the
mechanical, high-frequency failures. It cannot judge substantiation, and a clean
pass is not approval.

HARD findings block activation. SOFT findings are logged and served.

Usage
  compliance_preflight.py --input creative.json
  cat creative.json | compliance_preflight.py [--strict]

Input shape
  {"category":"financial","template":"Multiple Options + No Thanks",
   "title":"...","subtitle":"...","options":["Get My Card","View Details"],
   "disclaimer":"","skip_text":"No, Thanks!","enable_pii":false,
   "brands":["Merit Platinum"]}
"""

import argparse
import json
import re
import sys

# Absolute-certainty claims. In lead gen these are the ones that draw regulator
# and advertiser attention, because the outcome is never actually guaranteed.
ABSOLUTE_CLAIMS = [
    r"\bguarantee(d|s)?\b", r"\bpre-?approved\b", r"\byou(?:'re| are) approved\b",
    r"\b100%\s*(approval|approved|guaranteed)\b", r"\bno\s*risk\b",
    r"\brisk[- ]free\b", r"\binstant(ly)?\s+approv(ed|al)\b",
    r"\bcan(?:'t| ?not)\s+be\s+denied\b", r"\beveryone\s+qualifies\b",
    r"\bno\s+one\s+is\s+turned\s+down\b",
]
PROHIBITED = [
    r"\bfree\s+money\b", r"\bgovernment\s+grant\b", r"\bstimulus\s+check\b",
    r"\bdebt\s+forgiveness\s+guaranteed\b", r"\bunlimited\s+credit\b",
    r"\bno\s+credit\s+check\s+guaranteed\b",
]
# A money or rate figure implies terms, which implies a disclaimer.
FINANCIAL_FIGURE = r"(\$\s?\d[\d,]*(\.\d+)?|\b\d+(\.\d+)?\s*%\s*(apr|interest|rate))"
CONSENT_TOKENS = [
    "consent", "authorize", "agree to receive", "terms", "privacy policy",
    "opt in", "opt-in", "msg", "message and data rates", "unsubscribe",
]
FINANCIAL_CATEGORIES = {
    "financial", "finance", "credit", "credit card", "loans", "loan",
    "debt", "insurance", "banking", "mortgage", "tax", "crypto",
}
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF✅⬇️]"
)
KNOWN_ACRONYMS = {
    "USA", "US", "APR", "CPA", "CPC", "SSN", "PIN", "ID", "TCPA", "FAQ",
    "ATM", "FDIC", "NEW", "OK", "AI",
}


def _text_fields(c):
    parts = [c.get("title", ""), c.get("subtitle", "")]
    parts += list(c.get("options") or [])
    parts += [c.get("skip_text", ""), c.get("disclaimer", "")]
    return [p for p in parts if p]


def _visible_copy(c):
    """Everything a user reads except the disclaimer -- claims live here."""
    parts = [c.get("title", ""), c.get("subtitle", "")]
    parts += list(c.get("options") or [])
    return " ".join(p for p in parts if p)


def check(creative, strict=False, demote=None, ignore=None):
    """demote: codes downgraded from hard to soft. ignore: codes dropped.

    Both are recorded in the result so a demotion is always visible in the
    audit trail -- a silently relaxed rule is worse than no rule."""
    demote = set(demote or [])
    ignore = set(ignore or [])
    hard, soft = [], []
    title = creative.get("title") or ""
    subtitle = creative.get("subtitle") or ""
    disclaimer = (creative.get("disclaimer") or "").strip()
    category = str(creative.get("category") or "").strip().lower()
    visible = _visible_copy(creative)
    lowered = visible.lower()
    is_financial = category in FINANCIAL_CATEGORIES

    for pattern in ABSOLUTE_CLAIMS:
        m = re.search(pattern, lowered, re.I)
        if m:
            hard.append({
                "code": "absolute_claim",
                "detail": f"absolute-certainty claim {m.group(0)!r}",
                "fix": "qualify it -- 'see if you qualify', 'check your options'",
            })
    for pattern in PROHIBITED:
        m = re.search(pattern, lowered, re.I)
        if m:
            hard.append({
                "code": "prohibited_phrase",
                "detail": f"prohibited phrase {m.group(0)!r}",
                "fix": "remove entirely; there is no compliant phrasing",
            })

    money = re.search(FINANCIAL_FIGURE, visible, re.I)
    if is_financial and not disclaimer:
        hard.append({
            "code": "missing_disclaimer_financial",
            "detail": f"category '{category}' with an empty Disclaimer field",
            "fix": "populate Disclaimer before activation",
        })
    elif money and not disclaimer:
        hard.append({
            "code": "missing_disclaimer_figure",
            "detail": f"states {money.group(0)!r} with no disclaimer",
            "fix": "a stated amount or rate implies terms; add the disclaimer",
        })

    if creative.get("enable_pii"):
        haystack = (disclaimer + " " + lowered).lower()
        if not any(tok in haystack for tok in CONSENT_TOKENS):
            hard.append({
                "code": "pii_without_consent",
                "detail": "Enable PII Fields is on with no consent language",
                "fix": "add express consent language, or turn PII fields off",
            })

    # --- soft ---

    # This one is not hypothetical. Live creative 5060 has run at 100% weight
    # for ~11 months with the title "Get your $750 Credit line instantly Start
    # shopping in minutes!" -- two sentences with nothing between them.
    for name, text in (("title", title), ("subtitle", subtitle)):
        for m in re.finditer(r"[a-z0-9]\s+([A-Z][a-z]+)", text):
            before = text[:m.start() + 1]
            if not re.search(r"[.!?,:;–—-]\s*$", before):
                word = m.group(1)
                if word.lower() in {"i"} or word in KNOWN_ACRONYMS:
                    continue
                soft.append({
                    "code": "run_on_sentences",
                    "detail": f"{name}: missing punctuation before {word!r}",
                    "fix": "add a period, dash, or comma at the junction",
                })
                break

    if len(title) > 90:
        soft.append({"code": "title_long",
                     "detail": f"title is {len(title)} chars",
                     "fix": "trim to under 90 for mobile"})

    bangs = visible.count("!")
    if bangs > 2:
        soft.append({"code": "exclamation_overuse",
                     "detail": f"{bangs} exclamation marks",
                     "fix": "at most one or two"})

    emoji_n = len(EMOJI.findall(visible))
    if emoji_n > 4:
        soft.append({"code": "emoji_overuse",
                     "detail": f"{emoji_n} emoji in visible copy",
                     "fix": "cap at 3-4"})

    shouty = [w for w in re.findall(r"\b[A-Z]{3,}\b", visible)
              if w not in KNOWN_ACRONYMS]
    if len(shouty) > 2:
        soft.append({"code": "all_caps",
                     "detail": f"all-caps words: {shouty[:6]}",
                     "fix": "sentence case reads as less spammy"})

    for brand in creative.get("brands") or []:
        if brand and brand in visible and not re.search(
                re.escape(brand) + r"\s*[™®℠]", visible):
            soft.append({
                "code": "brand_no_symbol",
                "detail": f"brand {brand!r} appears without a symbol",
                "fix": "confirm whether it needs (TM) or (R)",
            })

    opts = [o for o in (creative.get("options") or []) if o]
    generic = {"continue", "view details", "next", "click here", "submit", "more"}
    weak = [o for o in opts if o.strip().lower() in generic]
    if weak:
        soft.append({
            "code": "generic_cta",
            "detail": f"generic CTA text: {weak}",
            "fix": "name the benefit -- 'Get $750 Credit' beats 'Continue'",
        })
    if len(opts) != len(set(o.strip().lower() for o in opts)):
        soft.append({"code": "duplicate_cta",
                     "detail": "duplicate option text",
                     "fix": "differentiate each option"})

    for token in re.findall(r"\{\{[^}]+\}\}", visible):
        if token not in (creative.get("macro_mappings") or {}):
            hard.append({
                "code": "unmapped_macro",
                "detail": f"{token} has no Macro Mapping",
                "fix": "map it, or users see the raw token",
            })

    if ignore:
        hard = [f for f in hard if f["code"] not in ignore]
        soft = [f for f in soft if f["code"] not in ignore]
    demoted = [f for f in hard if f["code"] in demote]
    if demoted:
        for f in demoted:
            f["demoted_from"] = "hard"
        hard = [f for f in hard if f["code"] not in demote]
        soft = demoted + soft

    blocked = bool(hard) or (strict and bool(soft))
    return {
        "ok": not blocked,
        "blocked": blocked,
        "may_activate": not blocked,
        "hard": hard,
        "soft": soft,
        "hard_count": len(hard),
        "soft_count": len(soft),
        "policy_applied": {
            "demoted_to_soft": sorted(demote),
            "ignored": sorted(ignore),
            "strict": strict,
        },
        "note": ("Heuristic screen, not legal review. A clean pass is not "
                 "approval and does not assess claim substantiation."),
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    ap.add_argument("--strict", action="store_true",
                    help="treat soft findings as blocking too")
    ap.add_argument("--demote", default="",
                    help="comma-separated codes to downgrade hard->soft")
    ap.add_argument("--ignore", default="",
                    help="comma-separated codes to drop entirely")
    ap.add_argument("--rules", help="JSON file with demote_to_soft / ignore lists")
    a = ap.parse_args()

    demote = [c for c in a.demote.split(",") if c]
    ignore = [c for c in a.ignore.split(",") if c]
    if a.rules:
        with open(a.rules) as fh:
            rules = json.load(fh)
        demote += rules.get("demote_to_soft") or []
        ignore += rules.get("ignore") or []

    raw = open(a.input).read() if a.input else sys.stdin.read()
    res = check(json.loads(raw), a.strict, demote, ignore)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["ok"] else 3)


if __name__ == "__main__":
    main()
