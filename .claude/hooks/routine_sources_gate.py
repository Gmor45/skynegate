#!/usr/bin/env python3
"""PreToolUse hook: refuse a scheduled Routine that will start with nothing.

WHY THIS EXISTS
---------------
Garrett, 2026-09-10: "I dont feel I should have to tell you hey connect these
repos... my guess is if a hook doesnt trigger and MAKE you add it, you wont."
He is right, and the finding behind it is structural, not a diligence gap:

`create_trigger` (the tool that makes a scheduled Routine) has NO parameter
for attaching a repo. None. A Routine created with
`create_new_session_on_fire: true` spawns a brand-new session on every single
firing, and that session starts with zero repos, forever, unless it is bound
instead to a persistent session that already has the repo attached. Nothing
in the tool schema stops a session (mine included) from creating exactly that
kind of Routine while the prompt or name plainly says what repo it needs.

`create_trigger` DOES have a `connectors` parameter, and it is just as often
left empty when the prompt names a connector the fired session will need
(Gmail, Calendar, Drive, Spotify) — same shape, cheaper fix.

WHAT IT REFUSES
----------------
A `create_trigger` call where:

  1. The `prompt` or `name` names one of Garrett's repos by its distinctive
     slug (not the word "skyne" alone — see FALSE POSITIVES below), AND
     `create_new_session_on_fire` is true, AND no `persistent_session_id` is
     set. That combination guarantees every firing starts with the named repo
     unreachable.

  2. The `prompt` or `name` says the Routine will use a connector-shaped
     service (Gmail, Google Calendar, Google Drive, Spotify) by name, and
     `connectors` is empty or missing.

WHAT IT DELIBERATELY LETS THROUGH
-----------------------------------
  - Any Routine with no `create_new_session_on_fire` (the default fires into
    the calling session, which keeps whatever it already has attached) or
    with `persistent_session_id` set (same reasoning — it reuses a session
    that was set up once, correctly).
  - A repo mention with no session-mode risk attached.
  - Cloudflare is NOT on the connector list. House-rules 27 and 31 are in
    active tension over whether Cloudflare work should route through the
    `cloudflare-deploy` repo dispatch or the Cloudflare connector — guessing
    wrong here would be worse than staying silent. Named, not hidden.

FALSE POSITIVES, MEASURED RATHER THAN HOPED
----------------------------------------------
Bare "skyne" is excluded on purpose: it is the estate's own brand name and
appears in almost every Routine prompt regardless of whether the fired
session touches the repo. Only the more distinctive slugs are matched
(`Gartera-Vault`, `FusterCluck`, `skynegate`, `DnD-Scheduler`,
`cloudflare-deploy`, `claude-usage-hud`, `gartera-codex`, `gartera-dashboard`),
plus a small set of generic repo-verb phrases. `Tangle` is matched
case-sensitively (capital T) to avoid "entangle"/"tangled" false hits — a
sentence-initial "Tangle up..." is a named, accepted residue.

NO OVERRIDE, ON PURPOSE
------------------------
Same reasoning as `no_push_to_main.py`: if a Routine genuinely needs no repo
despite naming one (a status-check Routine that only reads GitHub via the API,
say), that is fixable by rephrasing the prompt to drop the repo name, or by
setting `persistent_session_id` — not by an escape hatch Claude could set
itself and turn into decoration.

WHAT IT CANNOT SEE, STATED PLAINLY
-------------------------------------
It reads `tool_input` strings, so a repo or connector need phrased without any
of these markers is invisible to it — a false negative, not a false positive.
It also cannot fix the underlying gap: even when it fires correctly, the right
response is still "bind this to a persistent session" or "list the connector",
because `create_trigger` itself has no way to attach a repo. This hook forces
the conversation to happen; it does not do the attaching. Rule 21 point 5.

Usage:
    python3 routine_sources_gate.py                       # the hook (JSON on stdin)
    python3 routine_sources_gate.py --check '<json>'       # dry-run one tool_input
    python3 routine_sources_gate.py --self-test
"""
from __future__ import annotations

import json
import re
import sys

TOOL_NAME = "mcp__Claude_Code_Remote__create_trigger"

# Distinctive repo slugs only — never the bare brand word "skyne" (see
# FALSE POSITIVES above). Matched case-insensitively except "Tangle".
#
# CORRECTED 2026-09-11: three of these repos were renamed on GitHub the same
# week this hook was written (Tapestry->Hearth, skynegate->Bridge,
# FusterCluck->Exceed) -- same repos, same jobs, old names still redirect and
# are not broken. Both spellings are matched for each, because a stale prompt
# or an old habit can still type the old name, and a Routine created against
# either has the identical missing-repo failure. Skyne-Quest and Skyne-Loom
# are added too -- they postdate this hook's first draft.
REPO_SLUGS_CI = [
    "gartera-vault", "gartera vault", "fustercluck", "skynegate",
    "skyne-exceed", "skyne-bridge", "claude-bootstrap",
    "skyne-hearth", "skyne-tapestry", "skyne-quest", "skyne-loom",
    "dnd-scheduler", "cloudflare-deploy", "claude-usage-hud",
    "gartera-codex", "gartera-dashboard", "wedding vault",
]
REPO_SLUGS_CS = ["Tangle"]

# Generic phrases that name a repo need without naming a specific repo.
REPO_VERB_PHRASES = [
    "clone the repo", "clone this repo", "attach the repo", "attach a repo",
    "add_repo(", "the repo for", "push to origin", "open a pull request",
    "open a pr ", "create a pr ", "check my repos",
]

CONNECTOR_MARKERS = [
    "gmail", "google calendar", "calendar event", "google drive",
    "spotify",
]

REPO_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in REPO_SLUGS_CI) + r")\b",
    re.IGNORECASE,
)
TANGLE_RE = re.compile(r"\bTangle\b")
CONNECTOR_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in CONNECTOR_MARKERS) + r")\b",
    re.IGNORECASE,
)


def _text(tool_input: dict) -> str:
    return " ".join(
        str(tool_input.get(k) or "") for k in ("name", "prompt")
    )


def repo_hit(text: str) -> str | None:
    m = REPO_WORD_RE.search(text)
    if m:
        return m.group(1)
    m = TANGLE_RE.search(text)
    if m:
        return m.group(0)
    low = text.lower()
    for phrase in REPO_VERB_PHRASES:
        if phrase in low:
            return phrase
    return None


def connector_hit(text: str) -> str | None:
    m = CONNECTOR_RE.search(text)
    return m.group(1) if m else None


def verdict(tool_input: dict) -> str | None:
    """The refusal reason, or None to allow."""
    if not isinstance(tool_input, dict):
        return None
    text = _text(tool_input)

    fresh_session = bool(tool_input.get("create_new_session_on_fire"))
    has_persistent = bool(tool_input.get("persistent_session_id"))
    connectors = tool_input.get("connectors")
    has_connectors = isinstance(connectors, list) and len(connectors) > 0

    repo = repo_hit(text) if (fresh_session and not has_persistent) else None
    conn = None if has_connectors else connector_hit(text)

    if repo and conn:
        return (
            f"Refused: this Routine names `{repo}` and mentions `{conn}`, but "
            f"`create_new_session_on_fire: true` spawns a brand-new session on "
            f"every firing with no repo attached and no connector granted "
            f"(`connectors` is empty).\n"
            f"Fix both: either set `persistent_session_id` to a session that "
            f"already has `{repo}` attached, or drop the fresh-session mode; "
            f"AND pass `connectors: [\"{conn.title()}\"]` (or whatever its real "
            f"connector name is) so the fired session is actually granted it.\n"
            f"There is deliberately no override — a Routine that silently starts "
            f"with neither is the exact failure this hook exists to stop."
        )
    if repo:
        return (
            f"Refused: this Routine names `{repo}`, but "
            f"`create_new_session_on_fire: true` spawns a brand-new session on "
            f"every firing, and `create_trigger` has no way to attach a repo to "
            f"it. Every fire will start with `{repo}` unreachable.\n"
            f"Fix: set `persistent_session_id` to an existing session that "
            f"already has `{repo}` attached (its repos carry over on every "
            f"fire), or drop `create_new_session_on_fire` so it fires into the "
            f"calling session instead.\n"
            f"There is deliberately no override — say so to Garrett if this "
            f"Routine genuinely needs no repo, and rephrase the prompt so it "
            f"stops naming one."
        )
    if conn:
        return (
            f"Refused: this Routine's prompt mentions `{conn}`, but "
            f"`connectors` is empty. A fired session gets exactly the "
            f"connectors named at creation — none named means none granted, "
            f"even if the account has it installed.\n"
            f"Fix: pass `connectors: [\"{conn.title()}\"]` (match the exact name "
            f"`ListConnectors` reports) on this `create_trigger` call.\n"
            f"There is deliberately no override."
        )
    return None


def self_test() -> int:
    fails = []

    def refuse(tool_input, why):
        if verdict(tool_input) is None:
            fails.append(f"must REFUSE ({why}): {tool_input!r}")

    def allow(tool_input, why):
        if verdict(tool_input) is not None:
            fails.append(f"must ALLOW ({why}): {tool_input!r}")

    # --- must refuse: fresh session + named repo, no persistent binding ---
    refuse(
        {"name": "Nightly Gartera-Vault sync", "prompt": "Pull the vault and audit it.",
         "create_new_session_on_fire": True},
        "distinctive repo slug + fresh session, no persistent_session_id",
    )
    refuse(
        {"name": "x", "prompt": "Run scripts/session_start.py in skynegate.",
         "create_new_session_on_fire": True},
        "skynegate slug",
    )
    refuse(
        {"name": "x", "prompt": "Check Tangle for new commits.",
         "create_new_session_on_fire": True},
        "Tangle, capitalised",
    )
    refuse(
        {"name": "x", "prompt": "Update Skyne-Exceed pins.",
         "create_new_session_on_fire": True},
        "current name Skyne-Exceed",
    )
    refuse(
        {"name": "x", "prompt": "Check Skyne-Bridge hook self-tests.",
         "create_new_session_on_fire": True},
        "current name Skyne-Bridge",
    )
    refuse(
        {"name": "x", "prompt": "Build the Skyne-Hearth recap page.",
         "create_new_session_on_fire": True},
        "current name Skyne-Hearth",
    )
    refuse(
        {"name": "x", "prompt": "Check Skyne-Quest's dummy.",
         "create_new_session_on_fire": True},
        "Skyne-Quest",
    )
    refuse(
        {"name": "x", "prompt": "Check skyne-loom for new files.",
         "create_new_session_on_fire": True},
        "skyne-loom",
    )
    refuse(
        {"name": "x", "prompt": "clone the repo and build it",
         "create_new_session_on_fire": True},
        "generic repo-verb phrase",
    )
    # --- must refuse: connector named, connectors empty ---
    refuse(
        {"name": "x", "prompt": "Check Gmail for anything urgent and summarise it."},
        "connector named, connectors missing entirely",
    )
    refuse(
        {"name": "x", "prompt": "Look at Google Calendar for today's events.",
         "connectors": []},
        "connector named, connectors explicitly empty",
    )
    # --- must refuse: both at once ---
    refuse(
        {"name": "x", "prompt": "In FusterCluck, check Spotify and log it.",
         "create_new_session_on_fire": True},
        "repo AND connector both missing",
    )

    # --- must allow: fresh session but repo need is satisfied ---
    allow(
        {"name": "x", "prompt": "Pull Gartera-Vault and audit it.",
         "create_new_session_on_fire": True, "persistent_session_id": "session_abc"},
        "persistent_session_id set",
    )
    allow(
        {"name": "x", "prompt": "Pull Gartera-Vault and audit it."},
        "no create_new_session_on_fire — fires into calling session",
    )
    allow(
        {"name": "x", "prompt": "Pull Gartera-Vault and audit it.",
         "create_new_session_on_fire": False},
        "create_new_session_on_fire explicitly false",
    )
    # --- must allow: connector need satisfied ---
    allow(
        {"name": "x", "prompt": "Check Gmail for anything urgent.",
         "connectors": ["Gmail"]},
        "connectors non-empty",
    )
    # --- the false positives that would get this gate deleted ---
    allow(
        {"name": "Skyne v1 rescore", "prompt": "Re-score data/v1.json and rebuild the Loop board.",
         "create_new_session_on_fire": True},
        "bare 'Skyne' brand word must never trigger",
    )
    allow(
        {"name": "x", "prompt": "Don't let the plan get tangled up with the other one.",
         "create_new_session_on_fire": True},
        "lowercase 'tangled' must never trigger",
    )
    allow(
        {"name": "x", "prompt": "Send the morning email summary.",
         "create_new_session_on_fire": True},
        "'email' alone (not a connector marker) must not trigger",
    )
    allow(
        {"name": "x", "prompt": "Congratulate them on the wedding.",
         "create_new_session_on_fire": True},
        "bare 'wedding' (not 'wedding vault') must not trigger",
    )
    allow({}, "empty tool_input")
    allow({"name": "x", "prompt": ""}, "empty prompt")
    allow("not-a-dict", "non-dict tool_input must not raise")  # type: ignore[arg-type]

    # the refusal text has to name the actual fix, not just say no
    reason = verdict({"name": "x", "prompt": "Pull Gartera-Vault and audit it.",
                       "create_new_session_on_fire": True})
    for must in ("persistent_session_id", "no override"):
        if must.lower() not in (reason or "").lower():
            fails.append(f"refusal text must contain {must!r}")

    # the emitted payload must be a deny shape the harness understands
    payload = deny_payload("because")
    hso = payload.get("hookSpecificOutput", {})
    if hso.get("hookEventName") != "PreToolUse":
        fails.append("deny payload must name the PreToolUse event")
    if hso.get("permissionDecision") != "deny":
        fails.append("deny payload must carry permissionDecision=deny")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    print("self-test: 25 cases passed")
    return 0


def deny_payload(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        raw = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "{}"
        try:
            tool_input = json.loads(raw)
        except Exception:
            tool_input = {}
        reason = verdict(tool_input)
        print(reason if reason else "(allowed)")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except Exception:
        sys.exit(0)  # fail open: no stdin, or unparsable

    if not isinstance(payload, dict):
        sys.exit(0)
    if payload.get("tool_name") != TOOL_NAME:
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    try:
        reason = verdict(tool_input)
    except Exception:
        sys.exit(0)  # fail open: never break a session over a string scan

    if reason:
        json.dump(deny_payload(reason), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
