#!/usr/bin/env python3
"""Stop hook: refuse to end a substantive turn without a plain-English closing block.

WHY THIS EXISTS
---------------
Garrett has asked for shorter, simpler answers more times than for anything
else, and it has never held. Two other formatting rules in the same preferences
block — "always include a TLDR" and "always include Recommendations" — hold
every time. The difference is not emphasis. It is that those two can be checked
by looking, and "be concise" cannot: it is re-judged every turn, and every turn
there is a local excuse ("this one was genuinely complicated").

So this gate does not ask for concise. It asks for a fixed closing block, which
is countable, and it refuses the stop until the block is there:

    **What I did**       plain English, no jargon
    **Why**              plain English, no jargon
    **Recommendations**  optional — only when there are real ones
    **TLDR**             one line

The body ABOVE that block may be as long and as technical as the work needs.
That is the point of the design: the technical layer stays, and the block makes
it optional to read. Length was never the complaint — having to read the length
to find the answer was.

CORRECTION 2026-09-03 — the block was right, the frequency was not
--------------------------------------------------------------------
This gate had no memory across turns: every substantive reply, forever, got
the closing block, because nothing here ever asked "did I just show this a
moment ago?" In a long working session almost every reply is substantive, so
Garrett got the block on nearly every message. Found in a Cowork session:
"its doing the TLDR What, Why, Recommendations like way too many times."

The block itself was never the complaint — it is what makes a long reply
skimmable, and that need has not gone away. The complaint was cadence. So the
structural requirement (What I did / Why / TLDR, in order, sized and
jargon-free) now runs on a COOLDOWN: required on the first substantive reply
of a session, then again only once COOLDOWN_TURNS more have passed. The
stock-phrase and echo-only-turn checks below are NOT on this cooldown — they
do not repeat the block, so exempting them the same way would hide a
different failure behind this one's fix. See COOLDOWN_TURNS.

WHAT IT CANNOT DO, STATED HONESTLY
----------------------------------
No script can tell whether prose is actually simple. This one checks structure
(sections present, in order), size (the block stays skimmable), and a banned
vocabulary list *inside the block only*. It will happily pass a badly-written
summary that has the right shape. That residue is uncovered, and pretending
otherwise would be worse than leaving it named — a check that passes on the
real failure converts an open problem into a solved one.

FAIL-OPEN, ALWAYS
-----------------
Every error path allows the stop. A gate that traps the model is worse than no
gate. The per-turn counter caps re-prompts below the CLI's global ceiling so a
turn that genuinely cannot satisfy it still gets to end.

DELIVERY — this gate cannot fire in a multi-repo remote session
---------------------------------------------------------------
CORRECTED 2026-09-02 (evening) — read this before the paragraph under it. The
outcome below is right; the cause given for it was wrong. This gate ships as a
PLUGIN hook (`hooks/hooks.json`), not through a repo's `.claude/settings.json`,
so the subdirectory explanation does not apply to it. Measured in a remote
multi-repo session: `~/.claude/plugins/synced` held only `marketplace.json` —
the plugin was simply not installed there — and the only Stop hook registered
was the platform's own git check. The subdirectory failure is real for the
REPO-registered hooks (the vault's SessionStart brief, `findings_gate.py`,
`trail.py hook`: none of their per-call artifacts existed after 158 vault
scripts had run). Two different causes, one outcome: nothing of Skyne's fires
on that surface. Filed as `2026-09-02-no-skyne-hook-fired-in-a-multi-repo-
remote-session` in the brain repo's miss ledger; a "hooks fired this session"
probe is the S6 work item that makes the hole visible instead of documented.

Measured 2026-09-02. This repo's hooks are registered in its own
`.claude/settings.json`. When a Claude Code session clones SEVERAL repos side
by side, the project directory is their PARENT, this file sits in a
subdirectory, and those settings are never loaded — the same failure already
documented for claude-audit's SessionStart hook.

So on the surface where Garrett does much of his work, this gate is inert while
looking installed. It caught the 2026-09-02 double-summary on shape when run by
hand and did not fire once during the session that produced it. Do not read a
clean session as evidence the gate is working; run `--self-test` to see whether
the CODE is right, and check the session type to know whether it can RUN.

"""

import json
import os
import re
import sys
import tempfile

# ---------------------------------------------------------------- constants

# Below this, a reply is a one-liner and needs no closing block. Set from the
# shape of the failure: nobody has ever complained that a 40-word answer was
# hard to skim.
TRIVIAL_WORDS = 60

# The closing block must stay skimmable. This is the number that makes
# "concise" countable instead of arguable.
SUMMARY_MAX_WORDS = 170

# Tools that, on their own, mean the turn did no work worth reporting. Kept as a
# set so a turn using ANY other tool is exempt automatically.
NO_WORK_TOOLS = {"ReadNotifications"}

# Re-prompts per turn before giving up. Deliberately low: a gate that nags
# three times is one he learns to ignore, which is the failure it exists to fix.
LOCAL_CAP = 2

# Substantive turns between REQUIRED closing blocks. Found 2026-09-03: this was
# unset (every substantive turn required it, forever) and that is what "way too
# many times" was. 5 is a guess at a working session's natural rhythm rather
# than a measurement — there is no prior data on the RIGHT cadence, only proof
# the old one (every turn) was wrong. Override with REPLY_GATE_COOLDOWN_TURNS
# to retune without a code change while real data accumulates.
try:
    COOLDOWN_TURNS = int(os.environ.get("REPLY_GATE_COOLDOWN_TURNS", "5"))
except ValueError:
    COOLDOWN_TURNS = 5

# Banned INSIDE the closing block only. Not a style opinion — these are words
# that do not survive translation into "explain it like I'm five", so their
# presence means the block was written for the wrong reader. The body above the
# block may use any of them freely.
#
# GROW THIS LIST. When Garrett asks what a word means, that word belongs here in
# the same turn. That is the whole maintenance model.
BANNED_IN_SUMMARY = [
    "idempotent", "deterministic", "heuristic", "regex", "refactor",
    "frontmatter", "endpoint", "payload", "schema", "boolean", "serialize",
    "deserialize", "instantiate", "middleware", "stdin", "stdout", "jsonl",
    "transpile", "polyfill", "mutex", "race condition", "memoize",
    "dependency injection", "monkeypatch", "symlink", "subprocess", "stdlib",
    "venv", "orm", "cors", "mtls", "bytecode", "closure", "recursion",
    "abstraction", "sidechain", "transcript_path", "concurrency",
    "atomic", "immutable", "canonical", "normalize", "traversal",
    # 2026-09-04. A block that passed this gate on shape read as a list of
    # mechanisms to Garrett: "I dont understand the concept of what you did
    # stuff for." The two words below carried the most weight in it.
    "protocol", "mutation",
    # 2026-09-07. Garrett: "Narrator? You mean the model? I'm confused." It is
    # Skyne Quest's internal design word for the model that writes the story
    # prose, lifted straight out of DESIGN.md into a reply without being
    # translated. Rule 0a's standing instruction is that a word he asks the
    # meaning of joins this list in the same turn.
    "narrator",
    # 2026-09-07, a second session the same hour and the same reflex. The block
    # read "Because you were in the denominator." Rule 0a requires the block be
    # plain English with no jargon, and rule 0 is the most-broken rule in the
    # ledger (11 misses, zero recorded wins) — this is the vocabulary that broke
    # it. "confound" rode along in the same reply.
    "denominator", "confound",
]

# ---------------------------------------------------------------- AI-isms
#
# Banned ANYWHERE in the reply, unlike BANNED_IN_SUMMARY above which only
# guards the closing block. These are not jargon — they are the stock phrases
# an assistant reaches for to sound engaged, and Garrett clocked them as a
# tell rather than as content.
#
# Ruled 2026-09-02. He had just caught a real failure, and the reply opened
# "You're right, and it's worse than you're saying." His response: *"you love
# that dont you? ... can we add that to the bin of AI-isms I want you to avoid
# using repetitively from now on?"*
#
# WHY A GATE AND NOT A PREFERENCE. "Avoid stock phrases" is an adjective, and
# house-rules 0a is the measured proof that adjectives do not hold: three of
# his formatting rules ran for months, the two with a countable shape held
# every time and the one that was a judgement call held never. A phrase list is
# countable. So it is counted.
#
# EACH ENTRY IS A PHRASE HE ACTUALLY SAW. Do not pad this list with plausible
# AI-isms — a banned list nobody triggered is a list nobody trusts, and it will
# eventually block a reply for a phrase that was fine. Grow it the same way
# BANNED_IN_SUMMARY grows: he names one, it lands here in the same turn.
#
# Escalation, not perfection: the check reports the phrase and asks for a
# rewrite of that sentence. It never rewrites the reply itself.
BANNED_ANYWHERE = [
    # 2026-09-02, named by Garrett
    r"it'?s worse than (you'?re|you are|that)",
    r"you'?re (absolutely )?right,? and",
    # 2026-09-07. THE SAME PHRASE, reworded straight past both lines above.
    # The reply opened "Your instinct was right, and it's worse than you
    # framed it." Neither matched: "your instinct was right" is not "you're
    # right", and "worse than you framed it" is not "worse than you're". A ban
    # a paraphrase walks through is a ban in name only, and this one was walked
    # through in the reply AND in the artifact published beside it.
    #
    # Deliberately NOT widened to "you are right, and" — the fixture directly
    # below asserts that phrasing PASSES, because a gate that fired on every
    # agreement would just be banning disagreement.
    r"\byour \w+ (?:was|is|were) (?:absolutely |completely |exactly |dead )?right[,;]? (?:and|but)\b",
    r"worse than (?:you (?:framed|put|said|think|thought|described|stated|make))",
    r"and (it|that)'?s the (whole|entire) point\b",
    r"let me (be )?(perfectly |completely )?(clear|honest) (with you )?here\b",
    r"\bi'?ll be honest\b",
    r"that'?s a (great|fair|excellent) (question|point|catch)\b",
    r"\bhere'?s the (thing|kicker|rub)\b",
    r"\bthe (real|actual) (question|answer|issue) (here )?is\b",
]

# Section markers, in required order. Recommendations is optional by design —
# mandating it would manufacture filler recommendations, which is noise, and
# noise is what he tunes out.
# 2026-09-07. Garrett, on correctly-shaped blocks: "the what I did and why isn't
# always helpful because I still have to ask hey what is this thing related to?"
# `What I did` names an ACTION with no SUBJECT, so a true sentence is one he
# cannot place -- and a block that sends him scrolling has failed at the one job
# it has. The `About` line names the thing before anything is said about it.
# "About" is an ordinary English word, unlike "What I did" or "TLDR", so this
# marker REQUIRES the bold (or a heading rule) and must sit adjacent to the
# block. Measured before tightening: the body line "About half the runs were
# flaky." satisfied the requirement and the whole reply passed with no About
# line at all -- a check that green-lights the real failure, which house-rules
# 21 point 5 calls worse than none. Both shapes are self-test cases below.
ABOUT_RE = re.compile(r"^\s*(?:\*\*|#{1,4}\s)\s*about\b", re.I)
ABOUT_MAX_GAP = 8   # lines it may sit above "What I did" before it is body text
WHAT_RE = re.compile(r"^\W*\**\s*what i (did|found|changed)\b", re.I)
WHY_RE = re.compile(r"^\W*\**\s*why\b", re.I)
TLDR_RE = re.compile(r"^\W*\**\s*tl;?dr\b", re.I)
RECS_RE = re.compile(r"^\W*\**\s*recommendation", re.I)


# ---------------------------------------------------------------- plumbing

def allow(path="ok", **kv):
    """Exit 0 with no stdout = the stop proceeds. One stderr marker so a human
    can see which branch fired; never emits reply content."""
    safe = lambda v: re.sub(r"[^A-Za-z0-9._<>/-]", "_", str(v))[:96]
    extra = " ".join("%s=%s" % (k, safe(v)) for k, v in kv.items())
    sys.stderr.write(("reply_gate_allow path=%s %s" % (path, extra)).rstrip() + "\n")
    sys.exit(0)


def block(reason):
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


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
                    continue  # tolerate a half-written tail line
    except OSError:
        return []
    return entries


def last_user_boundary(entries):
    """Index of the newest real user turn. Tool results, meta entries and
    subagent prompts all arrive as user-type entries; anchoring on one of those
    would treat part of this turn as a previous turn."""
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
    """Tool names invoked in the main loop this turn.

    Cause 1 of house-rules 0b is countable and this is what counts it: a turn
    whose ONLY tool call was ReadNotifications did no work, so a long reply
    about it is a reply that should not exist. If a notification genuinely
    needed acting on, some other tool would appear here — that is the
    discriminator, and it is structural rather than a judgement about tone.
    """
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
    """Main-loop assistant prose written this turn. Subagent (sidechain) output
    is not the reply — it never reaches Garrett."""
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


# ---------------------------------------------------------------- the check

def words(s):
    return len(s.split())


def find_line(text, rx):
    for i, line in enumerate(text.splitlines()):
        if rx.search(line):
            return i
    return -1


def is_trivial(text):
    """A reply this short never needed the closing block, cooldown or not."""
    return words(text) < TRIVIAL_WORDS


# --- house-rules 3, and the mechanism it owed --------------------------------
# Rule 3: "Say when the chat should end, and write the handoff first", and in
# its own words: "Telling him to start a new chat without running the skill is
# the failure, not the fix." It has failed twice with nothing making it fire --
# a nine-hour session on 2026-08-26 told Garrett to start a new chat FOUR times
# and produced no handoff, and on 2026-09-06 a session recommended a fresh chat
# in three consecutive closing blocks before running it. That second one put
# rule 3 into mechanism debt by name, which is what this closes.
#
# Deliberately narrow. It fires only on an explicit recommendation to START a
# new chat or END this one -- not on the word "chat", not on mentioning the
# handoff, and never once a handoff has actually run this session. A gate that
# fired on ordinary talk about chats would be the coarse gate house-rules 21
# point 5 forbids, so the self-test carries more negatives than positives.
ENDS_THE_CHAT = [
    r"start(?:ing)?\s+a\s+(?:fresh|new)\s+chat",
    r"open(?:ing)?\s+a\s+(?:fresh|new)\s+chat",
    r"a\s+(?:fresh|new)\s+chat\s+(?:is|would be|makes sense)",
    r"(?:good|cheapest|right)\s+(?:point|time|moment)\s+to\s+stop",
    r"end\s+(?:this|the)\s+chat",
    r"wrap\s+(?:this|it)\s+up\s+here",
]


def recommends_new_chat(text):
    """True when the reply tells Garrett to end this chat or start another."""
    low = (text or "").lower()
    return any(re.search(rx, low) for rx in ENDS_THE_CHAT)


# Rule 2a: "Mismatch -> say so, first, addressed to him by name, one line, the
# exact tier, no hedging." Only Garrett can type /model, so the recommendation
# is the entire implementation -- and it is worthless if he has to guess the
# command from a tier name.
#
# That is exactly how it failed on 2026-09-06 (miss
# 2026-09-06-told-garrett-to-run-model-sonnet-5-a-mar): the reply named the tier
# in prose -- "Garrett - drop to Sonnet High for this one" -- and gave no
# command. He guessed `/model sonnet 5`, the CLI rejected it, and the turn was
# spent on the correction instead of the work. Rule 2a broken 2x with no
# recorded win put it into mechanism debt by name; this is what closes it.
#
# So the gate reads rule 2a's "exact" as ACTIONABLE: a reply that tells him to
# change tier must also carry a /model command he can type. It never guesses
# WHICH tier is right -- no script can know that -- only that the instruction
# can be followed without a second turn.
MODEL_FAMILIES = ("opus", "sonnet", "haiku", "fable")

# What `/model` actually accepts: a bare invocation (opens the picker), a family
# alias, or a full id. Kept as a shape rather than a version list on purpose --
# a hardcoded roster of ids is the "number with no check" that goes stale.
VALID_MODEL_ARG = re.compile(
    r"^(?:%s|claude-[a-z]+-[0-9][0-9a-z-]*)$" % "|".join(MODEL_FAMILIES)
)

# "go down to Sonnet", "drop to Opus High", "switch up to Haiku" -- an explicit
# instruction to change tier. Deliberately requires a movement verb AND a family
# name: merely discussing a model is not a recommendation, and a gate that fired
# on that is the coarse gate house-rules 21 point 5 forbids.
CHANGES_TIER = re.compile(
    r"\b(?:go|drop|switch|move|bump|step|dial)\s+(?:back\s+)?"
    r"(?:down|up|over)?\s*(?:to|into)\s+(?:%s)\b" % "|".join(MODEL_FAMILIES),
    re.I,
)


def model_commands(text):
    """Every /model argument the reply hands Garrett, as written.

    Returns [] when the reply names no /model at all, and [""] for a bare
    `/model` -- which IS valid (it opens the picker), so the two cases must not
    be conflated.
    """
    out = []
    for m in re.finditer(r"/model\b([^\n`*_,.;:!?)\]]*)", text or ""):
        out.append(m.group(1).strip())
    return out


def recommends_tier_change(text):
    """True when the reply tells Garrett to move to a different model tier."""
    return bool(CHANGES_TIER.search(text or ""))


def unfollowable_tier_change(text):
    """The rule 2a complaint, or None.

    Fires only when the reply BOTH recommends a tier change AND fails to give a
    typeable command for it -- either no /model at all, or one whose argument
    the CLI would reject.
    """
    if not recommends_tier_change(text):
        return None
    args = model_commands(text)
    if not args:
        return ("this reply tells Garrett to change model tier but never gives him the "
                "command. Rule 2a: only he can type it, so the exact command IS the "
                "implementation. Add `/model <family>` (or a bare `/model` for the picker)")
    bad = [a for a in args if a and not VALID_MODEL_ARG.match(a)]
    if bad and not any(a == "" or VALID_MODEL_ARG.match(a) for a in args):
        return ("`/model %s` is not something the CLI accepts, so Garrett's command will "
                "fail and cost a turn. Use a bare `/model` for the picker, or one token: "
                "%s" % (bad[0], ", ".join(MODEL_FAMILIES)))
    return None


# 2026-09-07. Rule 2a's amendment. Garrett: "when you're recommending a model
# switch do you actually give me the time to change the model before you keep
# working? I don't think you do." He is right, and the rule's own wording proved
# it: both sanctioned phrasings end "for this" / "for this one", which NAME the
# current task -- the one already being spent. A recommendation that names the
# turn it appears in cannot apply to it.
#
# So this fires ONLY on the false claim: a reply that recommends a tier change,
# in a turn that already did work, while saying the change applies to THIS one.
# It never fires on a call made before the work (which is the shape rule 2a now
# asks for), and never when the turn's tools are unknown -- it fails open.
CLAIMS_THIS_TURN = re.compile(
    r"\bfor (this|this one|the rest of this)\b", re.I)


def tier_call_on_a_spent_turn(text, tools):
    """The rule 2a-window complaint, or None."""
    if tools is None:
        return None                      # unknown turn: fail open, never trap
    if not recommends_tier_change(text or ""):
        return None
    if not CLAIMS_THIS_TURN.search(text or ""):
        return None                      # aimed at the next turn: honest
    if not (set(tools) - NO_WORK_TOOLS):
        return None                      # nothing spent yet: "for this" is true
    return ("this reply tells Garrett to switch tier *for this* turn, but the turn "
            "already did the work — so the switch cannot apply to it and the line "
            "reads as noise. Rule 2a (amended 2026-09-07): make the call BEFORE the "
            "work and stop, or aim it at the next task by name. Measured: 0 of 2 "
            "calls followed in the session that found this, and neither could have "
            "been.")


def handoff_ran(entries):
    """True when THIS SESSION has actually invoked the handoff skill.

    Scans the whole transcript, not the turn: rule 3 is a session property.
    Fails SAFE by returning True on anything it cannot read, because the cost
    of a false block (a trapped session) is far worse than the cost of a
    missed nag -- every other path in this file makes the same trade.
    """
    if not entries:
        return True
    try:
        for e in entries:
            blob = json.dumps(e)
            if '"Skill"' in blob and "handoff" in blob:
                return True
    except (TypeError, ValueError):
        return True
    return False


def evaluate(text, tools=None, require_block=True, handoff_done=True):
    """Return a list of complaints. Empty list == the reply passes.

    Pure and transcript-free so the self-test exercises the real thing rather
    than a copy of it. `tools` is the set of tool names used this turn, or None
    when the caller cannot say; None disables only the echo check below.
    `require_block` is the cooldown's decision, made by the caller — this
    function stays a pure function of its arguments rather than reading the
    clock or the filesystem itself, which is what keeps it self-testable.
    """
    problems = []
    if is_trivial(text):
        return []  # short answer, nothing to skim past

    # house-rules 0b, cause 1. Measured 2026-09-01: four consecutive replies
    # existed only to relay PR notifications that echoed Claude's own actions,
    # and every one of them passed this gate on shape. Reading a queue is not
    # work, so a turn that did nothing else owes Garrett one line, not four
    # sections. This fires BEFORE the shape checks on purpose — telling a reply
    # that should not exist to fix its heading order is the wrong instruction.
    if tools is not None and tools and tools <= NO_WORK_TOOLS:
        return [
            "this turn only read the notification queue and did no other work, "
            "yet the reply is %d words. An event that echoes your own action is "
            "safe to skip — say it in ONE line with no closing block (under %d "
            "words is exempt), or say nothing at all"
            % (words(text), TRIVIAL_WORDS)
        ]

    # house-rules 3. Placed here, after the echo check and before the shape
    # checks, for the same reason 0b is: telling a reply that should have run
    # the handoff to fix its heading order is the wrong instruction.
    if not handoff_done and recommends_new_chat(text):
        problems.append(
            "this reply tells Garrett to end the chat or start a new one, and "
            "/handoff has not run this session. House-rules 3: 'Telling him to "
            "start a new chat without running the skill is the failure, not the "
            "fix.' Run the handoff skill first, then say it — or drop the "
            "recommendation from this reply"
        )

    spent = tier_call_on_a_spent_turn(text, tools)
    if spent:
        problems.append(spent)

    # house-rules 2a: a tier recommendation he cannot type is not a
    # recommendation. See unfollowable_tier_change() for the measured failure.
    tier = unfollowable_tier_change(text)
    if tier:
        problems.append(tier)

    # AI-isms: whole reply, not just the block. Reported alongside whatever
    # else is wrong rather than short-circuiting — a reply can be both
    # stock-phrased and missing a section, and hearing one at a time wastes a
    # round trip.
    stock = [rx for rx in BANNED_ANYWHERE if re.search(rx, text, re.I)]
    if stock:
        shown = [re.search(rx, text, re.I).group(0) for rx in stock[:3]]
        problems.append(
            "stock phrase(s) Garrett has asked you to stop using: %s. He named "
            "these as a tell rather than content — say the same thing in your "
            "own words, or just say the thing itself and skip the wind-up"
            % ", ".join('"%s"' % x for x in shown)
        )

    if not require_block:
        return problems

    lines = text.splitlines()
    i_about = find_line(text, ABOUT_RE)
    i_what = find_line(text, WHAT_RE)
    i_why = find_line(text, WHY_RE)
    i_tldr = find_line(text, TLDR_RE)

    if i_about < 0:
        problems.append('no "**About**" line — name the SUBJECT in his vocabulary '
                        '(a thing, not a task, and never a filename) before saying '
                        'what you did to it')
    elif 0 <= i_what and not (0 <= i_what - i_about <= ABOUT_MAX_GAP):
        problems.append('the "**About**" line is not attached to the block — it must '
                        'sit directly above "What I did", not adrift in the body')
    if i_what < 0:
        problems.append('no "**What I did**" section')
    if i_why < 0:
        problems.append('no "**Why**" section')
    if i_tldr < 0:
        problems.append('no "**TLDR**" line')

    if problems:
        return problems

    # Order matters: the block is one landing zone, not three scattered bits.
    if not (i_about < i_what < i_why < i_tldr):
        problems.append(
            "the closing sections are out of order — it must run "
            "About -> What I did -> Why -> (Recommendations) -> TLDR, together at the end"
        )

    # TWO Recommendations sections is the shape this actually catches, and the
    # old message described the symptom (position) instead of the cause.
    #
    # Garrett, 2026-09-02: "why do I feel like this is a lazy fix?" — after a
    # reply with a `## Recommendations` section in the body AND one inside the
    # block, plus a TLDR. He read it as three summaries of the same reply, and
    # he was right. The duplication is not carelessness: rule 0a's block already
    # CONTAINS Recommendations, while rule 10 separately says to put
    # recommendations in their own short section. Obey both literally and you
    # get two. One place, and the block is it.
    #
    # This gate already caught it on position — verified against the real reply
    # — but never ran, because in a multi-repo remote session this repo's hooks
    # sit in a subdirectory and are never loaded. See DELIVERY, below.
    all_recs = [n for n, ln in enumerate(lines) if RECS_RE.search(ln)]
    i_recs = all_recs[0] if all_recs else -1
    if len(all_recs) > 1:
        problems.append(
            "there are %d Recommendations sections. The closing block's is the "
            "only one — rule 0a's block already contains Recommendations, so a "
            "second one in the body makes the reply summarise itself twice. "
            "Delete the body copy; keep the reasons in the block's"
            % len(all_recs)
        )
    elif i_recs >= 0 and not (i_why < i_recs < i_tldr):
        problems.append(
            "Recommendations must sit INSIDE the closing block, between Why and "
            "TLDR — not as its own section up in the body"
        )

    block_text = "\n".join(lines[i_what:])
    n = words(block_text)
    if n > SUMMARY_MAX_WORDS:
        problems.append(
            "the closing block is %d words; the limit is %d. It is meant to be "
            "skimmed, so move detail up into the body rather than trimming the body"
            % (n, SUMMARY_MAX_WORDS)
        )

    low = block_text.lower()
    hits = [w for w in BANNED_IN_SUMMARY if re.search(r"\b%s\b" % re.escape(w), low)]
    if hits:
        problems.append(
            "jargon inside the closing block: %s. The block is the layer that has "
            "to work for someone who does not code — say it in ordinary words "
            "instead (the body above may use them freely)"
            % ", ".join(sorted(hits)[:6])
        )
    return problems


def build_reason(problems, attempt, require_block=True):
    if not require_block:
        # Not a block-shape ask -- do not describe the four-part structure for
        # a problem that is only a stock phrase or an echo-only turn. Asking
        # for a block nobody required would just reintroduce the frequency
        # this cooldown exists to fix.
        head = ("Do not end this turn yet -- one thing needs fixing first:"
                if attempt <= 1 else "Still not right:")
        return "%s\n%s" % (head, "\n".join("  - " + p for p in problems))
    head = (
        "Do not end this turn yet. Garrett reads the closing block and often "
        "nothing else, so a turn without one lands as unreadable."
        if attempt <= 1 else
        "Still not right. Fix ONLY the closing block and finish:"
    )
    body = "\n".join("  - " + p for p in problems)
    shape = (
        "\nRequired shape, at the very END of your reply, in this order:\n"
        "  **About** - what this concerns, in HIS words: a thing, not a task\n"
        "  **What I did** - plain English, no jargon\n"
        "  **Why** - plain English, no jargon\n"
        "  **Recommendations** - only if you actually have some, each with its reason\n"
        "  **TLDR** - one line\n"
        "Reading those alone must be enough to know what happened AND what "
        "it was about. "
        "Keep the detailed body above them; do not delete it and do not "
        "summarise it away."
    )
    return "%s\n%s\n%s" % (head, body, shape)


# ---------------------------------------------------------------- counter

def _state_dir():
    home = os.path.expanduser("~")
    if not home or home == "~" or not os.access(home, os.W_OK):
        home = tempfile.gettempdir()
    return os.path.join(home, ".reply-gate")


def counter_path():
    d = _state_dir()
    return d, os.path.join(d, "turn-counter.json")


# ---------------------------------------------------------------- cooldown
#
# Tracks turns-since-the-block-last-ran, one file PER SESSION -- the opposite
# key from counter_path() above, which tracks retry attempts within a single
# turn and is reset by a new message uuid. This one persists across the whole
# transcript on purpose: that is what makes the cadence a SESSION property
# rather than a per-message coincidence.

def cooldown_path(transcript_path):
    """Hashed rather than the raw path, so an unusual transcript path never
    becomes an unwritable or collision-prone filename."""
    import hashlib
    key = hashlib.sha256((transcript_path or "").encode()).hexdigest()[:16]
    return os.path.join(_state_dir(), "cooldown-%s.json" % key)


def turns_since_block(transcript_path):
    """How many substantive turns have passed since the block last ran.

    No state file -- a fresh session, or one whose state was wiped -- reads as
    DUE. The one case this must never produce is a session's first substantive
    reply skipping the block because a stale or missing file looked like a
    recent cooldown; failing toward "still required" is the safe direction.
    """
    try:
        with open(cooldown_path(transcript_path), encoding="utf-8") as f:
            state = json.load(f)
        return int(state.get("since_last", COOLDOWN_TURNS))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return COOLDOWN_TURNS


def record_cooldown(transcript_path, since_last, required_block):
    """Called once per substantive turn, after the verdict is final.

    Demanding the block resets the clock to 0 whether or not the reply
    actually managed a compliant one on the first try -- re-demanding it next
    turn just because this turn struggled once would reintroduce the exact
    frequency this cooldown exists to fix. Not demanding it just counts one
    turn closer to the next time it will be.
    """
    since = 0 if required_block else since_last + 1
    try:
        d = _state_dir()
        os.makedirs(d, exist_ok=True)
        with open(cooldown_path(transcript_path), "w", encoding="utf-8") as f:
            json.dump({"since_last": since}, f)
    except OSError:
        pass  # best effort; a lost state file just re-triggers next turn


def bump(turn_key):
    d, p = counter_path()
    state = {}
    try:
        with open(p, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    count = state.get("count", 0) if state.get("turn_key") == turn_key else 0
    count += 1
    try:
        os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"turn_key": turn_key, "count": count}, f)
    except OSError:
        pass  # best effort; the CLI's global block ceiling still bounds this
    return count


# ---------------------------------------------------------------- self-test

SAMPLE_BODY = (
    "I looked at the four files and found the counter was reset in the wrong "
    "place, so every run started from zero. I moved it above the loop and ran "
    "the suite twice to be sure it was not luck. The second run took nine "
    "seconds and both passed cleanly with nothing skipped or ignored anywhere.\n"
)

GOOD = SAMPLE_BODY + (
    "\n**About** the turn counter on your session board\n\n"
    "**What I did**\n"
    "- Fixed a counter that kept starting over.\n"
    "- Ran the tests twice; both passed.\n\n"
    "**Why**\n"
    "- It was resetting in the wrong spot, so it never counted past one.\n\n"
    "**TLDR** Fixed the counter, tests pass.\n"
)


ECHO_REPLY = (
    "All four were echoes of my own actions on the pull request - the "
    "subscription, the ready-for-review flip, the green CI I had already "
    "polled, and the merge I had already verified against origin/main. GitHub "
    "auto-unsubscribed the session. Queue is empty, nothing outstanding. Still "
    "finished. The paste block from my last message is what you need, and there "
    "is nothing further for anyone to act on here tonight at all.\n\n"
    "**What I did** - Read the notification queue, confirmed all four were my "
    "own actions coming back. No work needed.\n\n"
    "**Why** - I check the queue rather than assume it is noise, but I am not "
    "going to invent work out of it.\n\n"
    "**TLDR** - Empty queue, nothing to act on, chat still done."
)


def self_test():
    fails = []

    def expect(name, text, should_pass):
        got = evaluate(text)
        ok = (len(got) == 0) == should_pass
        if not ok:
            fails.append("%s: expected %s, got %r" % (
                name, "pass" if should_pass else "fail", got))
        print("  %-34s %s" % (name, "ok" if ok else "FAIL"))

    print("reply_gate self-test")
    expect("short reply needs no block", "Yes, that is already true.", True)
    expect("well-formed reply passes", GOOD, True)

    # ---- AI-isms, ruled 2026-09-02 -----------------------------------------
    # Garrett, after a reply opened "You're right, and it's worse than you're
    # saying": *"you love that dont you? ... can we add that to the bin of
    # AI-isms I want you to avoid using repetitively from now on?"*
    #
    # The VERBATIM opening is the fixture, so this can never quietly become a
    # check that only ever passes. Both directions are asserted: the real
    # phrase fails, and a reply saying the same thing plainly passes — a gate
    # that fired on both would just be banning disagreement.
    expect("the real 2026-09-02 opener fails",
           "You're right, and it's worse than you're saying. " + GOOD, False)
    expect("saying it plainly still passes",
           "You are right, and the cause is one I had already documented. " + GOOD,
           True)
    # 2026-09-07: the paraphrase that walked past both original patterns. The
    # VERBATIM sentence is the fixture for the same reason the 2026-09-02 one
    # is — so this cannot quietly become a check that only ever passes.
    expect("the 2026-09-07 paraphrase fails",
           "Your instinct was right, and it's worse than you framed it. " + GOOD,
           False)
    # ...and the negatives, which are the half that keeps the widening honest.
    expect("plain agreement still passes",
           "You were right about the shallow clone. " + GOOD, True)
    expect("an ordinary comparison still passes",
           "This build is worse than the last one. " + GOOD, True)
    expect("jargon in the BLOCK is caught",
           SAMPLE_BODY + "\n**What I did**\nfixed the denominator\n"
           "**Why**\nit was wrong\n**TLDR**\nfixed\n", False)
    for phrase in ("That's a great question. ",
                   "Here's the thing. ",
                   "Let me be honest with you here. ",
                   "You're absolutely right, and that changes things. "):
        expect("banned: %s" % phrase.strip()[:28], phrase + GOOD, False)
    # A banned phrase must be reported even when the block is ALSO malformed —
    # hearing one complaint per round trip wastes a turn.
    both = evaluate("Here's the thing. " + SAMPLE_BODY + "\n**What I did**\n- x\n")
    if not any("stock phrase" in c for c in both):
        fails.append("banned phrase not reported alongside a shape failure")
    print("  %-34s %s" % ("reported beside a shape failure",
                          "ok" if any("stock phrase" in c for c in both) else "FAIL"))

    # ---- the double summary, measured 2026-09-02 ----------------------------
    # Garrett: "why the hell are There TWO tldrs?" then "why do I feel like this
    # is a lazy fix?" The reply had a `## Recommendations` section in the body
    # AND one in the block, so it summarised itself twice. This gate ALREADY
    # caught the shape on position — the failure was delivery, not detection
    # (see DELIVERY at the top). The message now names duplication rather than
    # position, and both directions are asserted so it cannot become a check
    # that only ever fires.
    _f = "filler word " * 90
    _dup = ("Body.\n\n## Recommendations\n\n- a\n\n---\n\n"
            "**About** the thing.\n\n"
            "**What I did** — d.\n\n**Why** — w. " + _f +
            "\n\n**Recommendations** — r.\n\n**TLDR** — t.\n")
    _one = ("Body. " + _f + "\n\n**About** the thing.\n\n**What I did** — d.\n\n**Why** — w.\n\n"
            "**Recommendations** — r.\n\n**TLDR** — t.\n")
    _none = ("Body. " + _f + "\n\n**About** the thing.\n\n**What I did** — d.\n\n**Why** — w.\n\n"
             "**TLDR** — t.\n")
    expect("two Recommendations sections fail", _dup, False)
    expect("one, inside the block, passes", _one, True)
    expect("no Recommendations at all passes", _none, True)
    _msgs = " ".join(evaluate(_dup))
    if "2 Recommendations sections" not in _msgs:
        fails.append("the duplicate message must COUNT them, not just complain")
    print("  %-34s %s" % ("the message names the count",
                          "ok" if "2 Recommendations sections" in _msgs else "FAIL"))

    # ---- house-rules 0b cause 1: the echo reply, measured 2026-09-01 ----
    # This block is the regression. The verbatim failing reply below PASSED
    # every shape check the gate had at the time, which is what made Garrett
    # ask for a summary at the end of a fully compliant session.
    def expect_t(name, text, tools, should_pass):
        got = evaluate(text, tools)
        ok = (len(got) == 0) == should_pass
        if not ok:
            fails.append("%s: expected %s, got %r" % (
                name, "pass" if should_pass else "fail", got))
        print("  %-34s %s" % (name, "ok" if ok else "FAIL"))

    expect_t("echo-only turn is caught", ECHO_REPLY, {"ReadNotifications"}, False)
    # ECHO_REPLY is the REAL 150-word reply, kept verbatim as a historical
    # record, so it predates the About line and now fails on that too. The two
    # assertions below were written to prove the ECHO check is what catches it
    # -- not the shape check -- so they assert the absence of the echo
    # complaint rather than a clean pass, which is the claim they always made.
    def no_echo_complaint(tools):
        return not any("one line" in c or "did no work" in c
                       for c in evaluate(ECHO_REPLY, tools))
    _ok = no_echo_complaint(None)
    print("  %-34s %s" % ("...shape alone never catches it", "ok" if _ok else "FAIL"))
    if not _ok:
        fails.append("the echo reply must be caught by the ECHO check, not by shape")
    _ok = no_echo_complaint({"ReadNotifications", "Bash"})
    print("  %-34s %s" % ("echo + real work is exempt", "ok" if _ok else "FAIL"))
    if not _ok:
        fails.append("a turn that did real work must never draw the echo complaint")
    expect_t("one-line echo is fine", "All four echo my own actions; nothing to do.",
             {"ReadNotifications"}, True)
    expect_t("no tools recorded falls back to shape", GOOD, set(), True)

    # The regression this gate exists to stop: each required section must fail
    # the gate on its own when dropped, or the gate is one that only ever passes.
    # 2026-09-07: About is required, and its absence must be caught by NAME --
    # otherwise the block goes back to being an action with no subject.
    expect("missing About is caught",
           "\n".join(l for l in GOOD.splitlines() if not ABOUT_RE.search(l)), False)
    expect("About present passes", GOOD, True)
    # PLANTED, and measured as a real hole before the marker required the bold:
    # this exact reply passed with no About line at all.
    expect("a bare body line starting 'About' is NOT an About line",
           "About half the runs were flaky.\n\n" + SAMPLE_BODY +
           "\n**What I did** - d.\n\n**Why** - w.\n\n**TLDR** - t.\n", False)
    expect("a bolded About adrift in the body is caught",
           "**About** something.\n\n" + SAMPLE_BODY + ("\nfiller\n" * 12) +
           "\n**What I did** - d.\n\n**Why** - w.\n\n**TLDR** - t.\n", False)
    expect("a heading-style ## About is accepted",
           GOOD.replace("**About** the turn counter on your session board",
                        "## About the turn counter on your session board"), True)
    expect("About after What I did is caught (order)",
           GOOD.replace("**About** the turn counter on your session board\n\n", "")
               .replace("**Why**", "**About** the counter\n\n**Why**"), False)

    # 2026-09-07, rule 2a's window. A tier call on a turn that already did the
    # work cannot apply to that turn. Both directions asserted, or the check is
    # just a ban on mentioning /model.
    _spent = GOOD + "\nGarrett - go down to Sonnet for this. Type `/model sonnet`.\n"
    expect_t("a tier call claiming a SPENT turn is caught", _spent, {"Bash", "Edit"}, False)
    expect_t("PLANTED: the same call before any work PASSES", _spent, set(), True)
    expect_t("PLANTED: aimed at the NEXT task it passes even after work",
             GOOD + "\nGarrett - go down to Sonnet for the next one. Type `/model sonnet`.\n",
             {"Bash", "Edit"}, True)
    expect_t("unknown tools fail open, never trap", _spent, None, True)

    for label, rx in (("What I did", WHAT_RE), ("Why", WHY_RE), ("TLDR", TLDR_RE)):
        stripped = "\n".join(
            l for l in GOOD.splitlines() if not rx.search(l))
        expect("missing %s is caught" % label, stripped, False)

    expect(
        "out-of-order block is caught",
        SAMPLE_BODY + "\n**TLDR** done.\n\n**What I did**\n- a thing\n\n**Why**\n- reasons\n",
        False,
    )
    expect(
        "jargon in the block is caught",
        GOOD.replace("Fixed a counter that kept starting over.",
                     "Made the counter idempotent."),
        False,
    )
    expect(
        "jargon in the BODY is allowed",
        GOOD.replace("I looked at the four files",
                     "I refactored the regex and the schema payload"),
        True,
    )
    expect(
        "an oversized block is caught",
        SAMPLE_BODY + "\n**What I did**\n" + ("- word word word word word\n" * 40)
        + "\n**Why**\n- because\n\n**TLDR** done.\n",
        False,
    )
    expect(
        "recommendations in the wrong place is caught",
        SAMPLE_BODY + "\n**Recommendations**\n- do a thing\n\n**What I did**\n- a thing\n\n"
        "**Why**\n- reasons\n\n**TLDR** done.\n",
        False,
    )

    # ---- require_block=False: only stock phrases and echo-turns still fire --
    # Found 2026-09-03: the block ran on every substantive turn, forever.
    # These assert the escape hatch works, and that it is NARROW -- it must
    # skip the four-section requirement and NOTHING else.
    no_block_plain = SAMPLE_BODY  # well-formed prose, no closing block at all
    got = evaluate(no_block_plain, require_block=False)
    ok = got == []
    print("  %-34s %s" % ("require_block=False allows no block",
                          "ok" if ok else "FAIL"))
    if not ok:
        fails.append("require_block=False should allow a blockless reply, got %r" % got)

    # GOOD is well over the 60-word trivial floor on its own (SAMPLE_BODY
    # alone was one word short of it, and that word count IS the point of a
    # gate like this one — it must be checked, not eyeballed).
    stock_no_block = "Here's the thing. " + GOOD
    got = evaluate(stock_no_block, require_block=False)
    ok = len(got) == 1 and "stock phrase" in got[0]
    print("  %-34s %s" % ("...but a stock phrase still fires",
                          "ok" if ok else "FAIL"))
    if not ok:
        fails.append("require_block=False must still catch AI-isms, got %r" % got)

    got = evaluate(ECHO_REPLY, {"ReadNotifications"}, require_block=False)
    ok = len(got) == 1
    print("  %-34s %s" % ("...and an echo-only turn still fires",
                          "ok" if ok else "FAIL"))
    if not ok:
        fails.append("require_block=False must still catch echo-only turns, got %r" % got)

    # build_reason must not describe the four-part shape for a require_block=
    # False complaint -- asking for a block nobody required reintroduces the
    # exact frequency this cooldown exists to fix.
    reason = build_reason(["stock phrase(s): x"], 1, require_block=False)
    ok = "What I did" not in reason
    print("  %-34s %s" % ("build_reason(False) omits the shape",
                          "ok" if ok else "FAIL"))
    if not ok:
        fails.append("build_reason(require_block=False) must not print the four-part shape")

    # ---- the cooldown state machine, on an isolated HOME ---------------------
    real_home = os.environ.get("HOME")
    tmp_home = tempfile.mkdtemp(prefix="reply-gate-selftest-")
    try:
        os.environ["HOME"] = tmp_home
        path_a = "/fake/transcript/a.jsonl"
        path_b = "/fake/transcript/b.jsonl"

        since = turns_since_block(path_a)
        ok = since >= COOLDOWN_TURNS
        print("  %-34s %s" % ("a fresh session is DUE",
                              "ok" if ok else "FAIL"))
        if not ok:
            fails.append("a session with no state file must read as due, got since_last=%r" % since)

        record_cooldown(path_a, since, True)
        since = turns_since_block(path_a)
        ok = since == 0
        print("  %-34s %s" % ("required resets the clock to 0",
                              "ok" if ok else "FAIL"))
        if not ok:
            fails.append("recording required=True must reset since_last to 0, got %r" % since)

        for i in range(COOLDOWN_TURNS - 1):
            record_cooldown(path_a, turns_since_block(path_a), False)
        since = turns_since_block(path_a)
        ok = since == COOLDOWN_TURNS - 1
        print("  %-34s %s" % ("skipped turns count up, not required yet",
                              "ok" if ok else "FAIL"))
        if not ok:
            fails.append("after %d skips since_last should be %d, got %r"
                         % (COOLDOWN_TURNS - 1, COOLDOWN_TURNS - 1, since))

        record_cooldown(path_a, turns_since_block(path_a), False)
        since = turns_since_block(path_a)
        ok = since >= COOLDOWN_TURNS
        print("  %-34s %s" % ("one more skip crosses the threshold",
                              "ok" if ok else "FAIL"))
        if not ok:
            fails.append("crossing COOLDOWN_TURNS should read as due again, got %r" % since)

        ok = turns_since_block(path_b) >= COOLDOWN_TURNS
        print("  %-34s %s" % ("a second session has its own clock",
                              "ok" if ok else "FAIL"))
        if not ok:
            fails.append("session b must not inherit session a's cooldown state")
    finally:
        if real_home is not None:
            os.environ["HOME"] = real_home
        else:
            os.environ.pop("HOME", None)
        import shutil as _shutil
        _shutil.rmtree(tmp_home, ignore_errors=True)


    # ---- house-rules 3: the handoff gate -----------------------------------
    # Rule 6c applied to this check: the NEGATIVES are the point. A gate that
    # fired on ordinary talk about chats gets switched off, so there are more
    # must-stay-silent cases here than firing ones.
    _end = SAMPLE_BODY + ("\n**What I did**\nx\n**Why**\ny\n"
                          "**Recommendations**\n- Start a fresh chat.\n"
                          "**TLDR**\nz\n")
    ok = any("handoff" in g for g in evaluate(_end, handoff_done=False))
    print("  %-34s %s" % ('rule 3: no handoff is refused', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('recommending a fresh chat with no handoff must be refused')
    ok = not any("handoff" in g for g in evaluate(_end, handoff_done=True))
    print("  %-34s %s" % ('rule 3: passes once handoff ran', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('the same reply must pass once the handoff has run')

    _quiet = [
        (SAMPLE_BODY + "\n**What I did**\nRan /handoff and filed it.\n"
         "**Why**\ny\n**TLDR**\nz\n", "merely naming the handoff"),
        (SAMPLE_BODY + "\n**What I did**\nRead the chat log.\n**Why**\ny\n"
         "**TLDR**\nz\n", "the word chat on its own"),
        (SAMPLE_BODY + "\n**What I did**\nFixed the new chat window bug.\n"
         "**Why**\ny\n**TLDR**\nz\n", "'new chat' as a feature being worked on"),
    ]
    ok = not any(any("handoff" in g for g in evaluate(t, handoff_done=False)) for t, _ in _quiet)
    print("  %-34s %s" % ('rule 3 stays silent on 3 negatives', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('the gate fired on ordinary talk about chats -- that gets it turned off')
    ok = recommends_new_chat("this is a good point to stop")
    print("  %-34s %s" % ("rule 3 catches 'good point to stop'", "ok" if ok else "FAIL"))
    if not ok:
        fails.append("'good point to stop' is the same recommendation in other words")
    ok = not recommends_new_chat("the chat is running long but carry on")
    print("  %-34s %s" % ('rule 3 ignores a mere observation', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('observing the chat is long is not recommending it end')

    # ---- house-rules 2a: a tier change he can actually type ------------------
    # Replays the real 2026-09-06 miss verbatim, then guards the false-positive
    # side harder than the firing side (rule 6c): this gate lives in a file that
    # discusses models constantly, so a version that cried wolf would be turned
    # off rather than fixed.
    _real = "Garrett — drop to Sonnet High for this one. It's a pricing lookup, not architecture."
    ok = unfollowable_tier_change(_real) is not None
    print("  %-34s %s" % ('2a: the real 2026-09-06 miss fails', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('the reply that actually cost a turn must be refused')
    ok = unfollowable_tier_change(_real + " Type `/model sonnet 5`.") is not None
    print("  %-34s %s" % ('2a: an invalid /model arg fails', "ok" if ok else "FAIL"))
    if not ok:
        fails.append("'/model sonnet 5' is what he typed, and the CLI rejects it")

    _quiet2a = [
        (_real + " Type `/model sonnet`.", "a valid command alongside the tier"),
        (_real + " Run `/model` and pick from the list.", "bare /model opens the picker"),
        (_real + " Use `/model claude-sonnet-5`.", "a full model id"),
        ("Sonnet writes this genre better than Opus does.", "comparing models, not recommending"),
        ("We could switch to a hosted model later.", "'switch to' with no family name"),
        ("Only you can change it, with /model — I can't.", "naming the command, no tier change"),
        ("The 12B is the pick; go down to 8B and it gets worse.", "a size, not a Claude family"),
    ]
    bad = [why for t, why in _quiet2a if unfollowable_tier_change(t) is not None]
    ok = not bad
    print("  %-34s %s" % ('2a stays silent on 7 negatives', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('rule 2a gate fired on: %s -- that gets it switched off' % "; ".join(bad))

    ok = model_commands("run `/model`") == [""] and model_commands("no command here") == []
    print("  %-34s %s" % ('2a: bare /model != absent /model', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('a bare /model is VALID; conflating it with absence inverts the check')
    ok = handoff_ran([]) is True and handoff_ran([{"x": object()}]) is True
    print("  %-34s %s" % ('handoff_ran fails SAFE when unreadable', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('an unreadable transcript must fail safe -- a trapped session is worse')
    ok = handoff_ran([{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "handoff"}}]}}]) is True
    print("  %-34s %s" % ('handoff_ran sees a real Skill call', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('a real Skill(handoff) call must be detected')
    ok = handoff_ran([{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}]) is False
    print("  %-34s %s" % ('PLANTED: it reports NOT done', "ok" if ok else "FAIL"))
    if not ok:
        fails.append('PLANTED case: an unrelated transcript must report NOT done, proving the scan can say no rather than returning True for any reason')

    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print("\nall checks passed")
    return 0


# ---------------------------------------------------------------- entry

def run():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--transcript" in sys.argv:
        # Dry run against a real transcript, so a session can prove the gate
        # fires on live data rather than only on its own fixtures.
        path = sys.argv[sys.argv.index("--transcript") + 1]
        entries = read_transcript(path)
        b = last_user_boundary(entries)
        text = reply_text(entries, b)
        trivial = is_trivial(text)
        since_last = None if trivial else turns_since_block(path)
        require_block = (not trivial) and since_last >= COOLDOWN_TURNS
        problems = evaluate(text, tools_used(entries, b), require_block=require_block,
                            handoff_done=handoff_ran(entries))
        print("reply words: %d" % words(text))
        print("tools this turn: %s" % (sorted(tools_used(entries, b)) or "none"))
        print("cooldown: since_last=%s require_block=%s (this is a DRY RUN -- "
              "state is not written)" % (since_last, require_block))
        print("verdict: %s" % ("BLOCK" if problems else "allow"))
        for p in problems:
            print("  - " + p)
        sys.exit(0)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        allow("stdin_unparseable")

    transcript_path = payload.get("transcript_path") or ""
    entries = read_transcript(transcript_path)
    if not entries:
        allow("transcript_empty")

    boundary = last_user_boundary(entries)
    text = reply_text(entries, boundary)
    if not text:
        # A tool-only turn (spawned work, ran a command, said nothing). There is
        # no reply to shape, so there is nothing to gate.
        allow("no_assistant_text")

    # The cooldown decision lives here, not inside evaluate() — evaluate()
    # stays a pure function of its arguments so the self-test exercises the
    # real logic rather than a copy of it (see its docstring).
    trivial = is_trivial(text)
    since_last = None if trivial else turns_since_block(transcript_path)
    require_block = (not trivial) and since_last >= COOLDOWN_TURNS

    problems = evaluate(text, tools_used(entries, boundary), require_block=require_block,
                        handoff_done=handoff_ran(entries))
    if not problems:
        if not trivial:
            record_cooldown(transcript_path, since_last, require_block)
        allow("well_formed", words=words(text),
              block="required" if require_block else "cooldown")

    e = entries[boundary] if boundary >= 0 else {}
    key = e.get("uuid") or e.get("timestamp") or "unkeyed"
    n = bump(key)
    if n > LOCAL_CAP:
        if not trivial:
            record_cooldown(transcript_path, since_last, require_block)
        allow("cap_exhausted", count=n)
    block(build_reason(problems, n, require_block))


def main():
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # never trap the model on a bug in this file
        sys.stderr.write("reply_gate_allow path=exception exc_type=%s\n"
                         % type(exc).__name__)
        sys.exit(0)


if __name__ == "__main__":
    main()
