# Interest Media plugin marketplace

Internal. Private repo — access controls the rules, not just the code.

## For operators

In Claude Code, open the plugin manager and add this marketplace, then install
`im-creative-engine`. `/plugin` walks you through both steps.

Then follow `im-creative-engine/SETUP.md`.

## For the Admin

Updating rules for the whole org:

1. Edit `im-creative-engine/rules/creative-rules.json`
2. Bump `version` inside that file **and** `version` in
   `im-creative-engine/.claude-plugin/plugin.json` — keep them equal
3. Commit and push
4. Operators pull the update from `/plugin`

Every test records the `rules_version` it ran under, so a result can always be
traced to the rules that produced it. That only works if the version is bumped.

## Never commit

- `~/.im-creative-engine/config.json` or any secret
- Anything from the admin tier: `learn_from_history.py`,
  `fetch_creative_assets.py`, `rules/_admin/`, `notify.py`,
  `admin-reporter.md`, or the Apps Script source

Those live only on the Admin's machine. This repo is readable by everyone who
can install the plugin.
