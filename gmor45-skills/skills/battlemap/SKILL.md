---
name: battlemap
description: Generate Dungeondraft battlemaps programmatically — rooms, walls, doors, floors and lights written straight into a .dungeondraft_map file that Garrett opens, furnishes, and exports to Foundry. Use when he asks for a battlemap, a tactical map, a dungeon or building layout, or a map for a specific session or encounter. This skill does not contain the generator or the procedure — it fetches them.
---

# Battlemap generator — pointer

**This skill is a pointer, not the procedure**, and in this case not the code
either. Both live in the private `Gmor45/Gartera-Vault` repo.

## Do this, in order

1. **If the vault is not already cloned this session, run the `gartera-connect`
   pointer first.**

2. **Read the real procedure from the clone, in full, and follow it exactly:**

   ```
   ~/vault-work/Gartera-Vault/.claude/skills/battlemap/SKILL.md
   ```

3. **The generator is in that same repo, and you run it rather than reimplement
   it:** `scripts/battlemap/` holds `dd_gen.py` and `dd_packs.py`, with worked
   examples beside them, and `tests/test_battlemap_geometry.py` asserts the
   geometry. Do not write map-file bytes by hand — the `.dungeondraft_map`
   format is the thing the generator exists to get right.

4. **The repo file wins on any disagreement**, for the rest of the session.

## Why this file is this short

Same reason as its siblings (`gartera`, `gartera-connect`, `flow`,
`full-dive`): one copy, fetched live, nothing to drift.

**This one is the clearest case of why.** Until 2026-09-12 the 16 KB skill
lived only in `~/.claude/skills/`, in no repo — while the code it describes and
the tests that assert it had been in `Gartera-Vault` all along. The
documentation and its subject were in different worlds, and only one of them
had history. The skill now lives beside the code, and this pointer is all that
sits outside.
