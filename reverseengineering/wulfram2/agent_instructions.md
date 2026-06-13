# Function-naming agent instructions (wulfram2.exe)

You are reverse-engineering **wulfram2.exe** — "Wulfram II", a late-1990s 3D multiplayer
tank game (x86 32-bit PE, C++) — inside a Ghidra instance exposed via the ghidra-mcp MCP
server. Your job: name and document a block of currently-unnamed functions.

You will be told a single CHUNK FILE path. That file holds ~50 function addresses, one
8-hex-digit address per line.

## Step 1 — load MCP tools (they are deferred)
Call ToolSearch with this exact query:
`select:mcp__ghidra-mcp__batch_decompile,mcp__ghidra-mcp__rename_function,mcp__ghidra-mcp__set_plate_comment,mcp__ghidra-mcp__decompile_function`

## Step 2 — read your chunk file
Read the chunk file path you were given.

## Step 3 — for each address
1. Decompile it. Use `batch_decompile` with ~10 comma-separated addresses at a time
   (program='wulfram2.exe'). Fall back to `decompile_function` for any that time out.
2. If the function's CURRENT name does NOT start with `FUN_`, it is already named — SKIP it.
3. Choose a concise descriptive name in **Module_VerbNoun** style: PascalCase parts with an
   underscore between the module prefix and the rest. Examples: TexList_FindByName,
   Render_DrawMesh, Net_SendPacket, Math_Normalize3, Vec3_Add, Snd_PlaySample,
   Hud_DrawStatusLine. Use class/vftable names in the decompilation (e.g. Tex_Entry,
   "::vftable" refs), names of called functions, and referenced strings/globals as hints
   for the module prefix and purpose.
4. Write ONE factual sentence describing what it does.
5. Apply BOTH:
   - `rename_function(program='wulfram2.exe', oldName='FUN_<addr>', newName=<name>)`
     where `<addr>` is the exact 8-digit form, e.g. `FUN_00401200`.
   - `set_plate_comment(program='wulfram2.exe', address='<addr>', comment=<the one sentence>)`

## Rules
- The server returns style warnings (wants PascalCase-without-underscores; wants
  Algorithm/Parameters/Returns sections). IGNORE them — they are non-blocking. We
  intentionally use Module_VerbNoun names and single-sentence comments.
- Tiny forwarder/thunk functions: name them for what they forward to and say so.
- If unsure of purpose, still give a best-effort descriptive name from the data/structures
  it touches, and hedge the comment with "Appears to..." / "Likely...". NEVER leave a
  function as FUN_.
- Comments: exactly one sentence, factual, concise. Names: valid C identifiers; if a name
  would collide, add a short suffix.
- Process EVERY address in the file.

## Step 4 — return a COMPACT summary ONLY
Report: number named, number skipped (already named), addresses that errored (with error),
and a one-line note on which module(s) the block belongs to. Do NOT paste decompilation or
the full list of names.
