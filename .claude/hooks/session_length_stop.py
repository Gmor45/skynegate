#!/usr/bin/env python3
"""session_length_stop.py — house-rules 3a's threshold, enforced rather than
announced. A UserPromptSubmit hook that blocks the next prompt once a chat is
long enough that Garrett should have run /handoff already.

WHY THIS EXISTS
---------------
`turn_counter.py` already fires on `Stop` and tells Claude to say the turn
count and run `/handoff`. It works, and it deliberately never blocks anything
— "a counter that can trap a session is worse than no counter." Measured
anyway (`skyne/2026-09-04-session-length-is-the-lever-not-the-model.md`): one
session, 5,903 turns, was about half of all re-send cost this estate has ever
incurred, and house-rules rule 3's own recorded failure is a session that
*said* the chat should end four times and never ran the handoff. A nag that
can always be talked past by simply continuing is exactly the mechanism that
produced both numbers.

So this is the other half, on the other event. `turn_counter.py` fires after
Claude answers and can only ask; this fires before Claude sees the NEXT
prompt and can actually refuse it. Session length is house-rules 3a's single
largest measured cost lever (~59% of total re-send cost, capped at ~1,000
turns) and, unlike model choice, it is the one lever a hook can act on
directly — nothing here needs Garrett to type `/model`.

WHY IT IS A SOFT LOCK, NOT A HARD ONE
--------------------------------------
Ruled 2026-09-10, same reasoning as house-rules 2a's 2026-09-09 amendment: a
mechanism that trusts its own count blindly has no way out when the count is
wrong. `count_turns()` is heuristic (it reads transcript shape, not Garrett's
intent), and a hard block with no exit would turn one miscount into a trapped
session — worse than the thing rule 3a is trying to save. So: past the
threshold, the prompt is refused UNLESS it names the override phrase or is
itself the prompt that runs `/handoff` — the same shape rule 2a already
moved to ("say the override phrase, no argument, no second ask").

WHY IT REUSES turn_counter.py RATHER THAN RE-COUNTING
--------------------------------------------------------
Both files ship in this same plugin directory, so — unlike skyne's
session_cost.py, which cannot import a plugin hook and carries its own copy
of THRESHOLD by necessity — there is no reason for a second implementation of
"how many real user turns are in this transcript" to exist here. This module
imports turn_counter's read_transcript/count_turns/band_for/THRESHOLD/
REPEAT_EVERY directly. One counting definition; two hooks acting on it.

WHAT IT DOES
------------
Below `turn_counter.THRESHOLD` (1,000 turns): always allows, no state touched
at all — this hook does nothing until turn_counter has already been nagging
for 400 turns.

At or above it: blocks (exit 2, reason on stderr — the documented primary
block method for UserPromptSubmit) UNLESS the submitted prompt:

  - contains the override phrase (OVERRIDE_RE) — allowed, and the current
    band is recorded as unlocked, so the REST of that band (up to the next
    500-turn crossing) proceeds without re-asking; or
  - is itself asking Claude to run the handoff (HANDOFF_RE) — allowed, but
    NOT recorded as an override, because the point is to let the escape
    hatch through, not to grant a free pass past it. If the session
    continues after that prompt without the chat actually ending, the very
    next ordinary prompt is blocked again.

Bands repeat every turn_counter.REPEAT_EVERY (500) turns past the threshold,
mirroring turn_counter's own "once per band, never again until the next one"
idiom — proven here already rather than invented fresh.

FAIL OPEN, ALWAYS
------------------
Every error path — no stdin, unparsable JSON, no transcript path, an
unreadable transcript, an unwritable state dir — allows silently. Nothing
here may ever refuse a prompt for a reason unrelated to the count itself; a
hook that can break prompt submission over its own bug is a worse failure
than the cost it exists to prevent.

Usage:
    python3 session_length_stop.py                          # the hook
    python3 session_length_stop.py --check "text" --turns N # dry run
    python3 session_length_stop.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import turn_counter  # noqa: E402 — sibling hook in the same plugin dir

# The override phrase. Distinct enough not to appear in ordinary conversation
# about session length — same design goal as rule 2a's "stay on Opus".
OVERRIDE_RE = re.compile(r"\boverride\s+session\s+length\b", re.IGNORECASE)

# Never block the escape hatch itself. Matches the slash command and the
# plain word, so "run the handoff", "/handoff", "handoff this session" all
# get through as a one-time bypass rather than a recorded override.
HANDOFF_RE = re.compile(r"\bhand[- ]?off\b", re.IGNORECASE)


def state_dir() -> str:
    """Deliberately its own directory, not turn_counter's — a different
    mechanism (an unlock Garrett must actively grant, not an announcement
    Claude makes) sharing a file would make one file's meaning ambiguous."""
    home = os.path.expanduser("~")
    if not home or home == "~" or not os.access(home, os.W_OK):
        home = tempfile.gettempdir()
    return os.path.join(home, ".session-stop")


def state_path(transcript_path: str) -> str:
    import hashlib
    key = hashlib.sha256((transcript_path or "").encode()).hexdigest()[:16]
    return os.path.join(state_dir(), "unlock-%s.json" % key)


def overridden_band(transcript_path: str) -> int:
    """The highest band Garrett has already unlocked for this session, or 0.

    Same fail-toward-blocking-less-often stance as turn_counter's
    already_announced: unreadable state reads as "nothing unlocked yet",
    because the cost of re-asking once is one blocked prompt and the cost of
    the other direction is the lock never actually holding.
    """
    try:
        with open(state_path(transcript_path), encoding="utf-8") as f:
            return int(json.load(f).get("band", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 0


def record_unlock(transcript_path: str, band: int) -> None:
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(state_path(transcript_path), "w", encoding="utf-8") as f:
            json.dump({"band": int(band)}, f)
    except OSError:
        pass  # best effort; a lost state file just re-asks once more


def message(turns: int, band: int, threshold: int = turn_counter.THRESHOLD) -> str:
    over = turns / float(threshold)
    return (
        "SESSION LENGTH (house-rules 3a) — this chat is at about %d turns, "
        "%.1fx the ~%s-turn threshold. This prompt is blocked rather than "
        "just flagged, because rule 3's recorded failure is a session that "
        "said the chat should end and kept going anyway.\n\n"
        "To continue anyway, resend this prompt with the phrase "
        "\"override session length\" in it — that unlocks the next %d turns, "
        "not the rest of the chat, so it will ask again after that.\n\n"
        "The other option: ask Claude to run the /handoff skill. That "
        "prompt is never blocked."
        % (turns, over, "{:,}".format(threshold), turn_counter.REPEAT_EVERY)
    )


def decide(entries, transcript_path: str, prompt_text: str):
    """(blocked: bool, reason: str|None, turns, band) — the whole verdict,
    transcript-free above the read so the self-test exercises the real
    function rather than a copy of it."""
    turns = turn_counter.count_turns(entries)
    band = turn_counter.band_for(
        turns,
        threshold=turn_counter.THRESHOLD,
        warn_at=turn_counter.THRESHOLD,  # this hook has no pre-threshold band
        repeat=turn_counter.REPEAT_EVERY,
    )
    if band is None:
        return False, None, turns, None

    prompt_text = prompt_text or ""
    if HANDOFF_RE.search(prompt_text):
        return False, None, turns, band  # one-time bypass, nothing recorded

    if band <= overridden_band(transcript_path):
        return False, None, turns, band  # already unlocked for this band

    if OVERRIDE_RE.search(prompt_text):
        record_unlock(transcript_path, band)
        return False, None, turns, band

    return True, message(turns, band), turns, band


def self_test() -> int:
    fails = []

    def u(**kw):
        return dict({"type": "user"}, **kw)

    below = [u() for _ in range(999)]
    blocked, reason, turns, band = decide(below, "/fake/a.jsonl", "carry on")
    if blocked or band is not None:
        fails.append("below threshold must never block, regardless of prompt text")

    over = [u() for _ in range(1200)]
    blocked, reason, turns, band = decide(over, "/fake/a.jsonl", "carry on please")
    if not blocked or band != 1000:
        fails.append("at 1,200 turns an ordinary prompt must be blocked, band 1000")
    if reason is None or "1200" not in reason or "override session length" not in reason:
        fails.append("the block reason must name the count and the override phrase")

    # the override phrase unlocks, and PERSISTS for the rest of the band
    import tempfile as _tf
    real_home = os.environ.get("HOME")
    with _tf.TemporaryDirectory() as tmp:
        os.environ["HOME"] = tmp
        try:
            path = "/fake/transcript/x.jsonl"
            blocked, _, _, band = decide(over, path, "let's override session length please")
            if blocked:
                fails.append("the override phrase must unlock the prompt that carries it")
            blocked2, _, _, _ = decide(over, path, "carry on, nothing special here")
            if blocked2:
                fails.append("once unlocked, the SAME band must not re-ask on the next "
                              "ordinary prompt")

            # crossing into the NEXT band must ask again
            much_more = [u() for _ in range(1600)]
            blocked3, _, _, band3 = decide(much_more, path, "keep going")
            if not blocked3 or band3 != 1500:
                fails.append("the next band (1,500) must still block after the "
                              "previous band was unlocked, or the lock never re-arms")

            # a different session must not inherit another's unlock
            other = "/fake/transcript/y.jsonl"
            blocked4, _, _, _ = decide(over, other, "carry on")
            if not blocked4:
                fails.append("unlock state is per-session; another transcript must "
                              "still be blocked")

            # the handoff bypass never records an unlock — the NEXT ordinary
            # prompt in the same band must still block
            path2 = "/fake/transcript/z.jsonl"
            blocked5, _, _, _ = decide(over, path2, "please run /handoff now")
            if blocked5:
                fails.append("a prompt asking to run /handoff must never be blocked")
            blocked6, _, _, _ = decide(over, path2, "ok now keep working on the feature")
            if not blocked6:
                fails.append("the handoff bypass must NOT unlock the band — it is a "
                              "one-time pass for that one prompt, not a recorded override")

            # an unwritable state dir must not raise, and must fail toward blocking
            os.environ["HOME"] = os.path.join(tmp, "does-not-exist-and-cannot")
            blocked7, reason7, _, _ = decide(over, path, "carry on")
            if not blocked7:
                fails.append("with no readable/writable state the gate must still "
                              "block an ordinary over-threshold prompt")
        finally:
            if real_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = real_home

    # empty/missing prompt text must not crash and must still block
    blocked8, _, _, _ = decide(over, "/fake/transcript/w.jsonl", "")
    if not blocked8:
        fails.append("an empty prompt at band 1000 must still be blocked")
    blocked9, _, _, _ = decide(over, "/fake/transcript/w2.jsonl", None)
    if not blocked9:
        fails.append("a None prompt must not crash decide() and must still block")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: 11 cases passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        text = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        turns = 0
        if "--turns" in sys.argv:
            tidx = sys.argv.index("--turns")
            turns = int(sys.argv[tidx + 1]) if tidx + 1 < len(sys.argv) else 0
        entries = [{"type": "user"} for _ in range(turns)]
        blocked, reason, t, band = decide(entries, "/dev/null", text)
        print("BLOCKED" if blocked else "ALLOWED", "turns=%d band=%r" % (t, band))
        if reason:
            print(reason)
        sys.exit(0)

    try:
        raw = sys.stdin.read()
    except Exception:
        sys.exit(0)  # fail open: no stdin, no block

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # fail open: unparsable stdin

    if not isinstance(payload, dict):
        sys.exit(0)

    transcript_path = payload.get("transcript_path") or ""
    prompt_text = payload.get("prompt") or payload.get("user_prompt") or ""

    if not transcript_path:
        sys.exit(0)  # fail open: cannot count turns with no transcript

    try:
        entries = turn_counter.read_transcript(transcript_path)
        if not entries:
            sys.exit(0)  # fail open: an empty/unreadable transcript never blocks
        blocked, reason, turns, band = decide(entries, transcript_path, prompt_text)
    except Exception:
        sys.exit(0)  # fail open: never let a bug here break prompt submission

    if not blocked:
        sys.exit(0)

    sys.stderr.write(reason + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
