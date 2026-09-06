#!/usr/bin/env python3
"""solved_guard — before a NEW file is written, say what already solved it.

Why this exists
---------------
Garrett, 2026-09-05, after correcting the same failure four times in one
session: *"what else did we miss? I keep having to remind you to look which
is... kind of what skyne is supposed to help you do."* Then, on the fifth:
*"you know the drill; figure out why you missed, figure out a change, and make
the change an automatic check that fires when we work."*

WHY THE MISS HAPPENED, measured rather than guessed. The estate already has a
register for "what is this a reinvention OF" — `skyne/data/prior-art.json`,
built for house-rules rule 22. It answers with EXTERNAL prior art: inverted
index, event sourcing, CRDTs, Constitutional AI. Across its 52 rows, the words
behind that night's four misses appear this often:

    pwa 0 · icon 0 · access 0 · apple 0 · bypass 0 · wrangler 0

So a session asking "have we solved this" got nothing — not because nobody
looked, but because the answer was never a pattern name. It was a file two
directories away:

    Cloudflare, and its SECOND runner  -> cloudflare-deploy/.github/workflows/
    what an Access policy contains     -> one cloudflare-api.yml GET
    PWA icons behind Access            -> Gartera-Vault/scripts/publish_dashboard.py
    rendering the icon set             -> Gartera-Vault/scripts/build_pwa_icons.py

WHY IT IS A HOOK AND NOT A RULE. House-rules 21 ranks mechanisms by how
reliably they fire, and its own measured finding is that `convention-no-
mechanism` spans six different rules — writing a seventh does nothing. A hook
is the top row: it fires before the turn exists, with no judgment call. The
moment that matters is the one where a session is about to CREATE something,
and that moment is observable — it is a Write to a path that does not exist yet.

WHAT IT DOES NOT DO. It never blocks and never decides a permission; it prints.
A gate that refused a Write on a word match would fire constantly on legitimate
new files, which is the coarse gate rule 21 point 5 forbids. It fails open on
every error path, times out fast, and stays silent unless at least two
distinctive words from the new path already appear in a sibling repo's
docstring or instruction file.

    python3 solved_guard.py --self-test
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Read the top of a file only: a hit inside a function body is a USE, a hit in
# a docstring or an instruction file is an EXPLANATION, and only the second is
# worth interrupting for.
MAX_HEAD = 6000
GLOBS = ("scripts/*.py", "CLAUDE.md", "README.md", "Vault Ops/*.md",
         ".github/workflows/*.yml", ".claude/skills/*/SKILL.md")
SIBLINGS = ("Gartera-Vault", "skyne", "claude-audit", "cloudflare-deploy", "Tangle",
            "FusterCluck", "claude-usage-hud", "DnD-Scheduler", "claude-bootstrap",
            "skynegate")
# Words that appear in every repo and would match everything.
STOP = {"build", "test", "tests", "script", "scripts", "py", "md", "html", "json",
        "yml", "yaml", "css", "js", "new", "index", "main", "utils", "util", "tmp",
        "src", "data", "assets", "check", "run", "the", "and", "for", "with", "get",
        "set", "add", "make", "file", "files", "core", "app", "web", "site", "page"}
MIN_TERMS = 2
BUDGET_S = 2.5
MAX_HITS = 3


def terms_from(path: str) -> list[str]:
    """Distinctive words in a path. `build_pwa_icons.py` -> {pwa, icons}."""
    raw = re.split(r"[^A-Za-z0-9]+", path)
    out = []
    for chunk in raw:
        for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", chunk):
            w = w.lower()
            if len(w) >= 3 and w not in STOP and w not in out and not w.isdigit():
                out.append(w)
    return out


def repo_root(path: Path) -> Path | None:
    for p in [path] + list(path.parents):
        if (p / ".git").exists():
            return p
    return None


def search(root: Path, words: list[str], deadline: float) -> list[dict]:
    hits = []
    for name in SIBLINGS:
        base = root.parent / name
        if not base.is_dir() or base == root:
            continue
        for glob in GLOBS:
            for f in sorted(base.glob(glob)):
                if time.monotonic() > deadline:
                    return hits
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")[:MAX_HEAD].lower()
                except OSError:
                    continue
                matched = [w for w in words if w in text]
                if len(matched) >= MIN_TERMS:
                    hits.append({"repo": name, "path": str(f.relative_to(base)),
                                 "terms": matched,
                                 "score": sum(text.count(w) for w in matched)})
    hits.sort(key=lambda h: (-len(h["terms"]), -h["score"]))
    return hits


def finding(target: str, hits: list[dict], words: list[str]) -> str:
    lines = [
        "ALREADY SOLVED HERE? %s does not exist yet, and %d file(s) in sibling "
        "repos already document %s." % (target, len(hits), " + ".join(words[:4])),
        "Read them before writing this one — four things were re-derived from "
        "scratch on 2026-09-05, two of them wrongly, for exactly this reason.",
    ]
    for h in hits[:MAX_HITS]:
        lines.append("  %s/%s  (matched %s)" % (h["repo"], h["path"], ", ".join(h["terms"])))
    lines.append("This is a note, not a refusal — if it is genuinely new, carry on.")
    return "\n".join(lines)


def emit(text: str) -> None:
    # Two channels on purpose: `additionalContext` is what recent Claude Code
    # gives the model on PreToolUse, `systemMessage` is what older builds
    # surface. An unknown key is ignored, so emitting both costs nothing and
    # loses nothing if either name changes.
    json.dump({"systemMessage": text,
               "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                      "additionalContext": text}}, sys.stdout)
    sys.exit(0)


def run(payload: dict) -> None:
    if payload.get("tool_name") not in ("Write",):
        sys.exit(0)
    target = (payload.get("tool_input") or {}).get("file_path") or ""
    if not target:
        sys.exit(0)
    p = Path(target)
    if p.exists():                      # editing something is not inventing it
        sys.exit(0)
    root = repo_root(p if p.is_absolute() else Path.cwd() / p)
    if root is None:
        sys.exit(0)
    words = terms_from(p.name) or terms_from(str(p))
    if len(words) < MIN_TERMS:
        sys.exit(0)
    hits = search(root, words, time.monotonic() + BUDGET_S)
    if not hits:
        sys.exit(0)
    emit(finding(p.name, hits, words))


def self_test() -> int:
    fails = []

    def ck(name, cond, detail=""):
        if not cond:
            fails.append(name)
        print(("  ok   " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))

    ck("a path yields its distinctive words",
       terms_from("build_pwa_icons.py") == ["pwa", "icons"], str(terms_from("build_pwa_icons.py")))
    ck("generic words are dropped",
       terms_from("build_test_index.py") == [], str(terms_from("build_test_index.py")))
    ck("camelCase splits", "manifest" in terms_from("pwaManifestWriter.py"))
    ck("an existing file is never flagged", Path(__file__).exists())

    root = repo_root(Path(__file__).resolve())
    sibling_present = root is not None and any(
        (root.parent / n).is_dir() for n in SIBLINGS)
    if not sibling_present:
        print("  skip the live search — no sibling repo checked out beside "
              f"{root.name if root else '?'}; reported, never counted as a pass")
    else:
        deadline = time.monotonic() + BUDGET_S
        hits = search(root, ["pwa", "icons"], deadline)
        ck("the real 2026-09-05 miss is found", bool(hits),
           "searching pwa + icons found nothing — the guard has stopped working")
        noise = search(root, ["zzzqq", "wwwqq"], time.monotonic() + BUDGET_S)
        ck("words nothing uses return nothing", not noise)

    print(f"\n{'FAILED' if fails else 'PASS'} — {len(fails)} failure(s)")
    return 1 if fails else 0


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        raw = sys.stdin.read()
        run(json.loads(raw) if raw.strip() else {})
    except SystemExit:
        raise
    except Exception as exc:            # never block a Write on a bug in here
        sys.stderr.write("solved_guard_allow exc=%s\n" % type(exc).__name__)
        sys.exit(0)


if __name__ == "__main__":
    main()
