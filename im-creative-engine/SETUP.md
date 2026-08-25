# Creative Testing Engine — setup

About 15 minutes. You need five things working, then one command to prove it.

You are running the **execution tier**. The engine's rules — what a creative may
look like, which experiment runs next, when a winner is called — are set centrally
and ship inside the plugin. You supply an offer; the engine does the rest.

---

## Terminal, or Claude?

Commands in this guide run in one of two places. Getting this wrong is the most
common setup failure.

| Runs in | Looks like | Examples |
|---|---|---|
| **Terminal** (Terminal.app, iTerm, your shell) | plain command | `python3 -V`, `mkdir`, `chmod`, `xcode-select` |
| **Inside a Claude Code session** | starts with `/` | `/plugin` |

`/plugin` is **not** a shell command. Pasting it into a terminal gets you
`command not found`. Type it into Claude, where you'd normally type a message.

---

## Before you start, get these from the Admin

- The plugin folder (or its marketplace name)
- The repository URL and the **public** secret

Do not ask for the admin secret. It is scoped differently on purpose.

---

## 1. Claude Code

Confirm it runs:

```bash
claude --version
```

If it is missing, install it first: https://claude.com/claude-code

## 2. Python 3

The engine's decision logic — which experiment runs, whether a variant passes the
rules, when a winner is called — is Python. **Check first, because you almost
certainly already have it:**

```bash
python3 -V
```

Anything **3.8 or newer** works. Verified on 3.9.6, which is what macOS ships. If
that prints a version, skip the rest of this step.

### If it says `command not found` — macOS

Lightest path, no Homebrew needed:

```bash
xcode-select --install
```

Click through the prompt, then re-run `python3 -V`.

Already on Homebrew, or you want a current release:

```bash
brew install python@3.12
```

Prefer a graphical installer: grab the latest 3.x from
https://www.python.org/downloads

### If it says `command not found` — Windows

Install from the Microsoft Store (search "Python 3"), or:

```
winget install Python.Python.3.12
```

Then confirm **`python3 -V` specifically** works. The engine invokes `python3`,
and some Windows installs only provide `python` or `py`. If `python3` isn't
found, fix that before going further or every engine command will fail.

### Nothing to pip install

The engine uses only the Python standard library — `argparse`, `json`, `math`,
`re`, `urllib`, `subprocess`, `collections`, `datetime`. There is no
`requirements.txt`, no virtualenv, and no pip step. If anyone tells you to run
`pip install`, they're guessing.

## 3. Console access in Claude's native browser

The engine reads and writes Console through **Claude's native browser**, not your
normal Chrome.

1. Open the Browser pane in Claude Code
2. Go to `https://console.im-reporting.com`
3. Sign in with your work Google account

Two things people get wrong here:

- **`console.im-reporting.com` is the right host.** `console.customer-acquisition.co`
  is a different Cloudflare Access app and will reject you.
- **"That account does not have access"** means your Google identity is not on the
  Access policy. That is an access request, not a login problem — ask the Admin.

Stay signed in. The engine cannot log in for you and will not ask for credentials.

## 4. Tableau

All performance data comes from Tableau. Connect the Tableau connector in Claude
Code for your `tableau.im-reporting.com` site. If you can see Linkout reporting in
Tableau in a browser, your account is provisioned; the connector just needs adding.

## 5. Install the plugin

Whichever the Admin tells you:

```bash
# from a marketplace the Admin publishes
/plugin install im-creative-engine
```

Or place the folder they send you at `~/.claude/plugins/im-creative-engine` and
enable it with `/plugin`.

## 6. Add your config

```bash
mkdir -p ~/.im-creative-engine
```

Create `~/.im-creative-engine/config.json`:

```json
{
  "apps_script_url": "<URL the Admin gave you>",
  "apps_script_secret": "<PUBLIC secret the Admin gave you>",
  "repo_transport": "apps_script"
}
```

Lock it down:

```bash
chmod 600 ~/.im-creative-engine/config.json
```

Treat that secret like a password. Do not commit it, do not paste it into chat,
do not share it in Slack.

---

## 7. Prove it works

### First, find the plugin. Don't assume the path.

Where the plugin lands depends on how it was installed, so **locate it rather
than guessing.** In a terminal:

```bash
find ~ -name repo_client.py -path '*im-creative-engine*' 2>/dev/null | head -1
```

That prints the real path. Hold on to it:

```bash
ENGINE=$(find ~ -name repo_client.py -path '*im-creative-engine*' 2>/dev/null | head -1)
echo "$ENGINE"
```

If that echoes nothing, the plugin isn't on disk where you think it is — go back
to step 5.

### Then run the check

```bash
python3 "$ENGINE" health
```

You want `"ok": true` across all five tabs.

**If `secret_enforced` comes back `false`, stop and tell the Admin immediately.**
It means the repository endpoint is open to anyone holding the URL.

A `forbidden` response for `elements` is correct, not a fault. That's the
learning library, and the execution tier doesn't read it.

### Why this one command is the only check that matters

`health` exercises everything beneath it in one shot: it runs on `python3`
(step 2), it lives at the plugin path (step 5), it reads your config (step 6),
and it reaches the endpoint over the network. If it returns `ok`, steps 2, 5,
6 and your connectivity are all confirmed. If it fails, the error tells you
which one broke.

That's the verification order: **`python3` exists → plugin path resolves →
config is in place → `health` proves the lot.**

---

## 8. Run it

Just name an offer:

> test creatives on RH - Merit Platinum $0.75 CPA

The engine will resolve the offer, read its Console state, identify the control,
pull the baseline, pick the next queued experiment, build variants inside the
rules, verify them, write them live at an 80/20 split, and record everything.

To check a running test:

> check the creative test on <offer name>

---

## What the engine will not do, and why

- **It will not invent an experiment.** If no queued experiment applies to an
  offer, it stops and tells you to ask the Admin. That is deliberate.
- **It will not take creative direction.** Asking for "a punchier headline" or
  "something more aggressive" gets declined. The rules define what a creative may
  look like so results stay comparable across the whole org.
- **It will not skip a failed check.** If a variant breaks a rule it gets rewritten,
  not waved through.

None of this stops you taking a creative live. It constrains what the creative
looks like, not your ability to ship it.

---

## Troubleshooting

| What you see | What it means |
|---|---|
| `That account does not have access` | Google identity not on the Access policy — ask the Admin |
| `health` fails with a transport error | Wrong URL, or the Admin has not deployed the endpoint |
| `secret_enforced: false` | Endpoint is unprotected. Report it and stop |
| `forbidden: public tier cannot read elements` | Working as intended |
| `no queue entry applies to this control` | No experiment fits this offer. Ask the Admin |
| Challenger sitting at zero impressions after a day | `Weightage` was set but `Status` stayed off. Re-run the write step |
| `python3: command not found` | Python isn't installed or isn't on PATH — see step 2 |
| `/plugin: command not found` | You pasted it into a terminal. It goes inside Claude |
| `$ENGINE` echoes nothing | Plugin isn't on disk — redo step 5 |
| `No such file or directory` on the health command | Wrong plugin path. Re-run the `find` in step 7 |
| `no config at ...` | Step 6 was skipped, or the file is in the wrong place |
| A creative saved with a blank title | The rich-text editor did not register. Re-run; the engine verifies before saving |
| Console search box ignores what is typed | Known. The engine sets it programmatically instead |

## Getting help

Include the offer name, the `test_id` if there is one, and the output of the
`health` command. Those three make almost any problem diagnosable straight away.
