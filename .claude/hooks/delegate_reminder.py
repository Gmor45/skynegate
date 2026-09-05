#!/usr/bin/env python3
"""UserPromptSubmit hook: notice a mechanical-shaped prompt and say so, once.

WHY THIS EXISTS
---------------
House-rules rule 2 already names the "down" tells in plain English: moving or
renaming files, running a script, formatting, applying an already-decided
change, sweeping the same edit across many files. Garrett asked (2026-09-05)
for these to route to a cheaper model automatically, the way he assumed an MCP
tool could. It can't — `anthropics/claude-code#17772` is still open, no hook or
MCP primitive can INITIATE a model switch or spawn a subagent on its own. What
a hook CAN do is the other half of the miss: not the switching, the *noticing*.
Rule 2's own tells were sitting in prose, re-judged from scratch every turn,
exactly the `convention-no-mechanism` shape rule 21 names as the estate's
largest failure class.

WHAT IT DOES
------------
On every `UserPromptSubmit`, scan the prompt text for rule 2's own mechanical
tells. On a hit, print one line of context naming the `haiku-mechanic` subagent
(`.claude/agents/haiku-mechanic.md`, shipped in this same plugin) as an option Fable
Claude Code can pick up and use — plain stdout on exit 0 is added as additional
context for this hook type, the same contract `desk_state.py announce` already
uses in Gartera-Vault for its own UserPromptSubmit hook.

**It is a suggestion, never a switch.** It cannot spawn the Agent call itself —
nothing can, from a hook — so acting on it is still a judgment made in the
turn that reads it. That is a real, named limit, not an oversight: see WHAT
THIS CANNOT DO below.

WHY KEYWORDS AND NOT SEMANTIC JUDGEMENT
----------------------------------------
A hook has no model in the loop (`check_ai_optional.py` would fail one that
did) and runs before any turn has read the prompt, so "mechanical" here is a
fixed, narrow phrase list lifted verbatim from rule 2's own text — not a
guess at what mechanical means. That is deliberately conservative: it will
miss mechanical-shaped prompts phrased differently (a false negative), and it
will occasionally fire on a prompt that only uses one of these words in
passing (a false positive). Both are named here rather than hidden — rule 21
point 5 — and the fix for either is the same: extend TELLS with a matched
case in the self-test, not "make it smarter."

**Suppressed when an "up" tell is also present.** Rule 2 names architecture,
visual/spatial layout, and 3+ conflicting constraints as tells for the
OPPOSITE direction. A prompt naming both is not this hook's call to make, so
it stays silent rather than nag a real design ask because it also happens to
mention "renaming a variable."

ONCE PER SESSION, NOT EVERY MATCHING PROMPT
--------------------------------------------
Same shape as `turn_counter.py`'s per-session state file. A reminder repeated
on every mechanical-sounding message becomes exactly the noise rule 0b warns
about — tuned out, which defeats the mechanism as surely as never firing does.
Keyed on `transcript_path` so a new chat gets the reminder again once.

FAIL OPEN, ALWAYS
------------------
Every error path — no stdin, unparsable JSON, no prompt text, an unwritable
state dir — prints nothing and exits 0. A hook that can break prompt
submission over a keyword scan has its priorities backwards, same standard
every other hook in this plugin holds itself to.

Usage:
    python3 delegate_reminder.py                 # the hook (JSON on stdin)
    python3 delegate_reminder.py --check "text"  # dry-run one prompt string
    python3 delegate_reminder.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

# Verbatim from house-rules rule 2's "down" tells. Each is a phrase a human
# would actually type, not a topic keyword — "format" alone would fire on any
# mention of a file format, so entries here are the multi-word shapes rule 2
# itself uses.
TELLS = [
    r"\bmov(e|ing)\b.{0,20}\bfiles?\b",
    r"\brenam(e|ing)\b.{0,20}\bfiles?\b",
    r"\brun\s+(the|this)\s+script\b",
    r"\bformat(ting)?\s+(the|this|these|all)\b",
    r"\bapply\s+(the|this)\s+(already[- ]?)?decided\b",
    r"\b(sweep|apply)\b.{0,30}\b(same|identical)\s+edit\b",
    r"\b(sweep|apply)\b.{0,30}\bacross\s+(many|all|every)\s+files?\b",
    r"\bsame\s+edit\s+(to|across|over)\s+every\b",
]

# Rule 2's own "up" tells — present, this hook has nothing useful to add.
UP_TELLS = [
    r"\barchitect(ure|ing)?\b",
    r"\bdesign\s+(the|a|this)\b",
    r"\b3\+?\s*conflicting\s+constraints\b",
    r"\bvisual(ly)?[- ]?spatial\b",
]

TELL_RE = re.compile("|".join(TELLS), re.IGNORECASE)
UP_RE = re.compile("|".join(UP_TELLS), re.IGNORECASE)

STATE_DIR_ENV = "CLAUDE_PROJECT_DIR"


def state_dir() -> str:
    base = os.environ.get(STATE_DIR_ENV) or tempfile.gettempdir()
    return os.path.join(base, ".claude", "state", "delegate_reminder")


def state_path(transcript_path: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_-]", "_", transcript_path or "no-transcript")[-120:]
    return os.path.join(state_dir(), key + ".json")


def already_shown(transcript_path: str) -> bool:
    try:
        with open(state_path(transcript_path), encoding="utf-8") as f:
            return bool(json.load(f).get("shown"))
    except (OSError, ValueError):
        return False


def record_shown(transcript_path: str) -> None:
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(state_path(transcript_path), "w", encoding="utf-8") as f:
            json.dump({"shown": True}, f)
    except OSError:
        pass  # best effort; a lost state file just re-reminds once more


MESSAGE = (
    "This prompt matches house-rules rule 2's own \"mechanical\" tells "
    "(moving/renaming files, running a script, formatting, applying an "
    "already-decided change, sweeping one edit across many files). Consider "
    "Agent(subagent_type=\"load-house-rules:haiku-mechanic\") instead of "
    "doing it inline on the current model — nothing can spawn that call "
    "automatically (anthropics/claude-code#17772), this is only the reminder "
    "rule 21 says a hook should carry. Shown once per session."
)


def decide(prompt_text: str) -> str | None:
    """The message, or None. Pure and transcript-free so the self-test
    exercises the real logic rather than a copy of it."""
    if not prompt_text:
        return None
    if not TELL_RE.search(prompt_text):
        return None
    if UP_RE.search(prompt_text):
        return None
    return MESSAGE


def self_test() -> int:
    fails = []

    positives = [
        "Can you move these 40 files into the archive folder",
        "Please rename the files to match the new convention",
        "Run the script scripts/build.py against every note",
        "Format all of these the same way as the others",
        "Apply the already decided change from yesterday across the repo",
        "Sweep the same edit across every file in scripts/",
        "Apply the identical edit across all files in changelog.d/",
    ]
    for text in positives:
        if decide(text) is None:
            fails.append(f"should have matched a mechanical tell: {text!r}")

    negatives = [
        "What do you think of this campaign arc structure?",
        "Why is the dashboard rendering blank on mobile?",
        "Can we design the architecture for the new console?",
        "",
        None,
    ]
    for text in negatives:
        if decide(text) is not None:
            fails.append(f"should NOT have matched: {text!r}")

    # an "up" tell must suppress even a real "down" tell in the same prompt
    mixed = "Let's design the architecture, then run the script to apply it"
    if decide(mixed) is not None:
        fails.append("an architecture tell present must suppress the reminder")

    # state file: shown once, then suppressed, in a throwaway directory so
    # this never touches the real state dir
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[STATE_DIR_ENV] = tmp
        transcript = "session-abc"
        if already_shown(transcript):
            fails.append("a fresh session must not already be marked shown")
        record_shown(transcript)
        if not already_shown(transcript):
            fails.append("recording shown must make already_shown true")
        # a different transcript is a different session
        if already_shown("session-xyz"):
            fails.append("shown state must be keyed per transcript, not global")
    os.environ.pop(STATE_DIR_ENV, None)

    # fail-open: an unwritable dir must not raise
    try:
        os.environ[STATE_DIR_ENV] = "/this/path/cannot/exist/at/all"
        record_shown("whatever")  # must not raise
    finally:
        os.environ.pop(STATE_DIR_ENV, None)

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print(f"self-test: {len(positives) + len(negatives) + 5} cases passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        text = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        msg = decide(text)
        print(msg if msg else "(no match)")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
    except Exception:
        sys.exit(0)  # fail open: no stdin, no reminder, no error

    try:
        payload = json.loads(raw) if raw else {}
    except ValueError:
        sys.exit(0)  # fail open: unparsable stdin

    if not isinstance(payload, dict):
        sys.exit(0)

    prompt_text = payload.get("prompt") or ""
    transcript_path = payload.get("transcript_path") or ""

    try:
        if already_shown(transcript_path):
            sys.exit(0)
        msg = decide(prompt_text)
        if msg is None:
            sys.exit(0)
        record_shown(transcript_path)
        print(msg)
    except Exception:
        sys.exit(0)  # fail open: never let a reminder break prompt submission

    sys.exit(0)


if __name__ == "__main__":
    main()
