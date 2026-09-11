#!/usr/bin/env python3
"""repo_standard_gate — refuse a workflow that bills twice for one answer.

WHY THIS EXISTS
---------------
Garrett, 2026-09-11, after catching the miss himself:

    "How do I know you've been using best practices to design github repos and
     python scripts? ... why did you make this miss? Lets make a structural
     change to make it harder for you to miss that next time and make sure its
     auditable and can run automatically as a hook on the mcp (so you can't
     miss it)"

THE MISS. Three workflows were written that day, each carrying BOTH
`pull_request` and `push: branches: [main]`. Every change would be checked
twice for one answer, and GitHub rounds each job up to a whole minute with a
one-minute floor -- so a ten-second check still bills a full minute, twice.

THE PART THAT MAKES IT A STRUCTURAL PROBLEM RATHER THAN CARELESSNESS. The rule
was already written down, in two places, and had been READ IN THE SAME SESSION
about an hour earlier -- Skyne's own ci.yml says "Deliberately NOT on push to
main" with the cost table quoted underneath. Knowing it did not make it fire.
That is the miss ledger's largest category by a wide margin, and nothing in the
estate turned that particular rule into something that acts.

So the rule now acts at the moment the file is written, which is the only point
where knowing it would have helped.

WHAT IT REFUSES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
Refuses: a Write or Edit to .github/workflows/*.yml whose content fires on a
push to main or master AND is not a deploy.

Never refuses a deploy or publish. Running after the merge is the entire point
of one, and a gate that fires on every legitimate publish is a gate someone
switches off within a week -- house-rules 21 point 5.

Never refuses a workflow that only fires on push (no pull_request). That is a
different and sometimes correct shape; the waste is specifically ANSWERING THE
SAME QUESTION TWICE.

Fails SAFE. Anything it cannot parse is allowed through, like every other hook
here: a trapped session is worse than a missed nag.

THE RULES LIVE IN ONE PLACE. data/repo-standard.json in Skyne is the source;
this file vendors it the same way check_hook_delivery.py vendors the hook
roster, and --self-test fails if the vendored copy no longer carries the rule
this gate enforces. A second copy of a decision is how the two drift apart
(house-rules 20).

    python3 .claude/hooks/repo_standard_gate.py --self-test
"""
import json
import os
import re
import sys

RULE_ID = "pr-not-push"
VENDORED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "repo-standard.json")

DEPLOY_HINTS = ("deploy", "publish", "release", "wrangler", "pages deploy",
                "gh-pages", "upload")
DEFAULT_BRANCHES = ("main", "master")

WORKFLOW_RE = re.compile(r"\.github/workflows/[^/]+\.ya?ml$")


def is_workflow(path: str) -> bool:
    return bool(path) and bool(WORKFLOW_RE.search(path.replace("\\", "/")))


def doubles_up(text: str) -> bool:
    """True when this workflow answers the same question on the PR and again
    on the merge.

    Both halves are required. A push-only workflow is a different shape and is
    not what rule pr-not-push is about.
    """
    if not text:
        return False
    low = text.lower()
    if any(h in low for h in DEPLOY_HINTS):
        return False
    if not re.search(r"(?m)^\s{0,4}pull_request:", text):
        return False
    m = re.search(r"(?m)^\s{0,4}push:\s*$", text)
    if not m:
        return False
    tail = text[m.end():m.end() + 240]
    return any(b in tail for b in DEFAULT_BRANCHES)


def vendored_rule() -> dict:
    try:
        with open(VENDORED, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    for r in doc.get("rules", []):
        if r.get("id") == RULE_ID:
            return r
    return {}


def message() -> str:
    r = vendored_rule()
    why = r.get("why") or ("A change checked on its PR and again on the merge is "
                           "billed twice for one answer.")
    return (
        "This workflow fires on BOTH pull_request and push to the default "
        "branch, so every change is checked twice for one answer.\n\n"
        f"{why}\n\n"
        "Drop the push trigger unless this is a deploy or publish, which "
        "genuinely must run after the merge:\n\n"
        "  on:\n"
        "    pull_request:\n"
        "      branches: [main]\n\n"
        "Standard: repo-standard.json rule 'pr-not-push'. Garrett caught this "
        "by hand on 2026-09-11 after it was written into three workflows in "
        "one session -- an hour after the opposite convention had been read in "
        "Skyne's own ci.yml. This gate exists because knowing it did not make "
        "it fire."
    )


def run() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    tool = payload.get("tool_name") or ""
    if tool not in ("Write", "Edit", "MultiEdit"):
        return 0
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if not is_workflow(path):
        return 0
    text = ti.get("content") or ti.get("new_string") or ""
    if not doubles_up(text):
        return 0
    print(message(), file=sys.stderr)
    return 2


def self_test() -> int:
    fails = []

    def check(ok, label):
        print("  %-56s %s" % (label, "ok" if ok else "FAIL"))
        if not ok:
            fails.append(label)

    both = "on:\n  pull_request:\n  push:\n    branches: [main]\njobs:\n  t:\n"
    pr_only = "on:\n  pull_request:\n    branches: [main]\njobs:\n  t:\n"
    push_only = "on:\n  push:\n    branches: [main]\njobs:\n  t:\n"
    deploy = ("on:\n  pull_request:\n  push:\n    branches: [main]\n"
              "jobs:\n  d:\n    steps:\n      - run: wrangler pages deploy site\n")

    check(doubles_up(both), "PLANTED: pull_request + push:main is refused")
    check(not doubles_up(pr_only), "pull_request alone is allowed")
    check(not doubles_up(push_only),
          "push alone is a different shape and is allowed")
    check(not doubles_up(deploy),
          "a DEPLOY on push:main is allowed — it must run after the merge")
    check(not doubles_up(""), "empty content is allowed (fails safe)")

    check(is_workflow(".github/workflows/ci.yml"), "a workflow path is matched")
    check(is_workflow("repo/.github/workflows/a.yaml"), ".yaml is matched too")
    check(not is_workflow("scripts/ci.yml"),
          "a yml OUTSIDE .github/workflows is not a workflow")
    check(not is_workflow(""), "an empty path is not a workflow")

    # The vendored standard must still carry the rule this gate enforces. If
    # Skyne's data/repo-standard.json drops or renames it, this gate is
    # enforcing something no longer written down -- exactly the drift that
    # vendoring a second copy risks.
    r = vendored_rule()
    check(bool(r), f"the vendored standard still carries rule {RULE_ID!r}")
    check(bool(r.get("why")), "the vendored rule still explains itself")
    check(r.get("why", "") in message(),
          "the refusal quotes the STANDARD, not a second copy of the reason")

    print("\nSELF-TEST " + ("FAILED" if fails else "PASSED"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(run())
