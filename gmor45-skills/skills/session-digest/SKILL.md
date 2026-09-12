---
name: session-digest
description: Nightly pull of Garrett's Claude Code session activity into the Gmor45/Skyne repo — mechanical model/effort audit, a terse judged grade of how well each session was prompted, and a self-eval of his own decision/communication/focus patterns. Use when the nightly session-digest scheduled task fires, or when Garrett asks to run or backfill the digest manually. This skill does not contain the procedure — it fetches it.
---

# Session digest — pointer

**This skill is a pointer, not the procedure.** The real, current one lives in
the private `Gmor45/Skyne` repo at `.claude/skills/session-digest/SKILL.md`.

That placement is not incidental: the digest's whole output is grades and
self-eval notes about Garrett's own working patterns, which belong in a private
repo. This pointer is the only part that is public, and it deliberately carries
none of it.

## Do this, in order

1. **Get a clone of `Gmor45/Skyne`, and `git pull` it first.** On Garrett's
   desktop the digest's own clone is `C:/Users/gmoor/claude-audit` — the
   directory name is deliberately stale because the HUD bridge finds it that
   way, so do not rename it. Elsewhere:

   ```
   gh repo clone Gmor45/Skyne
   ```

2. **Read the real procedure from that clone, in full, and follow it exactly:**

   ```
   <clone>/.claude/skills/session-digest/SKILL.md
   ```

   That file governs the heartbeat open/close, which sessions count as new,
   the mechanical fields, the grading basis, the merge-not-rebuild rule for
   `data/sessions-index.json`, and landing the digest by pull request.
   **`main` rejects a direct push** — branch and PR.

3. **The repo file wins on any disagreement**, for the rest of the session.

## Why this file is this short

The account-level *copy* this replaces was measured stale twice: two days
behind on 2026-08-29 with the heartbeat step missing entirely, and four days
behind on 2026-09-11 missing four separate changes. The scheduled task had
grown a hand-written paragraph telling whoever ran it to diff the two copies
and follow the repo's — which is a pointer, done by hand, every night. This is
that, done once.
