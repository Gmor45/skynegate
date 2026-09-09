# skynegate

Public on purpose, and deliberately almost empty. Renamed from
`claude-bootstrap` on GitHub (2026-09-09) — the old clone URL still redirects
here, but every pointer in this repo has been repointed to the current name so
nothing depends on that redirect surviving.

Claude's `Add marketplace` feature only syncs from a **public** repository
(verified 2026-08-29: a private repo returns *"Marketplace sync failed"*, an
otherwise identical public one syncs). The operating rules this points at are
personal, so publishing them to satisfy that requirement would be a bad trade.

This repo is the way around that. It carries one skill whose only job is to
clone the private repo and read the real rules from there. Nothing here is
worth protecting; everything that is stays private and is read live, so a rule
change is in force on the next session rather than after someone remembers to
paste it.

Install once, in the Plugins panel: **Add → Add marketplace →**
`https://github.com/Gmor45/skynegate`, leaving **Sync automatically** on.

**If you added this marketplace before the rename, check whether it's still
listed under the old name.** Some Claude Code surfaces track an installed
marketplace by the URL you originally typed, not by where it currently
resolves — if yours still shows `claude-bootstrap`, remove it and re-add
using the `skynegate` URL above so future syncs aren't relying on GitHub's
rename redirect.

## It also carries the reply gate

`.claude/hooks/reply_gate.py`, registered as a `Stop` hook in
`.claude/hooks/hooks.json`. It is here rather than in the private repo for one
reason: **a plugin already synced with "Sync automatically" on installs its
hooks with no further click.** House rule 15 says installing a skill is
Garrett's click and he should not be asked to click often — this is the one
delivery path that asks for zero.

**What it does.** When a substantive reply is about to be sent, the gate refuses
the stop unless the reply ends with a fixed block:

```
**What I did**       plain English, no jargon
**Why**              plain English, no jargon
**Recommendations**  optional, each with its reason
**TLDR**             one line
```

The body above the block may be as long and as technical as the work needs. The
block is what makes it optional to read.

**Why a hook and not another line in the rules.** House rule 21: a rule with no
mechanism is a hypothesis, and `convention-no-mechanism` is the single largest
failure class in the miss ledger. "Be concise" had been asked for more often
than anything else and had never held, because it is re-judged every turn and
every turn has a local excuse. A hook is the top row of rule 21's mechanism
table — it fires before the turn exists, with no judgment call.

**What it deliberately does not do.** It cannot tell whether prose is actually
simple; it checks shape, size, and a banned word list inside the block only. That
residue is uncovered on purpose — rule 21 point 5 says name what a gate cannot
see rather than shipping one that passes on the real failure.

It fails open on every error path, ignores short replies and tool-only turns, and
gives up after two re-prompts so it can never trap a session.

```bash
python3 .claude/hooks/reply_gate.py --self-test            # 10 checks
python3 .claude/hooks/reply_gate.py --transcript <file>    # dry-run a real transcript
```

The banned-word list is meant to grow: **when Garrett asks what a word means,
that word goes in the list in the same turn.**

## And the turn counter

`.claude/hooks/turn_counter.py`, registered as a second `Stop` hook alongside the
reply gate. It answers house-rules **3a**, which is the estate's largest measured
cost lever and had nothing firing on it.

**Why length matters more than model choice.** Every turn re-sends the whole
conversation behind it, so a chat's cost grows with roughly `turns²`. Measured
across the session index on 2026-09-04: **one session is about half of all
re-send cost ever incurred**, and ten sessions are seven eighths of it. Capping
chats at ~1,000 turns is worth more than switching to a cheaper model, and it
needs no tool and no permission — only a habit.

**What it does.** On every stop it counts the real user turns in the transcript.
Under 600 it does nothing at all. Crossing 600 it fires **once**, telling Claude
to say the count to Garrett and warn that a handoff should be written while there
is still room. Past 1,000 it fires once more and requires `/handoff` to actually
be run — because rule 3's recorded failure is a session that said the chat should
end four times and never wrote one. Past that, once every further 500 turns.

**Once per band, never a nag.** The band already announced is recorded per
session, so a gate that fires on every stop past 600 — which is a gate that gets
deleted — cannot happen.

**Why it is here rather than in each repo.** Garrett asked for it in "every repo
just so nothing gets missed." A repo's `.claude/settings.json` reaches only
sessions whose project directory is that repo, so eight copies would be eight
files that drift. This plugin is already synced, so one file fires in every
session on every surface with no click — the same argument that put the reply
gate here.

```bash
python3 .claude/hooks/turn_counter.py --self-test            # 20 checks
python3 .claude/hooks/turn_counter.py --count -t <file>      # count a real transcript
```

**Two copies of the threshold, said out loud.** `THRESHOLD = 1000` here and
`TURN_THRESHOLD` in `skyne/scripts/session_cost.py` are the same number: a plugin
hook runs with no repo attached (that is the point of it), and skyne cannot
import a plugin it does not ship. Nothing here can enforce the agreement, which
is stated rather than hidden — rule 21 point 5.

It fails open on every error path — no stdin, no transcript path, an unwritable
state directory, a half-written line — so it can never trap a session.

## It also carries a mechanical-task reminder and a Haiku subagent

Garrett asked (2026-09-05) for a way to route mechanical work — moving files,
running a script, formatting, applying an already-decided edit, sweeping one
change across many files — to a cheaper model automatically, the way he
assumed an MCP tool could. It can't: `anthropics/claude-code#17772` is still
open, and no hook or MCP primitive can initiate a model switch or spawn a
subagent on its own. What a hook CAN do is the half that actually was missing:
not the switching, the *noticing*. Rule 2 already names these tells in prose;
they were re-judged from scratch every turn, which is `convention-no-mechanism`
— the estate's largest measured failure class.

**`.claude/agents/haiku-mechanic.md`** — a subagent pinned to `model: haiku`,
scoped as `load-house-rules:haiku-mechanic` once this plugin is installed
(plugins auto-discover an `agents/` directory the same way they discover
`hooks/` and `skills/`). Its own instructions tell it to execute exactly what
it was asked, report counts rather than impressions, stop and ask rather than
guess at anything ambiguous, and never touch git — that stays with whichever
session spawned it.

**`.claude/hooks/delegate_reminder.py`**, a `UserPromptSubmit` hook. On every
prompt it scans for rule 2's own mechanical tells (a fixed phrase list lifted
verbatim from the rule, not a guessed vocabulary) and, on a hit, adds one line
of context naming the subagent as an option — suppressed if the same prompt
also carries one of rule 2's "up" tells (architecture, design, 3+ conflicting
constraints), and shown once per session so it nags nobody.

```bash
python3 .claude/hooks/delegate_reminder.py --self-test              # 17 checks
python3 .claude/hooks/delegate_reminder.py --check "some prompt text"
```

**What this is not.** It is a reminder, never a router. Nothing here decides
FOR Claude Code to delegate — that call is still made in the turn that reads
the reminder, same as rule 2a always was. And the match is a keyword scan, not
semantic understanding: it will miss a mechanical-shaped prompt phrased
differently, and it will occasionally fire on a prompt that only mentions one
of these words in passing. Both are named here rather than hidden — rule 21
point 5 — and the fix for either is a matched case added to the self-test, not
a claim that it got smarter.

It fails open on every error path, exactly like the two hooks above it.

## And it refuses a push to main

`.claude/hooks/no_push_to_main.py`, a `PreToolUse` hook on `Bash`. House rule 1
— never push to `main` — is the most expensive rule in the estate and, until
this file, the one with the weakest mechanism behind it: a paragraph. Pushing
to `main` fires up to five workflows; a branch with no PR fires none. Getting
it wrong produced a real Actions overage, ~3,580 minutes against 3,000
included, which Garrett paid for. Rule 1 even records itself being broken by
the session that wrote it, hours later, on a one-line doc edit.

**Why this one blocks when `delegate_reminder.py` only reminds.** Both came out
of the same conversation and the difference is the point. "Is this task
mechanical enough for Haiku?" is a judgement, so a reminder is the honest
ceiling. "Does this shell command push to main?" is a string, so it can be
refused outright — rule 21's top rung, which this rule qualified for and
nothing had claimed.

It refuses the shapes that do not look like a push to main at a glance —
`HEAD:main`, `+main`, `refs/heads/main`, `--delete main`, `cd x && git push
origin main`, and a bare `git push` while HEAD is on a protected branch — and
deliberately allows everything whose destination is not protected. The case
that matters most is `git push origin main-refactor`: a substring match on
"main" blocks a real branch, and a gate that blocks real work is a gate that
gets deleted. Every one of those is a fixture in the self-test, both
directions.

```bash
python3 .claude/hooks/no_push_to_main.py --self-test          # 42 checks
python3 .claude/hooks/no_push_to_main.py --check "git push origin main"
```

**No override, on purpose.** There is no environment variable that switches it
off, because Claude could set one and the gate would be decoration. The refusal
text names the branch-and-PR path instead, so the next move is obvious.

**What it cannot see.** It reads the Bash tool's command string, so a push made
some other way — inside a script it invokes, through a git alias, via an MCP or
API call, or from Garrett's own desktop obsidian-git backups — is invisible to
it. It also fails open on an unparsable command. This narrows the failure; it
does not close it.

## And it keeps Garrett's exact words across a compaction

`.claude/hooks/precompact_snapshot.py`, registered twice — as `PreCompact` and
as `SessionStart` with `matcher: "compact"`.

House rules already named this failure precisely: *"Past a certain size a
chat's earlier turns get summarised. A handoff written after that is a summary
of a summary, and what goes first is precision — exact field names, measured
counts, and his exact words. That is the part nobody can reconstruct later."*
There is a hook that fires at exactly that moment, and nothing used it. It was
found by enumerating the platform's 33 hook events from the docs rather than
from memory (`skyne/data/surfaces.json`).

**It does not summarise, and that is the design.** Compaction is already a
summariser; a hook firing just before it that writes its own summary has
preserved nothing. So it copies Garrett's turns verbatim, and when it has to
cut, it **drops whole turns and counts them** rather than paraphrasing. An
honest gap beats a smooth reconstruction. It also keeps the measured numbers
from his own words and the files this session wrote.

**Why a pair.** `PreCompact` can deny and observe but *cannot inject context* —
so a snapshot written by it alone is a file nobody opens, which is this
estate's measured failure mode (226 pins captured and never resurfaced).
`SessionStart` with `matcher: "compact"` re-fires after compaction and can
inject, so it prints where the snapshot is and what is in it. Neither half is
useful alone, which is why they are one file and why CI asserts both stay
registered.

**It never blocks.** `PreCompact` is allowed to refuse a compaction; this
doesn't, ever. Stranding a session with a full context window and no way
forward is strictly worse than a lost nuance — the same argument
`model_switch.py` makes for leaving `PreModelSwitch`'s block unused.

```bash
python3 .claude/hooks/precompact_snapshot.py --self-test   # 19 checks
python3 .claude/hooks/precompact_snapshot.py --announce    # what the next context sees
```

**What it cannot do.** It preserves a category — his words — not an importance
judgement, because judging importance is precisely what goes wrong under
compaction. Snapshots live under `~/.claude/skyne/precompact/`, so they are
per-machine and do not travel to another surface.

## A CI run can complete with zero jobs — that is not the same as a check failing

Measured 2026-09-06, on this exact branch. PR #24's head commit (`34ab6f1b`)
has a completed `ci` run (#43, a `push` event) whose `conclusion` is
`failure`, but `list_workflow_jobs` on it returns **zero jobs**, and its
`created_at`, `run_started_at` and `updated_at` are all the identical instant.
That is the shape of a run that failed before scheduling anything — not the
promise suite catching a real bug. GitHub also refused to let it be rerun
(`403 This workflow run cannot be retried`), and the base branch had no new
commits to merge in as a way to force a fresh `synchronize` event.

The sibling `skyne` repo's PR #277 shows the same absence one step further:
its last four commits on the identically-named branch have **no workflow run
at all** — `list_workflow_jobs`/check-runs return zero, not merely a failure.
Neither is diagnosed to a root cause yet; both are filed here rather than
assumed fixed, and this commit's own push is the fresh trigger being used to
find out whether the promise suite actually runs and passes on this branch.
