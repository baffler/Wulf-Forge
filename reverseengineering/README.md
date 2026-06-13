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
