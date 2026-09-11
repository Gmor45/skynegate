#!/usr/bin/env python3
"""PreToolUse hook: refuse a create_trigger call that names a repo or
connector it cannot actually reach.

WHY THIS EXISTS
---------------
Garrett, 2026-09-10, after being told the cloud environment dialog has no
field for repos or connectors: "I dont feel I should have to tell you hey
connect these repos... my guess is if a hook doesnt trigger and MAKE you add
it, you wont." He is right, and it is house-rules rule 21 by the book: a rule
with no mechanism is a hypothesis, and "remember to check" is not a mechanism.

WHAT IS ACTUALLY TRUE ABOUT THE TOOL THIS GUARDS
--------------------------------------------------
`create_trigger` (the tool behind every scheduled Routine) has NO parameter
for attaching a repo, at all. A Routine made with
`create_new_session_on_fire: true` spawns a brand-new session on every single
firing, and that session starts with zero repos, forever -- unless the
Routine is instead bound to a `persistent_session_id` naming a session that
already has the repo attached, in which case it keeps whatever that session
already has, every time. `create_trigger` DOES have a `connectors` parameter,
and the same failure shows up there in a cheaper form: nothing stops a
Routine's prompt from saying "check Gmail" while `connectors` is left empty.

WHAT IT REFUSES
----------------
1. A `create_trigger` call whose `name` or `prompt` names one of Garrett's
   repos by a distinctive slug, where `create_new_session_on_fire` is true
   and no `persistent_session_id` is set. That combination guarantees every
   firing starts with the named repo unreachable.
2. A call whose `name` or `prompt` names a connector-shaped service (Gmail,
   Google Calendar, Google Drive, Spotify) with `connectors` empty or
   missing.

Both refusals name the exact fix in the error text (set
`persistent_session_id`, or list the connector) rather than just saying no.
There is deliberately no override, same reasoning as `no_push_to_main.py`: an
escape hatch Claude could set itself is decoration.

REPO NAMES, CORRECTED 2026-09-1X
----------------------------------
Three of Garrett's repos were renamed on GitHub the same week this hook was
finally written (Tapestry->Hearth, skynegate->Bridge, FusterCluck->Exceed --
same repos, same jobs, old names still redirect and are not broken). This
roster matches BOTH spellings for each renamed repo, because a stale prompt
or an old habit can still type the old name, and a Routine created against
either name has the identical missing-repo failure.

WHAT IT DELIBERATELY DOES NOT CATCH, ON PURPOSE RATHER THAN BY OVERSIGHT
--------------------------------------------------------------------------
Bare "skyne" and bare "wedding" are excluded, because "skyne" is the estate's
own brand name (it would fire on almost every Routine regardless of whether
the fired session touches the repo) and "wedding" is an ordinary English word
with far more false positives than true ones. Cloudflare is excluded from the
connector list, because house rules 27 and 31 are in live tension over
whether Cloudflare work should route through the `cloudflare-deploy` repo
dispatch or the Cloudflare connector -- guessing wrong here would be worse
than staying silent, so it is named as a gap instead of guessed at.

WHAT IT CANNOT SEE, STATED PLAINLY
-------------------------------------
It is a string match over `name` and `prompt`, not a semantic read of whether
the Routine's task actually needs the repo it happens to mention, or a check
that a repo named via `persistent_session_id`'s session is the RIGHT repo.
Rule 21 point 5: this narrows the failure, it does not close it.

Usage:
    python3 routine_sources_gate.py --self-test
    python3 routine_sources_gate.py --check '{"name": "...", ...}'
"""
from __future__ import annotations

import json
import sys

# slug -> canonical current name. Multiple slugs may map to the same repo
# (an old name and its current one) so either spelling is caught.
REPO_SLUGS: dict[str, str] = {
    "gartera-vault": "Gartera-Vault",
    "skyne-exceed": "Skyne-Exceed",
    "fustercluck": "Skyne-Exceed",  # renamed 2026-09-10
    "skyne-bridge": "Skyne-Bridge",
    "skynegate": "Skyne-Bridge",  # renamed 2026-09-10
    "claude-bootstrap": "Skyne-Bridge",  # renamed 2026-09-09, then again above
    "skyne-hearth": "Skyne-Hearth",
    "skyne-tapestry": "Skyne-Hearth",  # renamed 2026-09-10
    "skyne-quest": "Skyne-Quest",
    "skyne-loom": "Skyne-Loom",
    "dnd-scheduler": "DnD-Scheduler",
    "cloudflare-deploy": "cloudflare-deploy",
    "claude-usage-hud": "claude-usage-hud",
    "gartera-codex": "gartera-codex",
    "gartera-dashboard": "gartera-dashboard",
    "tangle": "Tangle",
}

# Connector-shaped services with a real create_trigger `connectors` name.
# Cloudflare excluded on purpose -- see module docstring.
CONNECTOR_SLUGS: dict[str, str] = {
    "gmail": "Gmail",
    "google calendar": "Google Calendar",
    "google drive": "Drive",
    "spotify": "Spotify",
}


def _hits(text: str, slugs: dict[str, str]) -> list[str]:
    low = text.lower()
    seen: list[str] = []
    for slug, canonical in slugs.items():
        if slug in low and canonical not in seen:
            seen.append(canonical)
    return seen


def verdict(payload: dict) -> str | None:
    """The refusal reason, or None to allow. Pure over the tool_input dict."""
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    if not isinstance(tool_input, dict):
        return None

    text = " ".join(str(tool_input.get(k) or "") for k in ("name", "prompt"))
    if not text.strip():
        return None

    fresh_session = bool(tool_input.get("create_new_session_on_fire"))
    persistent_id = tool_input.get("persistent_session_id")

    if fresh_session and not persistent_id:
        repos = _hits(text, REPO_SLUGS)
        if repos:
            named = ", ".join(repos)
            return (
                f"Refused: this Routine names {named}, and "
                f"create_new_session_on_fire is true with no "
                f"persistent_session_id set.\n"
                f"create_trigger has NO parameter for attaching a repo. A "
                f"fresh-session Routine starts with zero repos on every "
                f"single firing, forever, unless it is bound to a "
                f"persistent_session_id naming a session that already has "
                f"{named} attached.\n"
                f"Do this instead: set persistent_session_id to a session "
                f"that already has {named}, or attach the repo to that "
                f"session first if it does not yet.\n"
                f"There is deliberately no override. If this Routine "
                f"genuinely needs no repo, drop create_new_session_on_fire "
                f"or reword the name/prompt so it does not name one."
            )

    connectors = tool_input.get("connectors")
    if not connectors:
        services = _hits(text, CONNECTOR_SLUGS)
        if services:
            named = ", ".join(services)
            return (
                f"Refused: this Routine's text names {named}, but "
                f"`connectors` is empty or missing.\n"
                f"A fired session gets exactly the connectors named at "
                f"creation -- none named, none granted, even if the "
                f"account has the real thing installed.\n"
                f"Do this instead: pass connectors=[{named!r}] (or the "
                f"exact connector name Garrett has connected).\n"
                f"There is deliberately no override. If this Routine "
                f"genuinely does not need {named}, reword the name/prompt "
                f"so it does not name it."
            )

    return None


def deny_payload(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def self_test() -> int:
    fails = []

    blocked = [
        {"name": "Nightly Gartera-Vault sync", "prompt": "pull the vault",
         "create_new_session_on_fire": True},
        {"name": "Check FusterCluck pins", "prompt": "read pins",
         "create_new_session_on_fire": True},
        {"name": "Exceed pin sweep", "prompt": "read Skyne-Exceed pins",
         "create_new_session_on_fire": True},
        {"name": "Bridge hook audit", "prompt": "check skynegate hooks",
         "create_new_session_on_fire": True},
        {"name": "check", "prompt": "clone claude-bootstrap and read it",
         "create_new_session_on_fire": True},
        {"name": "Hearth recap", "prompt": "build Skyne-Tapestry recap",
         "create_new_session_on_fire": True},
        {"name": "Quest status", "prompt": "check Skyne-Quest dummy",
         "create_new_session_on_fire": True},
        {"name": "Loom check", "prompt": "check skyne-loom",
         "create_new_session_on_fire": True},
        {"name": "Scheduler sweep", "prompt": "check DnD-Scheduler PRs",
         "create_new_session_on_fire": True},
        {"name": "Deploy check", "prompt": "dispatch cloudflare-deploy",
         "create_new_session_on_fire": True},
        {"name": "HUD check", "prompt": "read claude-usage-hud",
         "create_new_session_on_fire": True},
        {"name": "Codex check", "prompt": "check gartera-codex",
         "create_new_session_on_fire": True},
        {"name": "Dashboard check", "prompt": "check gartera-dashboard",
         "create_new_session_on_fire": True},
        {"name": "Tangle check", "prompt": "read Tangle model format",
         "create_new_session_on_fire": True},
        # connector-shaped, no connectors listed
        {"name": "Morning brief", "prompt": "check Gmail and calendar",
         "create_new_session_on_fire": True, "persistent_session_id": "s1"},
        {"name": "Playlist", "prompt": "build a Spotify playlist",
         "create_new_session_on_fire": True, "persistent_session_id": "s1"},
    ]
    for tool_input in blocked:
        got = verdict({"tool_input": tool_input})
        if got is None:
            fails.append(f"must REFUSE: {tool_input!r}")

    allowed = [
        # the false positives that would get this gate deleted
        {"name": "Skyne health check", "prompt": "run skyne's own checks",
         "create_new_session_on_fire": True},
        {"name": "Wedding planning nudge", "prompt": "remind me about the wedding",
         "create_new_session_on_fire": True},
        {"name": "Core status", "prompt": "check core services",
         "create_new_session_on_fire": True},
        # names a repo but bound to a persistent session that has it
        {"name": "Vault sync", "prompt": "pull Gartera-Vault",
         "create_new_session_on_fire": True, "persistent_session_id": "s1"},
        # names a repo but self-binds (default mode) -- this session already
        # has whatever it has; not this gate's problem
        {"name": "Vault sync", "prompt": "pull Gartera-Vault"},
        # no repo/connector named at all
        {"name": "Daily standup", "prompt": "summarize open PRs",
         "create_new_session_on_fire": True},
        # connector named, and actually listed
        {"name": "Morning brief", "prompt": "check Gmail",
         "create_new_session_on_fire": True, "persistent_session_id": "s1",
         "connectors": ["Gmail"]},
        # Cloudflare named on purpose -- excluded connector
        {"name": "Deploy nudge", "prompt": "check the Cloudflare account",
         "create_new_session_on_fire": True, "persistent_session_id": "s1"},
        # empty payload
        {},
    ]
    for tool_input in allowed:
        got = verdict({"tool_input": tool_input})
        if got is not None:
            fails.append(f"must ALLOW: {tool_input!r} -> {got!r}")

    # non-dict / missing tool_input must not raise and must allow
    for bad in ({}, {"tool_input": None}, {"tool_input": "not a dict"}, None):
        try:
            got = verdict(bad)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover
            fails.append(f"must not raise on {bad!r}: {exc}")
            continue
        if got is not None:
            fails.append(f"must ALLOW malformed payload: {bad!r}")

    # the refusal text has to be actionable, not just a no
    reason = verdict({"tool_input": {
        "name": "x", "prompt": "clone Gartera-Vault",
        "create_new_session_on_fire": True}})
    for must in ("persistent_session_id", "no override"):
        if must.lower() not in (reason or "").lower():
            fails.append(f"repo refusal text must contain {must!r}")

    reason = verdict({"tool_input": {
        "name": "x", "prompt": "check Gmail",
        "create_new_session_on_fire": True, "persistent_session_id": "s1"}})
    for must in ("connectors", "no override"):
        if must.lower() not in (reason or "").lower():
            fails.append(f"connector refusal text must contain {must!r}")

    # the emitted payload must actually be a deny the harness understands
    payload = deny_payload("because")
    hso = payload.get("hookSpecificOutput", {})
    if hso.get("hookEventName") != "PreToolUse":
        fails.append("deny payload must name the PreToolUse event")
    if hso.get("permissionDecision") != "deny":
        fails.append("deny payload must carry permissionDecision=deny")
    if hso.get("permissionDecisionReason") != "because":
        fails.append("deny payload must carry the reason")

    if fails:
        for f in fails:
            print("SELF-TEST FAIL:", f)
        return 1
    total = len(blocked) + len(allowed) + 4 + 7
    print(f"self-test: {total} cases passed")
    return 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        raw = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "{}"
        try:
            tool_input = json.loads(raw)
        except Exception:
            print("(unparsable input)")
            sys.exit(0)
        reason = verdict({"tool_input": tool_input})
        print(reason if reason else "(allowed)")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except Exception:
        sys.exit(0)  # fail open: no stdin, or unparsable

    if not isinstance(payload, dict):
        sys.exit(0)
    if payload.get("tool_name") != "mcp__Claude_Code_Remote__create_trigger":
        sys.exit(0)

    try:
        reason = verdict(payload)
    except Exception:
        sys.exit(0)  # fail open: never break a session over a string scan

    if reason:
        json.dump(deny_payload(reason), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
