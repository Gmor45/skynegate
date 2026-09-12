---
name: handoff
description: End a Claude session properly — write the session's handoff into Gmor45/Skyne, land it as a merged pull request, and hand Garrett a one-click button that starts the next chat already holding the context. Use when he types /handoff, and use it UNASKED the moment a session should end: the topic has changed, the chat has run long or been compacted, the next task does not need what is loaded, or a usage-limit warning has appeared. Also for "wrap this up", "write the handoff", "should I start a new chat", "end the chat", "file the report". Saying a chat should end WITHOUT running this is the failure this skill exists to stop. This skill does not contain the procedure — it fetches it.
---

# Handoff — pointer

**This skill is a pointer, not the procedure.** The real, current one lives in
the private `Gmor45/Skyne` repo at `.claude/skills/handoff/SKILL.md`.

## Do this, in order

1. **Get a clone of `Gmor45/Skyne`.** On Garrett's desktop one usually already
   exists — check `C:/gvwt/Skyne` and `C:/Users/gmoor/claude-audit` (that
   second directory name is deliberately stale; the HUD bridge finds the clone
   by it, so do not "fix" it). `C:/gvwt/Skyne` is **shared with other live
   sessions** and may be sitting on someone else's branch, so read from
   `origin/main` rather than the working tree, or clone fresh. Elsewhere:

   ```
   gh repo clone Gmor45/Skyne
   ```

2. **Read the real procedure from that clone, in full, and follow it exactly:**

   ```
   <clone>/.claude/skills/handoff/SKILL.md
   ```

   That file governs the pre-handoff gate, the footprint sweep, the chat
   grading passes, the pickup-tracking tag, the report format, and the
   branch → PR → **merge** sequence. **Merging is part of running the skill,
   not a permission to ask for** — `allow_auto_merge` is `false` on that repo,
   so nothing lands your PR for you, and a handoff sitting in an open PR is a
   handoff the next session cannot read.

3. **The repo file wins on any disagreement**, for the rest of the session.

## Why this file is this short, and why it used to be long

Same reason as its siblings (`gartera`, `gartera-connect`, `flow`,
`full-dive`): the procedure lives in one place, fetched live, so it has no
second copy to drift out of date.

**This one earned the pointer the hard way.** Until 2026-09-12 there was an
account-level *copy* of this skill in `~/.claude/skills/handoff/`, in no repo
at all — no history, no diff, nothing to revert. It had **forked**: 8 KB
against the repo's 17 KB, and it shadowed the good one everywhere outside
`Skyne`. Its step 4 told a session to `git push` to `main` a full day after
`main` became protected, so `/handoff` failed at its own last step and the
report sat unmerged — reproducing, in a new shape, the exact failure this skill
was built to stop. A skill is prose, so nothing warned.

There is a check now, on every pull request to that repo:

```
python3 scripts/check_skill_commands.py
```

It asserts that no skill command pushes to a protected default branch, that no
description or command names a repo under a retired name, and that **no
pointer points at another machine-local copy** — because a pointer to
`~/.claude/skills/` is the same unversioned file with an extra hop.
