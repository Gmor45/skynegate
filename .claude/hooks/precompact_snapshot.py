#!/usr/bin/env python3
"""PreCompact + SessionStart(compact): keep Garrett's exact words across a compaction.

WHY THIS EXISTS
---------------
house-rules' memory-bank section already names this failure precisely:

    "Past a certain size a chat's earlier turns get summarised. A handoff
     written after that is a summary of a summary, and what goes first is
     precision — exact field names, measured counts, and his exact words.
     That is the part nobody can reconstruct later."

There is a hook that fires at exactly that moment. Nothing used it. Found
2026-09-05 by enumerating the platform surface from the docs instead of from
memory — `skyne/data/surfaces.json`, which was written because two consecutive
attempts to answer "what else could we do?" both missed 27 unused events.

WHAT IT DOES, AND THE ONE THING IT REFUSES TO DO
-------------------------------------------------
On `PreCompact` it copies the irreplaceable parts of the transcript to a file
that outlives the context window: **Garrett's own turns, verbatim**, plus the
measured numbers and the paths touched.

**It does not summarise, and that is the whole design.** Compaction is already
a summariser; a hook that fires just before it and writes its own summary has
preserved nothing that was about to be lost. So this copies text exactly as
written and truncates by DROPPING WHOLE TURNS, counting what it withheld —
never by paraphrasing. An honest gap beats a smooth reconstruction.

WHY IT IS A PAIR, NOT ONE HOOK
-------------------------------
`PreCompact` can deny and observe. It **cannot inject context** — so a snapshot
written by it alone is a file nobody opens, which is the failure this estate
has measured at scale (226 pins captured and never resurfaced; "anything you
split needs a digest, or you have converted a legible file into a silent
backlog").

So the second half is a `SessionStart` hook with `matcher: "compact"`, which
re-fires after compaction and CAN inject. It prints where the snapshot is and
what is in it. Neither half is useful alone, which is why they are one file.

IT NEVER BLOCKS
---------------
`PreCompact` can refuse a compaction. This does not, ever. Blocking compaction
strands a session with a full context window and no way forward — strictly
worse than a lost nuance. Same argument `model_switch.py` makes for leaving
`PreModelSwitch`'s block unused: a capability is not a reason.

WHAT IT CANNOT DO, STATED PLAINLY
----------------------------------
It cannot tell which parts mattered — it preserves a category (his words), not
an importance judgement, because judging importance is the thing that goes
wrong under compaction in the first place. It cannot help a session whose
transcript path it was not given. And the snapshot is per-machine, under
`~/.claude/`, so it does not travel to another surface: this narrows the loss,
it does not abolish it.

Usage:
    python3 precompact_snapshot.py                 # PreCompact (JSON on stdin)
    python3 precompact_snapshot.py --announce      # SessionStart matcher:compact
    python3 precompact_snapshot.py --self-test
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys

DEFAULT_DIR = pathlib.Path.home() / ".claude" / "skyne" / "precompact"
ENV_DIR = "SKYNE_PRECOMPACT_DIR"

# Keep the newest N of Garrett's turns. Chosen so the file stays readable in one
# sitting; anything dropped is COUNTED in the header rather than quietly lost.
MAX_TURNS = 40
MAX_CHARS_PER_TURN = 4000

# A "measured count" in this estate's sense: a bare number with a unit or a
# ratio, not every digit that appears in a path or a date.
NUMBER_RE = re.compile(
    r"\b\d+\s*(?:of|/)\s*\d+\b"          # 9 of 33, 69/72
    r"|\b\d+\s*(?:%|percent|lines?|files?|turns?|minutes?|commits?|rows?|cases?"
    r"|events?|hooks?|promises?|checks?|sessions?|pins?|repos?|agents?|tokens?)\b"
    r"|\b\d+\.\d+\s*(?:%|x)\b",
    re.IGNORECASE)


def snap_dir() -> pathlib.Path:
    override = os.environ.get(ENV_DIR, "").strip()
    return pathlib.Path(override) if override else DEFAULT_DIR


def read_transcript(path):
    """Same tolerant read turn_counter.py uses — a half-written tail line is
    normal when another process is appending, and must not lose the rest."""
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


def is_real_user_turn(e):
    """reply_gate's predicate, third copy, deliberately. Tool results, meta
    entries and subagent prompts all arrive as user-type entries; a naive
    type=='user' test would fill the snapshot with tool output, which is the
    one thing already reproducible from disk."""
    return (isinstance(e, dict)
            and e.get("type") == "user"
            and not e.get("isMeta")
            and not e.get("toolUseResult")
            and not e.get("isSidechain"))


def text_of(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    out = []
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "text":
            out.append(blk.get("text") or "")
    return "\n".join(out).strip()


def paths_touched(entries):
    """Files this session actually wrote. Reconstructable from git in principle,
    but not from a compacted context, and it is one line to keep."""
    seen = []
    for e in entries:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if not (isinstance(blk, dict) and blk.get("type") == "tool_use"):
                continue
            if blk.get("name") not in ("Edit", "Write", "NotebookEdit"):
                continue
            p = (blk.get("input") or {}).get("file_path")
            if p and p not in seen:
                seen.append(p)
    return seen


def measurements(turns):
    """Numbers from Garrett's own words. His measured counts are the half a
    summary rounds off."""
    found = []
    for t in turns:
        for line in t.splitlines():
            if NUMBER_RE.search(line) and line.strip() not in found:
                found.append(line.strip())
    return found


def build(entries, when=None, trigger="auto"):
    """The snapshot text. Pure, so the self-test exercises the real thing."""
    when = when or dt.datetime.now()
    all_turns = [text_of(e) for e in entries if is_real_user_turn(e)]
    all_turns = [t for t in all_turns if t]
    dropped = max(0, len(all_turns) - MAX_TURNS)
    kept = all_turns[-MAX_TURNS:]

    out = [
        f"# Pre-compaction snapshot — {when:%Y-%m-%d %H:%M}",
        "",
        f"Compaction trigger: {trigger}. "
        f"Garrett's turns: {len(all_turns)} total, {len(kept)} kept"
        + (f", **{dropped} older turns dropped**." if dropped else "."),
        "",
        "Written verbatim. Nothing here is summarised — the summary is what",
        "compaction already produced, and precision is what it costs.",
        "",
        "## His words, exactly",
        "",
    ]
    for i, t in enumerate(kept, 1):
        body = t
        if len(body) > MAX_CHARS_PER_TURN:
            cut = len(body) - MAX_CHARS_PER_TURN
            body = body[:MAX_CHARS_PER_TURN] + f"\n[... {cut} more chars in this turn]"
        out += [f"### {i}.", "", "> " + body.replace("\n", "\n> "), ""]

    nums = measurements(kept)
    if nums:
        out += ["## Measured counts he stated", ""]
        out += [f"- {n}" for n in nums]
        out += [""]

    paths = paths_touched(entries)
    if paths:
        out += [f"## Files written this session ({len(paths)})", ""]
        out += [f"- `{p}`" for p in paths]
        out += [""]
    return "\n".join(out)


def write_snapshot(text, session_id, when=None):
    when = when or dt.datetime.now()
    d = snap_dir()
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "unknown")[-60:]
    path = d / f"{when:%Y%m%d-%H%M%S}-{safe}.md"
    path.write_text(text, encoding="utf-8")
    (d / "LATEST").write_text(str(path), encoding="utf-8")
    return path


def announce():
    """SessionStart(matcher: compact). PreCompact cannot inject context, so this
    is the half that makes the snapshot reachable instead of merely written."""
    try:
        pointer = snap_dir() / "LATEST"
        target = pathlib.Path(pointer.read_text(encoding="utf-8").strip())
        if not target.is_file():
            return ""
        body = target.read_text(encoding="utf-8")
        turns = body.count("\n### ")
        head = body.splitlines()[2] if len(body.splitlines()) > 2 else ""
        return (
            "CONTEXT WAS JUST COMPACTED. Garrett's own words from before the "
            f"compaction were saved verbatim — {turns} turn(s):\n"
            f"    {target}\n"
            f"    {head}\n"
            "Read it BEFORE writing a handoff, a report, or any claim about "
            "what he said or asked for. What you are holding now is a summary; "
            "that file is not.")
    except (OSError, ValueError, IndexError):
        return ""


def self_test() -> int:
    import tempfile
    fails = []

    def u(text):
        return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}

    def tool(name, path):
        return {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": name, "input": {"file_path": path}}]}}

    entries = [
        u("Build the thing. 9 of 33 events are unused."),
        {"type": "user", "isMeta": True, "message": {"content": [{"type": "text", "text": "META"}]}},
        {"type": "user", "toolUseResult": {"x": 1},
         "message": {"content": [{"type": "text", "text": "TOOLRESULT"}]}},
        {"type": "user", "isSidechain": True,
         "message": {"content": [{"type": "text", "text": "SUBAGENT"}]}},
        tool("Write", "/tmp/a.py"),
        tool("Read", "/tmp/never.py"),
        u("Second thing."),
    ]
    text = build(entries, when=dt.datetime(2026, 9, 6, 1, 0))

    if "Build the thing." not in text or "Second thing." not in text:
        fails.append("both real user turns must be preserved verbatim")
    for noise in ("META", "TOOLRESULT", "SUBAGENT"):
        if noise in text:
            fails.append(f"{noise} is not a real user turn and must not be kept")
    if "/tmp/a.py" not in text:
        fails.append("a written file must be listed")
    if "/tmp/never.py" in text:
        fails.append("a Read is not a write and must not be listed")
    if "9 of 33" not in text:
        fails.append("a measured count in his words must be pulled out")
    # the unit list was too narrow on the first cut and missed this session's
    # own headline number — "33 hook events" read as prose, not a measurement
    if not measurements(["33 hook events exist"]):
        fails.append("a count with a domain unit (events) must be recognised")
    if measurements(["see /tmp/a1.py at 2026-09-06"]):
        fails.append("a path or a date is not a measured count")
    if "Garrett's turns: 2 total" not in text:
        fails.append("the header must count his turns")

    # truncation DROPS and COUNTS; it never paraphrases
    many = [u(f"turn {i}") for i in range(MAX_TURNS + 7)]
    t2 = build(many)
    if "7 older turns dropped" not in t2:
        fails.append("dropped turns must be counted in the header")
    if f"turn {MAX_TURNS + 6}" not in t2:
        fails.append("the NEWEST turns must be the ones kept")
    if "turn 0" in t2:
        fails.append("the oldest turns are the ones dropped")

    long_turn = build([u("x" * (MAX_CHARS_PER_TURN + 500))])
    if "more chars in this turn" not in long_turn:
        fails.append("an over-long turn must say how much it withheld")

    # write + announce round trip, in a temp dir
    with tempfile.TemporaryDirectory() as tmp:
        os.environ[ENV_DIR] = tmp
        try:
            p = write_snapshot(text, "session_abc")
            if not p.is_file():
                fails.append("the snapshot must be written")
            if not (pathlib.Path(tmp) / "LATEST").is_file():
                fails.append("LATEST must point at the newest snapshot")
            msg = announce()
            if "CONTEXT WAS JUST COMPACTED" not in msg or str(p) not in msg:
                fails.append("announce must name the snapshot path")
            if "2 turn(s)" not in msg:
                fails.append("announce must say how many turns are in it")
            # a missing pointer must be silent, never a crash or a lie
            (pathlib.Path(tmp) / "LATEST").unlink()
            if announce() != "":
                fails.append("no snapshot must announce nothing at all")
        finally:
            os.environ.pop(ENV_DIR, None)

    # every failure path is silent and exit-0
    if build([]) is None:
        fails.append("an empty transcript must still build")
    if read_transcript("/nonexistent/path") != []:
        fails.append("an unreadable transcript must return empty, not raise")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: 19 cases passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--announce" in sys.argv:
        try:
            msg = announce()
            if msg:
                print(msg)
        except Exception:
            pass
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            sys.exit(0)
        path = payload.get("transcript_path") or ""
        if not path:
            sys.exit(0)
        entries = read_transcript(path)
        if not entries:
            sys.exit(0)
        text = build(entries, trigger=payload.get("trigger") or "auto")
        write_snapshot(text, payload.get("session_id") or "")
    except Exception:
        pass  # fail open, always: never block a compaction over a snapshot
    sys.exit(0)


if __name__ == "__main__":
    main()
