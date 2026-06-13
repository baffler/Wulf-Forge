# wulfram2.exe Work Queue

This folder preserves the current function-address queue used for ongoing
`wulfram2.exe` naming and documentation.

- `fun_addrs.txt` is the full address list exported from the local analysis
  workspace.
- `chunks/` splits that list into smaller batches for iterative review work.
- `agent_instructions.md` describes the current naming/commenting workflow used
  against the Ghidra MCP bridge.

This queue is incomplete by design. It records where the analysis work currently
stands so future PRs can continue from the same state.
