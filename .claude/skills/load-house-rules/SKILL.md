---
name: load-house-rules
description: Load Gmor45's standing operating rules before doing anything else. Use at the START of every session on any surface — Claude Code, Cowork, or claude.ai chat — that touches a Gmor45 repository (claude-audit, Gartera-Vault, FusterCluck, Tangle, claude-usage-hud, DnD-Scheduler, cloudflare-deploy, wedding), any Obsidian vault, or anything involving git, commits, branches, pushing, pull requests, merging, GitHub Actions, model choice, thinking effort, session length, usage limits, or cost. Also use on "don't push to main", "am I using this right", "should I start a new chat", "why is this so expensive", or any callout of a repeated mistake. This skill does not contain the rules — it fetches them.
---

# Load the house rules

**This skill is a pointer, not the rules.** The rules live in a private
repository so they can stay specific without being public. This file's only job
is to go get them, so that a rule change pushed to that repo reaches every
surface without anyone pasting anything.

## Do this first, before answering

### 0. Publish the Companion — BEFORE the clone, not after

Garrett is a visual processor and does not scroll back. A session with no
Companion has no view he can glance at, and he said so on 2026-09-01: *"I don't
have my visual aid firing reliably every chat."*

**It sits at step 0 for a measured reason.** It used to be rule 14 of 21 inside a
50 KB file, which is a position that loses to whatever else the turn is doing.
The rule was correct the whole time and never fired — the fix is where it sits
and what it costs, not more words in it.

If you can reach `claude-audit` (step 1 below), it is two commands:

```
python3 claude-audit/scripts/companion.py new --out companion.html
python3 claude-audit/scripts/companion.py check companion.html   # never publish a FAIL
```

If you cannot reach the repo, hand-build it — a page carrying, in this order:
**turn count · model and thinking tier · session state · one verdict LINE**
(`DOWNSHIFT` / `NEW CHAT` / `WAITING ON YOU` / `ON TRACK` — an instruction, not a
summary), then cards for what is happening now, what is settled, what is waiting
on him numbered so he can just do them, what will surprise him, and the next
move. Republish it whenever something on it becomes false — not every turn.

Do this on your first substantive turn. Not at the end; he may stop reading
replies at any point, and the Companion is what survives that.

### 1. Get the rules

**Clone or pull the private repo** into this session's workspace:

   ```
   git clone --depth 1 https://github.com/Gmor45/Skyne.git
   # already present? then:  git -C Skyne pull --ff-only
   # renamed from claude-audit on 2026-09-04; a clone directory still
   # named claude-audit is fine and deliberate on Garrett's desktop.
   ```

2. **Read the rules file in full:**

   ```
   claude-audit/.claude/skills/house-rules/SKILL.md
   ```

   Read the whole thing. Do not skim it, and do not act on a summary of it —
   it is the operating contract for every surface, and the failure it most
   often catches is a session that read *about* a thing instead of opening it.

3. **Open the Chain — one command, and it answers "what is already open":**

   ```
   python3 claude-audit/scripts/chain.py
   ```

   Every open thread in one shape: uncovered misses, backlog rows still open,
   and what a supersedes link already killed. `cold` means raised and then
   nobody came back to it. Read it at session start, and again before telling
   him anything is finished. An empty chain says `calm zero` out loud, so a
   clean run and a broken script never look the same.

4. **Follow it as if it had been loaded directly.** Everything in it applies:
   branch discipline, model and session-length guidance, the decisions
   register, the learning loop, the Thread, the braindump sweep.

5. **Also read, in the same repo, whichever of these the task touches:**

   | File | When |
   |---|---|
   | `.claude/skills/house-rules/DECISIONS.md` | Before asking him to re-affirm ANY design or process decision. **Do NOT plain-grep it** — run `python3 claude-audit/scripts/supersedes.py lookup <term>`, which searches the register AND every report and tags each hit `IN FORCE` or `SUPERSEDED`. Measured 2026-08-30: a plain `grep -n plugin DECISIONS.md` returned as its FIRST hit the entry the next line calls "WRONG, do not act on it", and seven reversed rulings carried no forward marker. Append-only means the file reads top-to-bottom and the stale answer comes first. |
   | `.claude/skills/night-shift/SKILL.md` | The nightly learning-loop procedure. |
   | `.claude/skills/handoff/SKILL.md` | Ending a session properly. |
   | `.claude/skills/braindump/SKILL.md` | A handwritten PDF, photo dump, or note export arrives. |
   | `.claude/skills/session-digest/SKILL.md` | The session/model audit. |

## If the clone fails

**In Cowork this is almost always the credential, not a broken clone.** See
below for the fix.

### The Cowork fallback: the credential Garrett already keeps

**Confirmed by Garrett 2026-09-01: his Cowork sessions clone `claude-audit`
fine**, because he keeps a fine-grained PAT in Cowork's custom instructions so he
does not have to paste one every chat. So the clone in step 1 is the live route
on that surface too, and a Cowork session that ends up ruleless has usually
skipped this skill rather than been blocked by it.

If the clone really is refused for want of a credential, ask him for that token
and splice it into the URL for that one command
(`https://x-access-token:<PAT>@github.com/...`) rather than writing it into git
config, so it is not left sitting in a file.

**Do not reach for the GitHub connector, and do not retry the same clone.** The
connector is separately and permanently broken here (rule 9a, six open Anthropic
issues) and will not even appear in Cowork's connector list to be turned on.

### And if the clone truly cannot happen: ask for a fresh PAT

**There is no Drive backup any more.** One existed for a few hours on
2026-09-01 and was deliberately removed the same day — Garrett's call, once
asked directly: the mirror needed real upkeep (re-split, re-upload, re-verify
every time the rules changed) to insure against a token that he can just
reissue by hand in a couple of minutes. Not worth the cost. Do not rebuild a
Drive mirror without him asking again.

So if the credential really is the problem, say so plainly and ask him for a
new fine-grained PAT to splice into the clone URL (per the paragraph above).
There is nowhere else to read the rules from.

### If that doesn't work

**Say so plainly and immediately. Do not proceed as if there were no rules.**

A session that silently continues without them is the exact failure this whole
arrangement exists to prevent — it will re-derive settled decisions, push to
`main`, and re-ask questions that were answered weeks ago, all while appearing
to work fine.

Known limits, so a failure is diagnosed rather than re-investigated:

- **claude.ai chat has no git.** It cannot clone anything. On that surface this
  skill cannot work, and the rules have to be pasted by hand. Say that rather
  than improvising.
- **A bare Cowork session has no credential for a private repo by default, and
  the GitHub connector will not save you — it is separately broken.** No
  `gh` CLI, no SSH key, `GITHUB_TOKEN` (if set) is a placeholder string not a
  real token, and even if Garrett has GitHub Integration showing "Connected" in
  Settings → Connectors, it does not appear in Cowork's own per-chat "Add
  connector" list, unlike Gmail/Calendar/Drive/Spotify — a known, long-open
  Anthropic bug (GitHub's MCP server doesn't support the OAuth flow Cowork's
  connector auto-auth needs; tracked in
  [`anthropics/claude-code#59854`](https://github.com/anthropics/claude-code/issues/59854)
  and five other issues, verified 2026-08-29). **Do not suggest "turn on the
  GitHub connector" as the fix — it will not show up to turn on.** The clone
  in step 1 will instead fail with `fatal: could not read Username for
  'https://github.com': terminal prompts disabled` until a human supplies a
  credential — verified 2026-08-29 by cloning the *public* `claude-bootstrap`
  repo with the identical command and no auth needed in the same container,
  isolating the failure to "no credential," not a broken git setup. **Say
  this plainly rather than retrying the same clone command or the connector.**
  If Garrett is in the chat, ask him to paste a GitHub personal access token;
  splice it into the clone URL for that one command
  (`https://x-access-token:<PAT>@github.com/...`) rather than writing it to git
  config, so it is not left sitting in a file.
- **Push from Cowork is walled off by a known, open Anthropic bug — not a
  design choice, and not fixable with a better credential.** Verified
  2026-08-29: even with a working PAT that made the clone succeed, push was
  refused with `remote: access denied by the git proxy: <repo> is not in this
  session's authorized repository set`. This is tracked publicly and
  unresolved: [`anthropics/claude-code#76248`](https://github.com/anthropics/claude-code/issues/76248)
  (opened 2026-07-10, reproduced) and
  [`anthropics/claude-code#84581`](https://github.com/anthropics/claude-code/issues/84581)
  (opened 2026-08-06, broader — some sessions can't read *any* repo). Both
  errors tell the agent to call `add_repo` or "add the repository to the
  session's sources" — **no such tool or UI exists inside a Cowork session.**
  Do not spend a session debugging this or trying more credential shapes; the
  credential is not the problem once clone already works. If a push must
  happen, hand the finished work to a Claude Code session to push instead —
  crediting Cowork as author, never claiming it (see house rule 9 in the file
  this skill just fetched).
- **A private repo needs the session to be authorized for it.** If the clone is
  refused for a reason other than the credential issue above, that is a
  separate access problem, not a missing file. Report which it was.

## Why it is built this way

The rules must reach Claude Code, Cowork, and claude.ai alike. The only
account-level mechanism for that requires a **public** repository, and the rules
themselves are personal — they name how he works, what he spends, and his own
words about his mistakes. Publishing that to solve a sync problem is a bad
trade.

So the public half is this pointer, which contains nothing worth protecting, and
the private half stays private and is read live. A rule change pushed to
`claude-audit` is in force on the next session that loads this skill — no paste,
no copy to drift out of date.
