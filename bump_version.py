#!/usr/bin/env python3
"""Set every version in this repo at once, or check that they agree.

WHY THIS EXISTS. Three files carry a version and they must move together:

  .claude-plugin/marketplace.json                     marketplace + plugin entry
  im-creative-engine/.claude-plugin/plugin.json        the plugin
  im-creative-engine/skills/.../rules/creative-rules.json   (only when rules change)

marketplace.json originally had no version at all, so the marketplace never
changed when the plugin did. A client that caches the marketplace index saw
nothing new and offered no update, which is how an install sits on a stale
version while the repo is several releases ahead. Bumping by hand across three
files is how they drift, so this does it in one shot.

The marketplace NAME is deliberately not touched. It is the identifier operators
added; changing it breaks every existing install. The version is the lever.

Usage
  ./bump_version.py 1.9.1              set plugin + marketplace to 1.9.1
  ./bump_version.py 1.9.1 --rules 1.7.0   also set the rules version
  ./bump_version.py --check            verify agreement, non-zero if they drift
"""

import argparse
import json
import pathlib
import re
import sys

MARKET = pathlib.Path(".claude-plugin/marketplace.json")
PLUGIN = pathlib.Path("im-creative-engine/.claude-plugin/plugin.json")
RULES = pathlib.Path(
    "im-creative-engine/skills/creative-testing-engine/rules/creative-rules.json")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def load(p):
    return json.loads(p.read_text())


def save(p, d):
    p.write_text(json.dumps(d, indent=2) + "\n")


def check():
    m, pl = load(MARKET), load(PLUGIN)
    entry = next((e for e in m.get("plugins", [])
                  if e.get("name") == pl["name"]), None)
    problems = []
    if not m.get("version"):
        problems.append("marketplace.json has no version")
    if entry is None:
        problems.append(f"marketplace.json lists no plugin named {pl['name']!r}")
    else:
        if entry.get("version") != pl["version"]:
            problems.append(f"plugin entry version {entry.get('version')!r} != "
                            f"plugin.json {pl['version']!r}")
        if entry.get("description") != pl.get("description"):
            problems.append("plugin entry description has drifted from plugin.json")
    if m.get("version") and m["version"] != pl["version"]:
        problems.append(f"marketplace version {m['version']!r} != "
                        f"plugin.json {pl['version']!r}")

    print(f"  marketplace.json   version: {m.get('version') or '(none)'}")
    print(f"  plugin.json        version: {pl['version']}")
    if entry:
        print(f"  plugin entry       version: {entry.get('version') or '(none)'}")
    if RULES.exists():
        print(f"  creative-rules     version: {load(RULES).get('version')}")
    if problems:
        print("\n  DRIFT:")
        for x in problems:
            print("    - " + x)
        return False
    print("\n  all versions agree")
    return True


def bump(version, rules_version=None):
    if not SEMVER.match(version):
        sys.exit(f"not a semver: {version!r}")

    pl = load(PLUGIN)
    pl["version"] = version
    save(PLUGIN, pl)

    m = load(MARKET)
    m["version"] = version
    found = False
    for e in m.setdefault("plugins", []):
        if e.get("name") == pl["name"]:
            e["version"] = version
            e["description"] = pl.get("description", e.get("description"))
            found = True
    if not found:
        m["plugins"].append({"name": pl["name"],
                             "source": f"./{pl['name']}",
                             "version": version,
                             "description": pl.get("description", "")})
    save(MARKET, m)

    if rules_version:
        if not SEMVER.match(rules_version):
            sys.exit(f"not a semver: {rules_version!r}")
        r = load(RULES)
        r["version"] = rules_version
        save(RULES, r)

    print(f"  set plugin + marketplace to {version}"
          + (f", rules to {rules_version}" if rules_version else ""))
    print()
    return check()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?")
    ap.add_argument("--rules")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if not MARKET.exists() or not PLUGIN.exists():
        sys.exit("run this from the repo root")
    if a.check or not a.version:
        sys.exit(0 if check() else 1)
    sys.exit(0 if bump(a.version, a.rules) else 1)


if __name__ == "__main__":
    main()
