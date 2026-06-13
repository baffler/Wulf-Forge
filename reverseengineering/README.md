# Reverse Engineering Export

This directory is a git-friendly export of the local Ghidra project `W2VULK`.

The export is intentionally text-first. It keeps program metadata, memory maps,
function inventories, symbols, comments, bookmarks, strings, exports, and
external references as TSV/JSON files so future analysis updates can be reviewed
as normal diffs.

This is not a complete reverse-engineering handoff yet. The source Ghidra
project still contains incomplete analysis work, especially around
`wulfram2.exe` function naming and documentation. This export exists so the
current state can be reviewed and iterated on in pull requests.

## Layout

- `programs/` - per-program text exports from the Ghidra project.
- `wulfram2/` - current `wulfram2.exe` function-address work queue and agent
  instructions from the local analysis workspace.
- `tools/ExportProgramText.java` - reusable Ghidra headless script used to
  refresh the text exports.

## Using This Data

Use `project_manifest.tsv` as the entry point. It lists every exported Ghidra
program, the directory that contains its files, hashes for source binary
identity, and row counts for the major export tables.

Each `programs/<program>/` directory is a read-only analysis snapshot. The TSV
files are meant for search, review, and small diffable follow-up PRs:

- `functions.tsv` is the primary function inventory, including current names,
  prototypes, comments, source types, thunk targets, and address ranges.
- `defined_symbols.tsv`, `external_locations.tsv`, and
  `external_entry_points.tsv` are useful for resolving imports, labels, and
  public entry points.
- `comments.tsv`, `bookmarks.tsv`, and `strings.tsv` capture analyst notes and
  string anchors that can justify future names or protocol discoveries.
- `memory_map.tsv` and `metadata.json` identify load ranges, image base,
  language/compiler settings, executable paths, and binary hashes.

Generated program exports should not be hand-edited. Make analysis changes in
Ghidra, rerun `tools/ExportProgramText.java`, and commit the resulting text
diff. Hand edits belong in README files, scripts, or follow-up notes, not in the
generated TSV/JSON snapshots.

TSV escaping is deliberately simple: `\N` means an empty field, `\t`, `\r`, and
`\n` are escaped control characters, `\\` is a literal backslash, and leading or
trailing spaces are written as `\s` so Git whitespace checks stay meaningful.

## Refreshing

If Ghidra or the MCP bridge has `W2VULK` open, copy the project to a temporary
directory first or headless export will fail on the project lock. From the repo
root, run the Ghidra headless analyzer recursively against the unlocked project
or a temporary copy:

```powershell
$ghidra = "C:\Users\balsa\Desktop\mcp\ghidra_12.1_PUBLIC_20260513\ghidra_12.1_PUBLIC\support\analyzeHeadless.bat"
$projectDir = "C:\Users\balsa\Desktop\WulframII\analysis"
& $ghidra $projectDir W2VULK -recursive -process -noanalysis -readOnly -scriptPath "$PWD\reverseengineering\tools" -postScript ExportProgramText.java "$PWD\reverseengineering"
```

Raw Ghidra project databases (`*.gpr`, `*.rep`, lock files, and binary Ghidra
archives) are deliberately not tracked here.
