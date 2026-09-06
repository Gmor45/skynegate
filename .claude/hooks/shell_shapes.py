#!/usr/bin/env python3
"""PreToolUse hook: warn when the shell is about to eat part of a command.

WHY THIS EXISTS
---------------
House-rules rule 29, created 2026-09-06 when Garrett ruled that the two wholly
invisible failure families in the miss ledger get rule numbers. Until that day
`shell-interpolation` had five misses and NO rule id, which meant it could
never enter `check_repeat_escalation.py`'s debt roster no matter how often it
repeated. It repeated anyway. The five:

  2026-08-29  a `cd` in a compound command did not carry; a checkout ran in the
              wrong repo
  2026-08-29  backticks inside a double-quoted HEREDOC were command-substituted,
              silently deleting text from a changelog body
  2026-08-30  backticks inside a double-quoted `git commit -m` were substituted,
              so `trail.py: command not found` ran and the commit aborted
  2026-09-01  a backticked command inside a double-quoted `--evidence` argument
              was executed, storing the sentence "a real query, , reports 93 hit
              lines" -- the reproducible detail, which is the entire value of an
              evidence field, silently removed
  2026-09-04  a Bash step meant for the vault ran in the skyne checkout, relying
              on a working directory a parallel call had moved

The 08-30 one is the reason this is a hook rather than another paragraph. The
ledger ALREADY held the 08-29 miss when it happened. It did not transfer,
because it was filed as "heredoc", so the instinct generalised to *use a
heredoc* rather than to *quote the delimiter*. A miss recorded as its instance
does not transfer; a hook fires before the turn exists.

WHY IT WARNS AND NEVER BLOCKS
-----------------------------
`no_push_to_main.py` in this same directory refuses, and the difference is the
point. "Does this command push to main?" has a right answer. "Is this backtick
meant literally?" does not -- three of the five misses are in commit-message
text, where a backtick is sometimes exactly what is wanted. A gate that refused
those would be the coarse gate house-rules 21 point 5 forbids, and a blocked
session cannot argue with it. So this emits a warning naming the safe rewrite
and gets out of the way.

WHAT IT DETECTS
---------------
Three shapes, each decidable from the command text alone:

  backtick-in-interpolating-context   a ` outside single quotes, outside a
                                      QUOTED heredoc body, not escaped, and not
                                      in a # comment
  unquoted-heredoc-delimiter          <<EOF (not <<'EOF') whose body contains a
                                      backtick or $(
  cd-not-chained-with-and             `cd X; ...` -- if the cd fails the next
                                      command still runs, somewhere else

WHAT IT DELIBERATELY LETS THROUGH
----------------------------------
`$VAR` and `$( )` are NEVER flagged. They are how shell scripting works, they
appear in nearly every correct command in this estate, and not one of the five
misses was an intended expansion. Only the backtick is called out -- a form
with no advantage over `$( )` and a long history of surviving quoting by
accident.

MEASURED TWICE, BECAUSE A CHECK THAT CRIES WOLF GETS TURNED OFF
----------------------------------------------------------------
The first version of this logic flagged **3 of 67** real command bodies -- every
CI `run:` block and shell script in Gartera-Vault and skyne -- and all three
were wrong: an escaped backtick that `foundry-module.yml` echoes as literal
text, and backticks inside `#` comments in `publish-dashboard.yml` and
`cloud_session_setup.sh`. Both classes are now stripped before scanning and both
are self-test cases. Second measurement: **0 of 67**.

WHAT IT CANNOT SEE, STATED PLAINLY (house-rules 21 point 5)
------------------------------------------------------------
The 2026-09-04 cwd-drift miss is NOT detected and cannot be. Whether a bare
`git status` is safe depends on where a previous, possibly parallel, tool call
left the shell -- that is not in this string, and guessing it would fire on
almost every correct command. Rule 29 states the shape for that half (`git -C`,
absolute paths) and nothing enforces it.

It also reads only the Bash tool's command string, so a backtick inside a script
the command invokes is invisible to it, and it fails OPEN on anything
unparsable -- consistent with every other hook here.

DUPLICATION, SAID OUT LOUD RATHER THAN HIDDEN
----------------------------------------------
`skyne/scripts/check_shell_shapes.py` carries the same three shapes as a CLI.
This file cannot import it: this plugin has to work on any machine with only
itself installed, and skyne is private. So there are two copies, and the honest
consequence is that they can drift. What limits it: both self-tests are built
from the SAME five real misses, so a drift that breaks detection fails both. A
drift in false-positive handling alone would not be caught by either. Nothing
checks this today.

Usage:
    python3 shell_shapes.py                     # the hook (JSON on stdin)
    python3 shell_shapes.py --check '<command>' # scan one command
    python3 shell_shapes.py --self-test
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys

FIXES = {
    "backtick-in-interpolating-context":
        "use $( ) instead of backticks, or put the text in a QUOTED heredoc "
        "(<<'EOF'), which is what saved the commit message in the 2026-09-01 "
        "miss while the argument beside it was eaten",
    "unquoted-heredoc-delimiter":
        "quote the delimiter: <<'EOF' instead of <<EOF. An unquoted delimiter "
        "interpolates the whole body",
    "cd-not-chained-with-and":
        "chain it: `cd X && ...`, or better, do not depend on the working "
        "directory at all -- `git -C X ...` and absolute paths cannot drift",
}

_HEREDOC = re.compile(r"<<-?\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)")


# --- the golden corpus, shared with the OTHER implementation -----------------
# House-rules 29 is enforced by two copies of this logic: skyne's
# scripts/check_shell_shapes.py and skynegate's .claude/hooks/shell_shapes.py.
# The hook cannot import the script -- the plugin must run on a machine with
# only itself installed, and skyne is private -- so the copies can drift.
#
# Both self-tests were already built from the same five real misses, which
# catches a drift that breaks DETECTION. It does not catch a drift in
# FALSE-POSITIVE handling, and that is the drift that gets a check switched
# off rather than noticed. This corpus closes that: 28 of its 34 rows are
# commands that must stay SILENT.
#
# The sha is checked too. Editing the corpus on one side only changes its hash
# and fails THAT side's own CI, which is what forces both to move together --
# no network, no cross-repo read, works with one repo private.
CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shell-shapes-corpus.json")
CORPUS_SHA = "ff184d223ca94651323723f9bb9b1c78b70af67724fdcd916abfd2e777b934eb"


def corpus_rows(path=None):
    """(rows, sha) from the golden corpus file."""
    path = path or CORPUS_PATH
    raw = io.open(path, encoding="utf-8").read()
    return json.loads(raw)["cases"], hashlib.sha256(raw.encode("utf-8")).hexdigest()


def corpus_failures(rows=None, path=None):
    """Rows this implementation disagrees with. Empty list means in sync.

    Takes `rows` so the self-test can hand it a deliberately-wrong expectation
    and prove the comparator still REPORTS. Without that, blinding the
    comparison here makes it vacuous and every assertion still passes -- which
    is the "a check that matches nothing reads exactly like a clean run"
    failure this estate has already paid for. Measured: the first version of
    this function let both of its own mutations SURVIVE.
    """
    if rows is None:
        rows, _ = corpus_rows(path)
    out = []
    for r in rows:
        got = sorted({f["shape"] for f in scan(r["command"])})
        if got != r["expect"]:
            out.append({"why": r["why"], "expected": r["expect"], "got": got})
    return out


def _strip_inert(s: str) -> str:
    """Blank out the two places a backtick is real text, not a command.

    Both were REAL false positives on the first measurement. Only a `#` that
    OPENS a line counts as a comment -- that covers the measured cases and
    cannot misfire on ${var#prefix} or a # inside quoted text.
    """
    s = re.sub(r"\\.", "  ", s)
    s = re.sub(r"(?m)^[ \t]*#[^\n]*", lambda m: " " * len(m.group(0)), s)
    return s


def _strip_single_quoted(s: str) -> str:
    """Blank out single-quoted runs; the shell does not interpolate inside them.

    Replaced with spaces rather than deleted so offsets stay aligned.
    """
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "'":
            j = s.find("'", i + 1)
            if j == -1:
                out.append(" " * (n - i))
                break
            out.append(" " * (j - i + 1))
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _heredocs(command: str):
    """(tag, quoted, body) for each heredoc, in the order they are introduced."""
    found = []
    tags = [(m.group("tag"), bool(m.group("q"))) for m in _HEREDOC.finditer(command)]
    if not tags:
        return found
    lines = command.split("\n")
    idx, collecting, body = 0, None, []
    for line in lines[1:] if len(lines) > 1 else []:
        if collecting is None:
            if idx >= len(tags):
                break
            collecting, body = tags[idx], []
        if line.strip() == collecting[0]:
            found.append((collecting[0], collecting[1], "\n".join(body)))
            idx += 1
            collecting = None
            continue
        body.append(line)
    if collecting is not None:
        found.append((collecting[0], collecting[1], "\n".join(body)))
    return found


def scan(command: str):
    """Return a list of {shape, detail, fix}. Empty list means nothing found."""
    findings = []
    hds = _heredocs(command)

    # A QUOTED heredoc body is inert -- the 2026-09-01 miss proves it, because
    # the quoted body survived in the same command whose argument did not.
    scannable = command
    for tag, quoted, body in hds:
        if quoted and body:
            scannable = scannable.replace(body, " " * len(body), 1)

    if "`" in _strip_single_quoted(_strip_inert(scannable)):
        findings.append({
            "shape": "backtick-in-interpolating-context",
            "detail": "a ` sits where the shell will run what is between the "
                      "backticks and substitute the output",
            "fix": FIXES["backtick-in-interpolating-context"],
        })

    for tag, quoted, body in hds:
        if not quoted and ("`" in _strip_inert(body) or "$(" in body):
            findings.append({
                "shape": "unquoted-heredoc-delimiter",
                "detail": f"heredoc <<{tag} is unquoted and its body contains a "
                          "backtick or $( , so the body is interpolated",
                "fix": FIXES["unquoted-heredoc-delimiter"],
            })
            break

    bare = _strip_single_quoted(_strip_inert(command))
    for m in re.finditer(r"(?:^|[;&|\n])\s*cd\s+[^;&|\n]+", bare):
        rest = bare[m.end():]
        sep = rest[:1]
        if sep == ";" or (sep == "\n" and rest.strip()):
            findings.append({
                "shape": "cd-not-chained-with-and",
                "detail": "a `cd` is followed by `;` or a newline rather than "
                          "`&&`, so a failed cd does not stop what comes next",
                "fix": FIXES["cd-not-chained-with-and"],
            })
            break
    return findings


def message(findings) -> str:
    lines = ["house-rules 29 -- the shell may eat part of this command:"]
    for f in findings:
        lines.append(f"  !! {f['shape']}: {f['detail']}")
        lines.append(f"     -> {f['fix']}")
    lines.append("This is a warning, not a refusal. If the text is meant "
                 "literally, carry on.")
    return "\n".join(lines)


def warn_payload(text):
    # Two channels on purpose, same as solved_guard.py: `additionalContext` is
    # what recent Claude Code gives the model on PreToolUse, `systemMessage` is
    # what older builds surface.
    return {"systemMessage": text,
            "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "additionalContext": text}}


def run_hook(stream=None) -> int:
    raw = (stream or sys.stdin).read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # fail open: a malformed payload must never trap a session
    if not isinstance(payload, dict):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    ti = payload.get("tool_input") or {}
    command = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0
    try:
        findings = scan(command)
    except Exception:
        return 0  # fail open: never break a session over a string scan
    if findings:
        json.dump(warn_payload(message(findings)), sys.stdout)
    return 0


def self_test() -> int:
    """Every case is a real miss, or a real command this estate runs correctly."""
    import io
    fails = []

    def check(ok, msg):
        print(("  ok   " if ok else "  FAIL ") + msg)
        if not ok:
            fails.append(msg)

    def shapes(cmd):
        return {f["shape"] for f in scan(cmd)}

    # --- the measured misses, in their real shape ---
    check("backtick-in-interpolating-context" in shapes(
        'git commit -m "ran `trail.py agreement` and it held"'),
        "2026-08-30: backticks in a double-quoted commit -m are caught")

    check("backtick-in-interpolating-context" in shapes(
        'check_misses.py --add --evidence "a real query, `whois.py Duras`, '
        'reports 93 hit lines"'),
        "2026-09-01: a backticked command in an --evidence argument is caught")

    check("unquoted-heredoc-delimiter" in shapes(
        'changelog.py add --body "$(cat <<EOF\nsee `pin_tools.py`\nEOF\n)"'),
        "2026-08-29: an UNQUOTED heredoc whose body holds a backtick is caught")

    check("cd-not-chained-with-and" in shapes("cd ../Gartera-Vault; git checkout main"),
          "2026-08-29: `cd X; ...` is caught -- a failed cd does not stop the checkout")

    # --- the safe forms must be SILENT, or the hook gets turned off ---
    check(shapes("cd ../Gartera-Vault && git checkout main") == set(),
          "the && form of the same command is clean")

    check(shapes("git commit -q -F - <<'MSG'\nran `trail.py agreement`\nMSG") == set(),
          "2026-09-01's SURVIVING half: a QUOTED heredoc body is inert")

    check(shapes("git log --format='%an | %s' origin/main..origin/branch") == set(),
          "single-quoted text with % and | is clean")

    check(shapes('echo "today is $(date -u +%Y-%m-%d)"') == set(),
          "$( ) is the RECOMMENDED form and must never be flagged")

    check(shapes('TZ=America/New_York date "+%Y-%m-%d %H:%M %Z"') == set(),
          "house-rules 19's own dating command is clean")

    check(shapes("git -C ../Gartera-Vault status -s") == set(),
          "the -C form rule 29 recommends is clean")

    check(shapes("echo 'a `backtick` inside single quotes'") == set(),
          "a backtick inside SINGLE quotes is inert")

    # Both of these were REAL false positives on the first measurement,
    # 3 of 67 real command bodies across both repos' CI and shell scripts.
    check(shapes('echo "Version \\`1.2.0\\` built"') == set(),
          "an ESCAPED backtick is literal text, not a command")

    check(shapes("# `|| true` so a network failure reports below\nout=$(curl -s x)")
          == set(),
          "backticks inside a # comment are not flagged")

    check(shapes('grep "${name#prefix}" file') == set(),
          "a # inside ${...} is parameter expansion, not a comment")

    # --- the hook contract: warns, never blocks, never traps ---
    check(run_hook(io.StringIO("")) == 0, "an empty payload exits 0")
    check(run_hook(io.StringIO("not json")) == 0,
          "a malformed payload fails OPEN, never blocks")
    check(run_hook(io.StringIO(json.dumps({"tool_name": "Read"}))) == 0,
          "a non-Bash payload is ignored")

    out = io.StringIO()
    real_stdout, sys.stdout = sys.stdout, out
    try:
        rc = run_hook(io.StringIO(json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "`x`"'}})))
    finally:
        sys.stdout = real_stdout
    emitted = out.getvalue()
    check(rc == 0, "a FLAGGED command still exits 0 -- this hook never blocks")
    check(emitted.strip() != "", "and it does emit a warning payload")
    try:
        got = json.loads(emitted)
    except Exception:
        got = {}
    check(got.get("systemMessage", "").startswith("house-rules 29"),
          "the warning names the rule so it is traceable")
    check(got.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse",
          "and carries the PreToolUse shape recent builds read")
    check("permissionDecision" not in json.dumps(got),
          "it must NOT carry a permissionDecision -- that is what would block")


    # --- the golden corpus: the ONLY thing that catches false-positive drift
    # between this implementation and the other one. ---
    rows, sha = corpus_rows()
    check(sha == CORPUS_SHA,
          f"the corpus file is the one this code was frozen against "
          f"(sha {sha[:12]} vs {CORPUS_SHA[:12]}) -- if this fails, the corpus "
          f"moved on ONE side only; sync both repos, do not just bump the sha")
    fails_c = corpus_failures()
    check(not fails_c,
          f"all {len(rows)} corpus rows agree with this implementation"
          + (f" -- MISMATCH: {fails_c[:3]}" if fails_c else ""))
    # The comparator must be able to SAY NO. Without this, blinding the
    # comparison above passes silently -- both of this check's own mutations
    # survived the first version for exactly that reason.
    planted = [dict(rows[0], expect=["a-shape-that-cannot-exist"])]
    check(len(corpus_failures(rows=planted)) == 1,
          "the comparator reports a mismatch when one is planted -- proving it "
          "compares at all, rather than passing because it looked at nothing")
    silent = [r for r in rows if not r["expect"]]
    check(len(silent) >= 25,
          f"the corpus still carries enough MUST-STAY-SILENT rows to catch "
          f"false-positive drift (got {len(silent)})")

    print("self-test: PASS" if not fails else f"self-test: {len(fails)} FAILURE(S)")
    return 1 if fails else 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        cmd = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        found = scan(cmd)
        print(message(found) if found else "(clean)")
        sys.exit(0)
    sys.exit(run_hook())


if __name__ == "__main__":
    main()
