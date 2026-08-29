# Progress

_Last updated: 2026-06-12 (automated batch-labeling session)._

## Current State

- Active reverse-engineering target: `wulfram2.exe` in Ghidra project `W2VULK`.
- **Ghidra MCP bridge is currently DISCONNECTED** — all 232 `ghidra-mcp` tools are
  unavailable. It must be reconnected (restart the bridge / re-open the project in
  Ghidra) before any further labeling can run.
- The previous automated run was cut off by the account usage limit
  (**resets 5:30pm America/New_York**). Wait for the reset before relaunching.

## Labeling Convention (keep consistent)

- **Function name:** `Subsystem_VerbObject` (underscore-separated subsystem prefix,
  then a PascalCase action). Examples already in the binary: `TexList_FindByName`,
  `Math_BuildReciprocalTable`, `Camera_SetupViewAndRenderFrame`,
  `Hud_DrawOffscreenTargetArrow`, `Select_FormatTargetName`, `Math_VectorToSphericalAngles`.
- **Plate comment:** exactly ONE concrete sentence describing behavior/effect.
- **Variables:** rename only where the role is unambiguous. **Never** try to rename the
  auto-parameters `this`, `in_EAX`, `unaff_*`, `extraout_*` — Ghidra rejects these and it
  just produces noise in the error log.
- The MCP linter nags for sectioned (Algorithm/Parameters/Returns) comments and
  no-underscore names — **ignore it**; the one-line + underscore-prefix convention is correct
  and the renames still succeed.

## What Was Done This Session (2026-06-12)

Drove labeling with a self-scouting background workflow (decompile → name → comment →
rename vars → save, in parallel batches of 10, looping in rounds of 300).

- **~1,171 wulfram2.exe functions labeled** (1 proof + 150 validation batch + 1,020 full run).
- **Confirmed saved to disk: ~1,051** functions
  - 151 saved via explicit `save_program` before the full run.
  - Full run rounds 0–2 = 900 (saves r0/r1/r2 succeeded).
- **~120 functions from round 3 are labeled in memory but were NOT saved** — `save:r3`
  failed when the usage limit hit. If the Ghidra process is still open they persist and the
  next save will capture them; if it was closed they need re-doing. Either way the
  self-scouting resume handles it automatically (it re-scans whatever is still `FUN_*`).
- Unnamed non-thunk functions dropped **3,158 → ~2,138** (in memory) / **~2,258** (on disk).
- Earlier session work (pre-existing): profiler/timegraph, FX queue, controls/help UI,
  histogram, sky/fog shell, and the selected-object/HUD slice in the `0x0044xxxx` range.

### ⚠️ Known bug in the previous workflow (fix before re-running)

The run's log ends with *"Round 4: 0 unnamed remain… Complete"* — this is a **false
completion**. The round-4 scout agent failed on the usage limit, returned empty, and the
termination check misread "empty" as "done." **wulfram2 is NOT fully labeled.**
Fix for the resume script: treat a null/failed scout as an error (retry / abort the run),
and only declare completion when a *successful* scout reports `total === 0`.

## Remaining Ghidra Work

Functions are labeled lowest-address-first, so everything below the current frontier
(~`0x0049xxxx`) is done and the remainder sits in the higher ranges — consistent with the
old note that `0x004a18e0`–`0x004a7f70` and `0x004a8080`–`0x004b02f0` were still anonymous
(those `0x004a...` addresses are exactly where round 3 was interrupted).

Outstanding, in priority order:

1. **wulfram2.exe** — finish the remaining ~2,100+ unnamed functions (names + plate comments
   + variable renames).
2. **wulfram2.exe** — internal labels: loop bodies, switch/jump targets, error paths (short
   EOL comments), and obvious data labels encountered while working functions.
3. **wulfram2.exe** — dedicated global data-point pass (`DAT_*` / `_DAT_*`) labeled from
   cross-function usage (`list_globals` + xref analysis).
4. **bwau.exe** — ~590 unnamed functions + its data points.
5. **win32_glide.dll** — the rendering engine, in **two distinct builds**:
   - 3dfx build (~1,141 functions, ~794 unnamed)
   - client build (~450 functions)
   - Note: each build is imported more than once in the project; label each *distinct*
     binary only once. Targeting by the bare name `win32_glide.dll` is ambiguous — resolve
     the specific program (by path) before running.
6. **glide2x.dll** — **DEFERRED** per user instruction; do not label yet.

## How To Resume

1. Reconnect the Ghidra MCP bridge and confirm the `W2VULK` programs are open.
2. Ensure the usage limit has reset (after 5:30pm America/New_York).
3. Relaunch the self-scouting labeling workflow against `wulfram2.exe` **with the
   false-completion bug fixed** (see above). It auto-detects remaining `FUN_*` functions via
   `search_functions_enhanced(has_custom_name=false, is_thunk=false, sort_by="address")`,
   labels them in parallel batches, and saves each round — so it simply continues from
   wherever the unnamed set currently stands (including re-doing round 3's unsaved ~120).
4. After wulfram2 is clean, run the same workflow against `bwau.exe`, then each
   `win32_glide.dll` build, then the global-data passes.

### Reusable workflow script

Saved at (session-scoped; regenerable):
`~/.claude/projects/C--Users-balsa-Desktop-WulframII/4bfdc753-76ac-4a82-b979-e8a92c33b4fe/workflows/scripts/ghidra-label-wulfram2-full-wf_c01849c0-6dd.js`

It's small and self-contained — only the `program` const and the scout/termination logic
need changing per target. If the file is gone on restart, it can be regenerated from this
description.

## Working Notes

- Repo root is `Wulf-Forge/`, not the outer workspace root.
- `W2GL/` is present but currently untracked in Git.
- The `W2GL` README documents the renderer plan: OpenGL 3.3 core backend, drop-in
  `win32_glide.dll` replacement; remaining work around host pixel fetch, paletted texture
  rebake, mipmaps, and dual-texture paths.
- Concurrency: ~15 parallel labeling agents write to the single Ghidra instance safely
  (validated — 0 contention failures across 600+ writes). Saving happens between rounds, so
  no concurrent writes during a save.
