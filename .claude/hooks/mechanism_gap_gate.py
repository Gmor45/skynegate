#!/usr/bin/env python3
"""Stop hook: catch rule 21 being diagnosed and not acted on, in the same turn.

WHY THIS EXISTS
---------------
Garrett, 2026-09-10, after being handed a correct diagnosis of a real gap (the
tool that creates a scheduled Routine has no parameter for attaching a repo)
with the fix offered only as a Recommendation, not built: *"I had to ask you
to build this and verify it works you're supposed to do that always. That's a
miss. I wonder if it's even fixable truly."*

It is the exact rule the session had loaded minutes earlier, verbatim: house
rule 21 -- "A rule with no mechanism is a hypothesis. When one is broken,
build the mechanism -- do not restate the rule." Filed as
`2026-09-10-diagnosed-the-create-trigger-repo-connec...` in the miss ledger,
mechanism `convention-no-mechanism`, why `knew-didnt-connect` -- the rule was
known and loaded, and nothing tied it to the moment of acting.

WHY THIS IS NARROW, NOT "ALWAYS BUILD INSTEAD OF RECOMMENDING"
------------------------------------------------------------------
A blanket gate against offering a recommendation would be wrong and would get
deleted fast: house rule 26 already carves out that a recommendation is
correct when the decision genuinely is Garrett's (a GitHub permission only he
can grant is exactly that shape, and this session's own reply naming it was
right to). Measured before trusting a phrase list: bare "no mechanism" appears
in **47** of this repo's own dated reports -- it is rule 21's own vocabulary,
used constantly to describe gaps that were ALREADY fixed in the same report.
Gating on it would fire on nearly every retrospective in this repo. So this
hook matches a much narrower set of phrases that name a concrete, checkable
absence (a missing parameter, field or setting) rather than the word
"mechanism" itself -- each occurs 0-6 times across the corpus, not 47.

WHAT IT REFUSES
----------------
The final reply of a turn contains one of the narrow trigger phrases (see
TRIGGERS below), AND neither escape condition holds:

  1. This turn's own tool calls include something that actually builds or
     changes something (Write, Edit, MultiEdit, NotebookEdit, Bash) -- rule 21
     was connected to action, whatever the reply goes on to say about it.
  2. The reply text itself names what is needed FROM GARRETT SPECIFICALLY
     (a dependency phrase: "your call", "only you can", "requires your",
     "needs your", "grant access", "up to you") -- the honest case rule 26
     already sanctions.

WHAT IT DELIBERATELY LETS THROUGH
-----------------------------------
Every reply that does not name one of the narrow triggers, including ones
using rule 21's own broad vocabulary ("no mechanism", "unenforced",
"hypothesis") to discuss something already fixed or already decided elsewhere.
That is a deliberate, named gap, not an oversight -- rule 21 point 5.

NO OVERRIDE, ON PURPOSE
------------------------
Same reasoning as `no_push_to_main.py`. If building right now is genuinely
wrong (needs a design call, is out of scope, is expensive), that is escape
condition 2 -- name it to Garrett -- not a flag Claude sets on itself.

WHAT IT CANNOT SEE, STATED PLAINLY
-------------------------------------
It is a phrase scan over the CURRENT turn's transcript slice, not a judgement
about whether the diagnosis was even correct or whether "built it" actually
worked. A reply that phrases the identical failure without hitting one of
these strings is invisible to it -- a false negative rule 21 point 5 accepts
rather than hides. And it cannot verify the fix works; that is still on
whoever writes the self-test, same as every other hook in this plugin.

Usage:
    python3 mechanism_gap_gate.py                    # the hook (JSON on stdin)
    python3 mechanism_gap_gate.py --self-test
"""
from __future__ import annotations

import json
import re
import sys

TRIGGERS = [
    "no parameter for", "has no parameter", "no way to attach",
    "structural gap", "no field for", "doesn't have a field",
    "no setting for", "isn't something you're doing wrong",
    "not something you're doing wrong",
]
TRIGGER_RE = re.compile(
    "(" + "|".join(re.escape(t) for t in TRIGGERS) + ")", re.IGNORECASE
)

BUILD_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"}

DEPENDENCY_PHRASES = [
    "your call", "only you can", "requires your", "needs your",
    "grant access", "up to you", "your decision", "your github",
    "you'll need to", "you will need to",
]
DEPENDENCY_RE = re.compile(
    "(" + "|".join(re.escape(p) for p in DEPENDENCY_PHRASES) + ")", re.IGNORECASE
)


def read_transcript(path):
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


def last_user_boundary(entries):
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (
            e.get("type") == "user"
            and not e.get("isMeta")
            and not e.get("toolUseResult")
            and not e.get("isSidechain")
        ):
            return i
    return -1


def tools_used(entries, boundary):
    names = set()
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                n = blk.get("name")
                if n:
                    names.add(n)
    return names


def reply_text(entries, boundary):
    out = []
    for e in entries[boundary + 1:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                out.append(blk.get("text") or "")
    return "\n".join(out).strip()


def verdict(text: str, tools: set[str]) -> str | None:
    """The refusal reason, or None to allow. Pure, so the self-test exercises
    the real function without touching a transcript file."""
    if not text:
        return None
    hit = TRIGGER_RE.search(text)
    if not hit:
        return None
    if tools & BUILD_TOOLS:
        return None
    if DEPENDENCY_RE.search(text):
        return None
    return (
        f"Refused: this reply names a gap ({hit.group(0)!r}) the way house-"
        f"rule 21 describes -- a mechanism that does not exist -- but this "
        f"turn made no build attempt (no Write/Edit/Bash) and does not say "
        f"what specifically is needed from Garrett.\n"
        f"Rule 21: when a rule or a gap is found broken, build the mechanism "
        f"in the same turn, or say plainly what only Garrett can decide and "
        f"why. A recommendation that could have been an attempt is the exact "
        f"miss filed 2026-09-10 (mechanism convention-no-mechanism, why "
        f"knew-didnt-connect).\n"
        f"There is deliberately no override."
    )


def self_test() -> int:
    fails = []

    def refuse(text, tools, why):
        if verdict(text, tools) is None:
            fails.append(f"must REFUSE ({why}): {text!r} tools={tools}")

    def allow(text, tools, why):
        if verdict(text, tools) is not None:
            fails.append(f"must ALLOW ({why}): {text!r} tools={tools}")

    refuse(
        "The dialog has no parameter for repos or connectors, so a Routine "
        "silently starts without either.",
        set(),
        "trigger phrase, no build tool, no dependency phrase",
    )
    refuse(
        "This tool has no field for source repos.",
        {"Read", "Grep"},
        "non-build tools present must not count as an attempt",
    )
    refuse(
        "There is no setting for this in the dialog.",
        set(),
        "another trigger phrase",
    )

    allow(
        "The dialog has no parameter for repos, so I wrote and self-tested "
        "a hook that catches it.",
        {"Write", "Bash"},
        "a real build attempt this turn",
    )
    allow(
        "The tool has no field for this -- only you can grant the GitHub "
        "access that would let me ship it.",
        set(),
        "names what is needed from Garrett specifically",
    )
    allow(
        "Rule 21 already covers this: a rule with no mechanism is a "
        "hypothesis, and convention-no-mechanism is the largest failure "
        "class in the ledger.",
        set(),
        "the broad, excluded phrase 'no mechanism' must never trigger",
    )
    allow(
        "Filed the miss and built the fix; nothing was structurally wrong "
        "here, just late.",
        {"Bash"},
        "no trigger phrase present at all",
    )
    allow("", set(), "empty reply text")
    allow(
        "There is no field for it, but I already committed the fix in a "
        "prior message this same turn.",
        {"Edit"},
        "Edit counts as a build tool",
    )

    # the refusal text has to name the actual rule and the actual filed miss
    reason = verdict("This has no field for it.", set())
    for must in ("rule 21", "no override"):
        if must.lower() not in (reason or "").lower():
            fails.append(f"refusal text must contain {must!r}")

    # the emitted payload must be a deny shape the harness understands
    payload = deny_payload("because")
    hso = payload.get("hookSpecificOutput", {})
    if hso.get("hookEventName") != "Stop":
        fails.append("deny payload must name the Stop event")
    if hso.get("permissionDecision") != "deny":
        fails.append("deny payload must carry permissionDecision=deny")

    # must not raise on garbage input
    try:
        verdict(None, set())  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover
        fails.append(f"must not raise on None text: {exc}")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: 13 cases passed")
    return 0


def deny_payload(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)  # fail open: no stdin, or unparsable

    if not isinstance(payload, dict):
        sys.exit(0)

    transcript_path = payload.get("transcript_path") or ""
    entries = read_transcript(transcript_path)
    if not entries:
        sys.exit(0)  # fail open: no transcript to read

    boundary = last_user_boundary(entries)
    text = reply_text(entries, boundary)
    tools = tools_used(entries, boundary)

    try:
        reason = verdict(text, tools)
    except Exception:
        sys.exit(0)  # fail open: never trap a session over a string scan

    if reason:
        print(json.dumps(deny_payload(reason)))
    sys.exit(0)


if __name__ == "__main__":
    main()
