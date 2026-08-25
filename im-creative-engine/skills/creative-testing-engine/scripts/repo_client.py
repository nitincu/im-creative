#!/usr/bin/env python3
"""Repository client for the IM creative engine.

Transport: Google Apps Script web app, verified working 2026-08-24.
Every append also lands in a local JSONL mirror so nothing is lost if the
endpoint is unreachable; reads prefer the endpoint and fall back to the mirror.

Never write to Google Sheets through browser automation. It fails silently:
form_input into the formula bar reports success while the sheet records no edit.
See references/repository-setup.md.

Usage
  repo_client.py health
  repo_client.py schema [TAB]
  repo_client.py read TAB [--start-row N] [--as-dicts]
  repo_client.py append TAB --rows-json '[["a","b"],["c","d"]]'
  repo_client.py append TAB --dicts-json '[{"col":"val"}]'
  echo '[{...}]' | repo_client.py append TAB --stdin-dicts
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CONFIG_PATH = os.environ.get(
    "IM_CREATIVE_ENGINE_CONFIG",
    os.path.expanduser("~/.im-creative-engine/config.json"),
)
MIRROR_DIR = os.path.expanduser("~/.im-creative-engine/mirror")

# Canonical schema. Column order is the sheet's column order and must not be
# reordered -- the Apps Script appends positionally.
TABS = {
    "tests": [
        "test_id", "created_at", "operator", "offer_id", "offer_name",
        "advertiser", "category", "tier", "control_creative_id",
        "control_template", "control_conv_per_impr", "control_ctr",
        "control_skip_rate", "control_click_to_conv", "attributed_share",
        "mode", "brief", "status", "min_days", "max_days", "target_mde",
    ],
    "variants": [
        "test_id", "creative_id", "role", "hypothesis", "varied_attributes",
        "template", "weight_configured", "weight_verified", "status",
        "created_at", "compliance_hard", "compliance_soft",
    ],
    "outcomes": [
        "test_id", "creative_id", "decided_at", "impressions", "clicks",
        "conversions", "revenue", "conv_per_impr", "ctr", "skip_rate",
        "click_to_conv", "p_beat_control", "rel_lift", "verdict", "reason",
        "guardrail_breach",
    ],
    "elements": [
        "element_key", "attribute", "value", "category", "tag", "template",
        "n_tests", "n_wins", "n_losses", "total_impressions",
        "weighted_rel_lift", "confidence", "last_updated",
    ],
    "audit": [
        "timestamp", "operator", "action", "offer_id", "creative_id", "field",
        "from_value", "to_value", "test_id", "notes",
    ],
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config():
    try:
        with open(CONFIG_PATH) as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        die(f"no config at {CONFIG_PATH} -- see references/apps-script-setup.md")
    except json.JSONDecodeError as exc:
        die(f"config is not valid JSON: {exc}")
    for key in ("apps_script_url", "apps_script_secret"):
        if not cfg.get(key) or str(cfg[key]).startswith("PASTE_"):
            die(f"config key '{key}' is not filled in")
    return cfg


def die(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}), file=sys.stderr)
    sys.exit(code)


def _request(url, data=None, timeout=60, retries=3):
    """One HTTP call with retries. Apps Script 302-redirects its responses;
    urllib follows redirects by default, which is the equivalent of curl -L."""
    last = None
    for attempt in range(retries):
        try:
            if data is None:
                req = urllib.request.Request(url)
            else:
                req = urllib.request.Request(
                    url, data=json.dumps(data).encode(),
                    headers={"Content-Type": "application/json"},
                )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode()
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                # Apps Script serves an HTML error page when the deployment is
                # broken or the script threw before ContentService ran.
                return {"ok": False, "error": "non-JSON response",
                        "body_head": body[:300]}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return {"ok": False, "error": f"transport failed after {retries} tries: {last}"}


def read(tab, start_row=0):
    cfg = load_config()
    params = {"tab": tab, "secret": cfg["apps_script_secret"]}
    if start_row:
        params["startRow"] = start_row
    url = cfg["apps_script_url"] + "?" + urllib.parse.urlencode(params)
    res = _request(url)
    if not res.get("ok"):
        mirrored = _read_mirror(tab)
        if mirrored is not None:
            res = {"ok": True, "values": mirrored, "source": "mirror",
                   "warning": res.get("error")}
    else:
        res["source"] = "endpoint"
    return res


def _mirror_path(tab):
    return os.path.join(MIRROR_DIR, f"{tab}.jsonl")


def _write_mirror(tab, rows):
    os.makedirs(MIRROR_DIR, exist_ok=True)
    with open(_mirror_path(tab), "a") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _read_mirror(tab):
    path = _mirror_path(tab)
    if not os.path.exists(path):
        return None
    out = [TABS[tab]] if tab in TABS else []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def dicts_to_rows(tab, dicts):
    """Project dicts onto the canonical column order. Unknown keys are an error
    -- silently dropping a field is how a repository quietly loses data."""
    cols = TABS[tab]
    rows = []
    for i, d in enumerate(dicts):
        unknown = sorted(set(d) - set(cols))
        if unknown:
            die(f"row {i}: unknown columns for tab '{tab}': {unknown}")
        rows.append(["" if d.get(c) is None else str(d.get(c, "")) for c in cols])
    return rows


def append(tab, rows):
    if tab not in TABS:
        die(f"unknown tab '{tab}'. known: {sorted(TABS)}")
    width = len(TABS[tab])
    for i, row in enumerate(rows):
        if len(row) != width:
            die(f"row {i} has {len(row)} cells, tab '{tab}' needs {width}. "
                "Apps Script setValues rejects ragged rows.")
    if not rows:
        return {"ok": True, "appended": 0}

    _write_mirror(tab, rows)          # mirror first: never lose a write
    cfg = load_config()
    res = _request(cfg["apps_script_url"],
                   data={"secret": cfg["apps_script_secret"],
                         "tab": tab, "rows": rows})
    res["mirrored"] = True
    return res


def health():
    cfg = load_config()
    report = {"config_path": CONFIG_PATH, "tabs": {}}
    ok = True
    for tab, cols in TABS.items():
        res = read(tab)
        if not res.get("ok"):
            report["tabs"][tab] = {"ok": False, "error": res.get("error")}
            ok = False
            continue
        values = res.get("values") or []
        header = values[0] if values else []
        matches = header == cols
        report["tabs"][tab] = {
            "ok": matches, "rows": len(values), "source": res.get("source"),
            "header_matches_schema": matches,
        }
        if not matches:
            report["tabs"][tab]["expected"] = cols
            report["tabs"][tab]["found"] = header
            ok = False

    bad = _request(cfg["apps_script_url"] + "?" + urllib.parse.urlencode(
        {"tab": "tests", "secret": "deliberately-wrong"}))
    report["secret_enforced"] = (bad.get("ok") is False)
    if not report["secret_enforced"]:
        ok = False
        report["CRITICAL"] = ("endpoint served data with a wrong secret -- it is "
                              "open to anyone with the URL. Fix the script.")
    report["ok"] = ok
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")
    p_schema = sub.add_parser("schema")
    p_schema.add_argument("tab", nargs="?")

    p_read = sub.add_parser("read")
    p_read.add_argument("tab")
    p_read.add_argument("--start-row", type=int, default=0)
    p_read.add_argument("--as-dicts", action="store_true")

    p_app = sub.add_parser("append")
    p_app.add_argument("tab")
    g = p_app.add_mutually_exclusive_group(required=True)
    g.add_argument("--rows-json")
    g.add_argument("--dicts-json")
    g.add_argument("--stdin-dicts", action="store_true")

    a = ap.parse_args()

    if a.cmd == "health":
        r = health()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 2)

    if a.cmd == "schema":
        print(json.dumps({a.tab: TABS[a.tab]} if a.tab else TABS, indent=2))
        return

    if a.cmd == "read":
        res = read(a.tab, a.start_row)
        if a.as_dicts and res.get("ok"):
            vals = res.get("values") or []
            if len(vals) > 1:
                hdr = vals[0]
                res["records"] = [dict(zip(hdr, r)) for r in vals[1:]]
            else:
                res["records"] = []
            res.pop("values", None)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("ok") else 2)

    if a.cmd == "append":
        if a.rows_json:
            rows = json.loads(a.rows_json)
        else:
            raw = sys.stdin.read() if a.stdin_dicts else a.dicts_json
            rows = dicts_to_rows(a.tab, json.loads(raw))
        res = append(a.tab, rows)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res.get("ok") else 2)


if __name__ == "__main__":
    main()
