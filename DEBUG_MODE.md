# Wulfram II Built-In Debug Mode Manual

This manual documents the debug and diagnostic features compiled into the stock
`wulfram2.exe` native client. These features are useful for Wulf-Forge server
work, client reverse engineering, `wulfram_lua.dll`, renderer debugging, and
general gameplay-state inspection.

The features here are built into the game. They do not require the Lua injection
project, although the Lua runtime can later wrap these commands and functions.

## Requirements

- A working Wulfram II install.
- The stock `data/keymap` file, or an equivalent binding for
  `command_dialogue`.
- A client session where gameplay input is active. Some commands only produce
  useful output after joining a server or loading enough game state.

## Open the Native Command Prompt

The shipped `data/keymap` binds the native command prompt to `Ctrl+End`:

```text
bind "" "ctrl-end" "command_dialogue"
```

To open it:

1. Launch `wulfram2.exe`.
2. Get to a screen where gameplay input is active.
3. Press `Ctrl+End`.
4. The client opens an `Enter command:` prompt.
5. Type a command and press `Enter`.

If `Ctrl+End` does nothing, add the binding above to the active `data/keymap`
file, restart the client, and try again.

Command output is posted back into the in-game console/chat output area. Unknown
commands print `Command unrecognized.` or the command-specific error text.

## Recommended Debug Startup

For normal Wulf-Forge testing, launch the client with the usual local-server
arguments:

```text
-root -windowed
```

One common setup is an `_override_args` file beside `wulfram2.exe`:

```text
-root
-windowed
```

Then launch the game, connect to the local server, press `Ctrl+End`, and enable
the debug tools you need from the command prompt.

## Quick Debug Presets

Enable common visual diagnostics:

```text
peek toggle
peek histo
peek net
grid
gprof
set debug_sound true
```

Disable the same diagnostics:

```text
peek toggle
peek histo
peek net
grid
gprof
set debug_sound false
```

Most debug commands are toggles. If a display appears twice or becomes noisy,
run the same command again.

## Command Reference

### `peek`

`peek` is the main debug command group. It requires one argument:

```text
peek <mode>
```

Known modes:

| Command | Effect |
| --- | --- |
| `peek toggle` | Toggles the native debug output-line overlay. |
| `peek histo` | Toggles packet histogram overlays. |
| `peek net` | Toggles the network multigraph overlay. |
| `peek netpri` | Toggles network-priority debug capture. |
| `peek resends` | Toggles packet-resend debug capture. |
| `peek weapons` | Toggles weapon debug capture and graphing. |
| `peek viewpoint` | Toggles viewpoint debug capture and graphing. |
| `peek keygraph` | Toggles the key/performance graph display path. |

If the mode is unknown, the client prints the supported list.

### `grid`

Toggles grid debug rendering:

```text
grid
```

Use this while inspecting world, terrain, or placement issues. Run `grid` again
to disable it.

### `keygraph`

Toggles the key/performance graph display:

```text
keygraph
```

This is similar to `peek keygraph`, but exposed as a direct command.

### `gprof`

Toggles the client graph/timegraph profiler:

```text
gprof
```

Use this when looking for client-side frame or timing spikes.

### `profiler`

Toggles the server/network profiler capture channel:

```text
profiler
```

This uses the built-in debug-network capture path. The command can still be a
useful hook target even when no external debug peer is running.

### `graphs`

Toggles the on-screen performance graph table:

```text
graphs
```

Some graph output depends on client state and current renderer/HUD paths.

### `look`

Requests a named debug graph over the debug-network system:

```text
look <graph-name>
look KILL-ALL
```

`KILL-ALL` removes all requested graphs. Other graph names depend on the debug
peer and profiler graph registrations available at runtime.

### `spynet`

Attaches the debug-network spy path to a player:

```text
spynet
spynet <player-name-prefix>
```

With no argument, the client attempts to use a reasonable current target. With a
name prefix, it resolves a matching player. The command reports errors for
missing player lists, unknown names, or ambiguous prefixes.

Expected messages include:

```text
spynet: playerlist is not ready
spynet: <name> is not a player
spynet: <name> is ambiguous
spynet: attached to player <name> [id]
spynet: failed attach to player <name> [id]
```

### `print`

Prints a bound config or runtime variable:

```text
print debug_sound
print time_debug_min
```

Use this before changing a setting so you can record the original value.

### `set`

Writes a bound config or runtime variable:

```text
set debug_sound true
set time_debug_min 0.25
set heap_debug_min 1024
```

Values are parsed by the game's command/config parser. Use `true` and `false`
for bools, decimal numbers for int/float values, and quoted text when setting a
string.

### `save` and `load`

Save or reload client parameters:

```text
save
load
```

Use `save` after changing a config setting you want to persist. Use `load` to
reload `client_params` from disk.

## Debug Config Variables

These variables are bound in the advanced client config registry.

| Variable | Type | Use |
| --- | --- | --- |
| `debug_sound` | bool | Enables the native sound debug overlay. |
| `debug_graphics_accelerator` | bool | Graphics accelerator debug flag. Exact visible effects still need runtime validation. |
| `heap_debug_min` | int | Heap/debug threshold used by native diagnostics. |
| `time_debug_min` | float | Timing/debug threshold used by native diagnostics. |

### Sound Debug Overlay

`debug_sound` is the most immediately useful config flag:

```text
set debug_sound true
```

When enabled, the HUD render path draws the active sound count and
world-positioned sound labels/boxes. This is useful when validating sound
emitters, object positions, camera projection, and HUD text rendering.

Disable it with:

```text
set debug_sound false
```

## Debug Network System

The client includes a debug-network subsystem used by several profiler and
overlay commands.

Known behavior:

- The debug accept port is `6969` (`0x1b39`).
- `profiler`, `peek weapons`, `peek viewpoint`, `peek netpri`, and
  `peek resends` toggle debug-network capture channels.
- `look <graph>` sends graph requests through debug-net.
- `spynet` uses debug-net to attach to player-specific debug streams.

The original external debug peer is not fully documented yet. If no peer is
available, some commands may only toggle internal flags or print status text.
They are still valuable hook targets for `wulfram_lua.dll`.

## Suggested Workflows

### Inspect Packet Behavior

```text
peek histo
peek net
peek netpri
peek resends
```

Use this while connecting, spawning, firing, or moving between zones. The
histogram and graph overlays help identify packet bursts, priority changes, and
resend behavior.

### Inspect Client Rendering or HUD Problems

```text
peek toggle
grid
gprof
graphs
```

Use this when testing overlays, HUD drawing, or frame-time changes. `gprof` and
`graphs` are useful for checking whether a visual change creates a timing spike.

### Inspect World-Space Audio

```text
set debug_sound true
```

Move around the world and watch the sound labels. This is useful for checking
projection, active sound counts, emitter positions, and whether sound-related
state is being updated.

### Inspect a Player With Spynet

```text
spynet playerprefix
```

Use a short unique prefix of the player name. If the prefix is ambiguous, use a
longer one.

## Troubleshooting

### `Ctrl+End` Does Nothing

Check that `data/keymap` contains:

```text
bind "" "ctrl-end" "command_dialogue"
```

Restart the client after editing keymap files.

### Command Output Says `Command unrecognized.`

Check spelling and argument count. `peek` requires exactly one argument, for
example `peek net`, not just `peek`.

### A Toggle Prints a Message But No Overlay Appears

Possible causes:

- The required game state is not active yet.
- The relevant debug-net peer is absent.
- The renderer/HUD path is not currently drawing that widget.
- The overlay is hidden behind another screen or mode.

Try joining a live local server session and toggling the command again.

### `spynet` Cannot Attach

Confirm the player list is ready and the name prefix is unique. If you are not
in an active match, `spynet` may not have enough state to resolve a target.

## Lua Integration Notes

The Lua injection project should wrap the safest native surface first: command
execution. That lets Lua reuse the game's validation, output, and toggle logic.

Recommended Lua-facing helpers:

```lua
w2.debug.command("peek net")
w2.debug.peek_output(true)
w2.debug.sound(true)
w2.debug.grid_toggle()
w2.debug.packet_histogram_toggle()
w2.debug.net_graph_toggle()
w2.debug.server_profiler_toggle()
w2.debug.client_profiler_toggle()
```

Direct native calls can follow once calling conventions and argument lifetimes
are verified. The debug command handlers are useful as bridge points, but many
were compiled with assumptions about global client state.

## Reverse-Engineering Appendix

These addresses are from the current `wulfram2.exe` analysis and are useful for
hooks, symbols, and future Lua wrappers.

| Symbol | Address | Notes |
| --- | ---: | --- |
| `Cmd_RegisterAll` | `0x0041c200` | Registers built-in console commands. |
| `Cmd_CreateCommandPrompt` | `0x0041adc0` | Creates the `Enter command:` prompt. |
| `Console_ExecuteAndReportCommand` | `0x004440c0` | Executes command text and posts output. |
| `Cmd_Peek` | `0x0041bd10` | Handles `peek <mode>`. |
| `Cmd_ToggleGridDebug` | `0x0041b540` | Handles `grid`. |
| `Cmd_ToggleKeyGraph` | `0x0041b520` | Handles `keygraph`. |
| `Cmd_ToggleServerProfiler` | `0x0041adf0` | Handles `profiler`. |
| `Cmd_ToggleClientGraphProfiler` | `0x0041ae30` | Handles `gprof`. |
| `Cmd_RequestGraph` | `0x0041aea0` | Handles `look <graph>`. |
| `SpyNet_AttachToPlayer` | `0x0041bbb0` | Handles `spynet`. |
| `DbgNet_Init` | `0x004139e0` | Initializes debug-net and binds port `6969`. |
| `DbgNet_Update` | `0x00413ae0` | Pumps debug-net connections and graph updates. |
| `DbgNet_Connect` | `0x004143b0` | Opens the debug-net connection. |
| `DbgNet_StartCapture` | `0x00414570` | Starts a capture channel. |
| `DbgNet_StopCapture` | `0x004145d0` | Stops a capture channel. |
| `DbgNet_ToggleCapture` | `0x00414630` | Toggles a capture channel. |
| `DbgNet_DrawPacketStats` | `0x00414860` | Draws packet stats overlay. |
| `NetDebug_TogglePacketHistogramOverlay` | `0x004866e0` | Toggles packet histograms. |
| `Cmd_Peek_ToggleMultigraphOverlay` | `0x004435f0` | Toggles network multigraph. |
| `DGW_ToggleGridDebug` | `0x00429150` | Toggles grid debug widget. |
| `DbgPeek_ClearOutputLines` | `0x0043bae0` | Clears debug output lines. |
| `DbgPeek_DrawOutputLines` | `0x0043bb10` | Draws debug output lines. |
| `AudioDebug_AddSoundEntry` | `0x00451440` | Adds a sound debug label entry. |
| `Hud_RenderFrame` | `0x00451b50` | Renders HUD and sound debug overlay. |
| `DebugLog_SetFilterString` | `0x004e5200` | Sets debug log filter text. |
| `DebugLog_FilteredPrintf` | `0x004e5210` | Filtered debug printf path. |
| `DebugLog_FilePrintf` | `0x004e5450` | Timestamped debug file printf path. |

Keep these addresses in the symbol registry rather than scattering constants
through hook code. That keeps future rebase or executable-version work localized.
