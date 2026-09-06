#!/usr/bin/env python3
"""PreToolUse hook: refuse a Bash command that pushes to main.

WHY THIS EXISTS
---------------
House-rules rule 1 is the most expensive rule in this estate and the one with
the weakest mechanism behind it. Measured: pushing to `main` fires up to five
workflows, a branch with an open PR fires two, a branch with no PR fires none.
Getting this wrong produced a real GitHub Actions overage — ~3,580 minutes
against 3,000 included, almost all of it one repo, and Garrett paid for it.

Its enforcement, until this file: a paragraph. Rule 1 even records itself being
broken *by the session that wrote it*, hours later, on a one-line doc edit. That
is `convention-no-mechanism` — the largest failure class in the miss ledger —
sitting on top of the largest cost.

WHY THIS ONE CAN BLOCK, WHEN delegate_reminder.py ONLY REMINDS
---------------------------------------------------------------
Both hooks came out of the same 2026-09-05 conversation, and the difference
between them is the whole point. "Is this task mechanical enough for Haiku?" is
a judgement, so the strongest honest mechanism is a reminder. "Does this shell
command push to main?" is a string, so it can be *refused*. Rule 21's ladder
ranks a gate above a note; this rule is one of the few here that qualifies for
the top rung, and nothing had claimed it.

WHAT IT REFUSES
---------------
A `git push` whose DESTINATION is a protected branch (`main` / `master`),
including the shapes that do not look like one at a glance:

    git push origin main                 git push origin HEAD:main
    git push -u origin master            git push origin +main
    git push --force origin main         git push origin refs/heads/main
    git push origin --delete main        cd x && git push origin main
    git push                             (when HEAD is on a protected branch)

WHAT IT DELIBERATELY LETS THROUGH
----------------------------------
Anything whose destination is not a protected branch, and every read-side
command that merely NAMES one. The false positive is the failure that gets a
gate deleted, so these are all fixtures in the self-test rather than hopes:

    git push -u origin claude/task-x     git push origin main-refactor
    git fetch origin main                git push origin feature/mainline
    git merge origin/main                git log origin/main..HEAD

`main-refactor` is the case that matters: a substring match on "main" blocks a
legitimate branch, and a gate that blocks real work does not survive contact
with a working session.

NO OVERRIDE, ON PURPOSE
-----------------------
There is no `ALLOW_PUSH_TO_MAIN=1` escape hatch, because Claude could set one
and the gate would be decoration. If pushing to main is genuinely right, that
is a decision to re-take with Garrett — the same standing this estate gives its
three write-surface guards. The refusal text names the branch-and-PR path
instead, so the next action is obvious rather than blocked.

WHAT IT CANNOT SEE, STATED PLAINLY
-----------------------------------
It reads the Bash tool's command string, so it cannot see a push made by
something other than that string: a script the command invokes, a git alias
resolving to a push, an MCP or API call, or Garrett's own desktop obsidian-git
backups (which are his and none of this hook's business). It also fails OPEN on
an unparsable command — consistent with every other hook in this plugin, and
worth saying out loud, because it means this narrows the failure rather than
closing it. Rule 21 point 5.

Usage:
    python3 no_push_to_main.py                  # the hook (JSON on stdin)
    python3 no_push_to_main.py --check "<cmd>"  # dry-run one command string
    python3 no_push_to_main.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}

# Shell operators that separate one command from the next. `cd x && git push
# origin main` is one Bash tool call and two commands; a parser that only looks
# at the front of the string sees `cd` and waves it through.
SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")


def _strip_ref(name: str) -> str:
    """`refs/heads/main` and `+main` both name main. Normalise to the branch."""
    name = name.lstrip("+")
    for prefix in ("refs/heads/", "heads/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def destinations(tokens: list[str]) -> list[str] | None:
    """Every branch this `git push` would WRITE to.

    None means "a push with no explicit refspec" — the caller has to look up
    the current branch, which is the one case that needs the filesystem.
    Returns [] for a push that names only a remote-side read (there is no such
    thing today, but an empty list is the honest shape for "nothing written").
    """
    # drop everything up to and including the `push` verb, so global options
    # like `git -C /some/path push` are skipped rather than parsed as refspecs
    try:
        idx = tokens.index("push")
    except ValueError:
        return []
    args = tokens[idx + 1:]

    dests: list[str] = []
    positional: list[str] = []
    deleting = False
    skip_next = False

    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--delete", "-d"):
            deleting = True
            continue
        if arg in ("--repo", "-o", "--push-option", "--receive-pack", "--exec"):
            skip_next = True  # takes a value that is not a refspec
            continue
        if arg.startswith("-"):
            continue  # --force, -u, --tags, --set-upstream, ...
        positional.append(arg)

    if not positional:
        return None  # bare `git push` — destination is whatever HEAD tracks

    # first positional is the remote; the rest are refspecs
    refspecs = positional[1:]
    if not refspecs:
        return None  # `git push origin` — still HEAD's branch

    for spec in refspecs:
        if ":" in spec:
            # src:dst, or :dst for a delete. The DESTINATION is what counts:
            # `git push origin HEAD:main` writes main and never says "main"
            # in a position a naive parser would look at.
            dst = spec.split(":", 1)[1]
        else:
            dst = spec
        if dst:
            dests.append(_strip_ref(dst))

    if deleting and not dests:
        return []
    return dests


def current_branch(cwd: str | None) -> str | None:
    """HEAD's branch, or None if that cannot be established cheaply."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or None, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    name = out.stdout.strip()
    return name or None


def verdict(command: str, cwd: str | None = None,
            branch_lookup=current_branch) -> str | None:
    """The refusal reason, or None to allow. Pure apart from the injected
    branch lookup, so the self-test exercises the real function."""
    if not command or "push" not in command:
        return None

    for segment in SPLIT_RE.split(command):
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment, comments=True)
        except ValueError:
            continue  # unbalanced quotes: fail open on this segment
        if not tokens:
            continue

        # `git push ...`, and `sudo git push`, `env X=1 git push`, `git -C p push`
        if "git" not in tokens or "push" not in tokens:
            continue
        if tokens.index("git") > tokens.index("push"):
            continue

        dests = destinations(tokens)
        if dests is None:
            branch = branch_lookup(cwd)
            if branch is None:
                continue  # cannot establish HEAD — fail open, say nothing
            dests = [branch]

        hit = [d for d in dests if d in PROTECTED]
        if hit:
            return refusal(hit[0], segment)
    return None


def refusal(branch: str, segment: str) -> str:
    return (
        f"Refused: this pushes to `{branch}`, which house-rules rule 1 forbids "
        f"({segment.strip()}).\n"
        f"Pushing to {branch} fires up to 5 workflows; a branch with no PR yet "
        f"fires 0. This already cost a real Actions overage (~3,580 minutes "
        f"against 3,000 included) that Garrett paid for.\n"
        f"Do this instead: commit to a feature branch, "
        f"`git push -u origin <branch>`, and open the PR when the work is DONE "
        f"— an open PR turns every later push into 2 runs.\n"
        f"There is deliberately no override. If pushing to {branch} is genuinely "
        f"right here, that is a call to take with Garrett, not to route around."
    )


def self_test() -> int:
    fails = []

    def on_main(_cwd):
        return "main"

    def on_feature(_cwd):
        return "claude/task-x"

    def no_repo(_cwd):
        return None

    blocked = [
        "git push origin main",
        "git push origin master",
        "git push -u origin main",
        "git push --force origin main",
        "git push -f origin main",
        "git push origin HEAD:main",
        "git push origin main:main",
        "git push origin +main",
        "git push origin refs/heads/main",
        "git push origin --delete main",
        "git push origin -d master",
        "cd /home/user/skyne && git push origin main",
        "git push origin main # ship it",
        "git status && git push origin main && echo done",
        "git -C /home/user/skyne push origin main",
        "sudo git push origin master",
        "git push origin feature:main",
    ]
    for cmd in blocked:
        if verdict(cmd, branch_lookup=on_feature) is None:
            fails.append(f"must REFUSE: {cmd!r}")

    allowed = [
        # the false positive that would get this gate deleted
        "git push origin main-refactor",
        "git push -u origin feature/mainline",
        "git push -u origin claude/task-model-categorization-7n4ccb",
        "git push origin HEAD:claude/task-x",
        "git push origin domain",
        # read-side commands that merely name a protected branch
        "git fetch origin main",
        "git merge origin/main",
        "git log origin/main..HEAD",
        "git diff --stat origin/main HEAD",
        "git checkout -B claude/task-x origin/main",
        "git rebase origin/main",
        # not git at all
        "echo 'git push origin main'",
        "grep -rn 'push origin main' docs/",
        "",
    ]
    for cmd in allowed:
        if verdict(cmd, branch_lookup=on_feature) is not None:
            fails.append(f"must ALLOW: {cmd!r}")

    # a bare push depends on where HEAD is
    if verdict("git push", branch_lookup=on_main) is None:
        fails.append("bare `git push` while on main must be refused")
    if verdict("git push origin", branch_lookup=on_main) is None:
        fails.append("`git push origin` while on main must be refused")
    if verdict("git push", branch_lookup=on_feature) is not None:
        fails.append("bare `git push` on a feature branch must be allowed")
    # ...and fails OPEN when HEAD cannot be established
    if verdict("git push", branch_lookup=no_repo) is not None:
        fails.append("an unknown HEAD must fail open, not refuse")

    # the refusal has to be actionable, not just a no
    reason = verdict("git push origin main", branch_lookup=on_feature)
    for must in ("rule 1", "-u origin", "no override"):
        if must.lower() not in (reason or "").lower():
            fails.append(f"refusal text must contain {must!r}")

    # an unparsable command must not raise
    for junk in ('git push origin "unbalanced', "git push $(", "\x00"):
        try:
            verdict(junk, branch_lookup=on_feature)
        except Exception as exc:  # pragma: no cover
            fails.append(f"must not raise on {junk!r}: {exc}")

    # the emitted payload must actually be a deny the harness understands —
    # a gate that computes the right verdict and emits the wrong shape is a
    # gate that never fires, and looks identical to a clean run
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
    total = len(blocked) + len(allowed) + 11
    print(f"self-test: {total} cases passed")
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
        cmd = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        reason = verdict(cmd, cwd=os.getcwd())
        print(reason if reason else "(allowed)")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except Exception:
        sys.exit(0)  # fail open: no stdin, or unparsable

    if not isinstance(payload, dict):
        sys.exit(0)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""

    try:
        reason = verdict(command or "", cwd=payload.get("cwd"))
    except Exception:
        sys.exit(0)  # fail open: never break a session over a string scan

    if reason:
        json.dump(deny_payload(reason), sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
