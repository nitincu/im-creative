# Interest Media plugin marketplace

Internal. Private repo — access controls the rules, not just the code.

## For operators

In Claude Code, open the plugin manager and add this marketplace, then install
`im-creative-engine`. `/plugin` walks you through both steps.

Then follow `im-creative-engine/SETUP.md`.

## For the Admin

### Every release: bump with the tool, never by hand

```bash
./bump_version.py 1.9.2                  # plugin + marketplace
./bump_version.py 1.9.2 --rules 1.7.0    # also the rules, when rules changed
./bump_version.py --check                # verify before committing
```

Three files carry a version and they must move together:

| File | Carries |
|---|---|
| `.claude-plugin/marketplace.json` | marketplace version **and** the plugin entry's version + description |
| `im-creative-engine/.claude-plugin/plugin.json` | the plugin version |
| `.../rules/creative-rules.json` | the rules version, only when the rules actually change |

**Why the marketplace version matters.** It originally had none, so the
marketplace never changed when the plugin did. A client that caches the
marketplace index saw nothing new and offered no update — which is how an
install sits on 1.1.0 while the repo is eight releases ahead. Bumping three
files by hand is how they drift, so the tool does all of them and `--check`
fails if they disagree.

The marketplace **name** is deliberately never bumped. It is the identifier
operators added; changing it breaks every existing install.

### Rules changes

1. Edit `im-creative-engine/skills/creative-testing-engine/rules/creative-rules.json`
2. `./bump_version.py <new> --rules <new-rules>`
3. `./bump_version.py --check`
4. Commit and push
5. Operators update from `/plugin`

Every test records the `rules_version` it ran under, so a result can always be
traced to the rules that produced it. That only works if the version moves.

## Never commit

- `~/.im-creative-engine/config.json` or any secret
- Anything from the admin tier: `learn_from_history.py`,
  `fetch_creative_assets.py`, `rules/_admin/`, `notify.py`,
  `admin-reporter.md`, or the Apps Script source

Those live only on the Admin's machine. This repo is readable by everyone who
can install the plugin.
