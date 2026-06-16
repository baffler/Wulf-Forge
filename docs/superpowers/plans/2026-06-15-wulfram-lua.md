# wulfram-lua Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable `wulfram-lua` milestone: an x86 loader that injects `wulfram_lua.dll`, plus a Lua-backed runtime with hook registration, events, memory helpers, and 2D/3D draw queues.

**Architecture:** `wulfram-lua-loader.exe` starts `wulfram2.exe` suspended and injects `wulfram_lua.dll` with `LoadLibraryW`. The DLL starts a worker thread, initializes logging/config/Lua, registers known Ghidra-backed symbols, installs enabled hooks, and dispatches events to Lua through protected calls.

**Tech Stack:** C++17, Win32 API, MSVC x86, CMake, Ninja, Lua 5.4.8 fetched by CMake, in-tree native test executable.

---

## File Structure

- Create `wulfram-lua/CMakeLists.txt`: CMake build for loader, DLL, static Lua, tests.
- Create `wulfram-lua/build.ps1`: Win32 build wrapper using Visual Studio `vcvars32.bat`.
- Create `wulfram-lua/include/wulfram_lua/*.hpp`: public internal headers for config, draw queue, event bus, hooks, loader args, logging, Lua runtime, memory, runtime, and symbols.
- Create `wulfram-lua/src/common/*.cpp`: deterministic modules shared by DLL, loader, and tests.
- Create `wulfram-lua/src/loader/*.cpp`: argument parsing and Win32 injection.
- Create `wulfram-lua/src/runtime/*.cpp`: DLL entry, runtime bootstrap, Lua binding, memory API, hook installation.
- Create `wulfram-lua/tests/*.cpp`: native tests using a tiny assert-based harness.
- Create `wulfram-lua/config/wulfram_lua.toml`: default config.
- Create `wulfram-lua/mods/main.lua`: sample mod script.
- Create `wulfram-lua/README.md`: build, install, and script API notes.

## Build Commands

Use Visual Studio's bundled CMake if `cmake` is not on PATH:

```powershell
cd C:\Users\balsa\Desktop\WulframII\Wulf-Forge\wulfram-lua
.\build.ps1 -Config Debug
```

Manual equivalent:

```powershell
cmd /c '"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat" && "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug && "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build build && build\wulfram_lua_tests.exe'
```

---

### Task 1: Test-First Project Scaffold

**Files:**
- Create: `wulfram-lua/CMakeLists.txt`
- Create: `wulfram-lua/build.ps1`
- Create: `wulfram-lua/tests/test_main.cpp`

- [ ] **Step 1: Write the failing smoke test**

```cpp
#include <cstdlib>
#include <iostream>

int main() {
    std::cout << "wulfram_lua_tests smoke\n";
    return EXIT_SUCCESS;
}
```

- [ ] **Step 2: Run test to verify the scaffold is incomplete**

Run: `.\build.ps1 -Config Debug`

Expected: FAIL before implementation because `build.ps1` or `CMakeLists.txt` does not exist.

- [ ] **Step 3: Add CMake and build wrapper**

Create a CMake project with `wulfram_lua_tests`, `wulfram-lua-loader`, and `wulfram_lua` targets. The initial test target only compiles `tests/test_main.cpp`.

- [ ] **Step 4: Run the smoke test**

Run: `.\build.ps1 -Config Debug`

Expected: PASS and prints `wulfram_lua_tests smoke`.

### Task 2: Loader Argument Parsing

**Files:**
- Create: `wulfram-lua/include/wulfram_lua/loader_args.hpp`
- Create: `wulfram-lua/src/loader/loader_args.cpp`
- Modify: `wulfram-lua/tests/test_main.cpp`

- [ ] **Step 1: Write failing loader argument tests**

Add tests that assert:

```cpp
auto parsed = ParseLoaderArgs({L"loader.exe", L"..\\Game\\wulfram2.exe", L"-windowed"});
expect(parsed.ok);
expect(parsed.value.game_exe_path.wstring().find(L"wulfram2.exe") != std::wstring::npos);
expect(parsed.value.dll_path.filename() == L"wulfram_lua.dll");
expect(parsed.value.game_arguments == L"-windowed");
expect(!ParseLoaderArgs({L"loader.exe"}).ok);
```

- [ ] **Step 2: Run test to verify failure**

Run: `.\build.ps1 -Config Debug`

Expected: FAIL because `ParseLoaderArgs` is not implemented.

- [ ] **Step 3: Implement parser**

Implement `ParseLoaderArgs` to require a game path, default the DLL path to the loader directory plus `wulfram_lua.dll`, and preserve remaining arguments.

- [ ] **Step 4: Run tests**

Run: `.\build.ps1 -Config Debug`

Expected: PASS.

### Task 3: Config, Symbols, Events, Draw Queue

**Files:**
- Create: `wulfram-lua/include/wulfram_lua/config.hpp`
- Create: `wulfram-lua/include/wulfram_lua/symbols.hpp`
- Create: `wulfram-lua/include/wulfram_lua/event_bus.hpp`
- Create: `wulfram-lua/include/wulfram_lua/draw_queue.hpp`
- Create: `wulfram-lua/src/common/config.cpp`
- Create: `wulfram-lua/src/common/symbols.cpp`
- Create: `wulfram-lua/src/common/event_bus.cpp`
- Create: `wulfram-lua/src/common/draw_queue.cpp`
- Modify: `wulfram-lua/tests/test_main.cpp`

- [ ] **Step 1: Write failing module tests**

Add tests that assert default config values, hook toggles from a temporary TOML file, symbol addresses for `Client_RenderFrame`, `Render_DriverFrameLoop`, `Hud_RenderFrame`, and `Winsys_LoadExternalRenderer`, event handler error isolation, and draw queue drain/clear behavior.

- [ ] **Step 2: Run tests to verify failure**

Run: `.\build.ps1 -Config Debug`

Expected: FAIL because modules are not implemented.

- [ ] **Step 3: Implement modules**

Implement simple TOML-style parsing, fixed default symbols, exception-safe event dispatch, and frame-local draw queues.

- [ ] **Step 4: Run tests**

Run: `.\build.ps1 -Config Debug`

Expected: PASS.

### Task 4: Lua Runtime and API

**Files:**
- Create: `wulfram-lua/include/wulfram_lua/lua_runtime.hpp`
- Create: `wulfram-lua/src/runtime/lua_runtime.cpp`
- Modify: `wulfram-lua/CMakeLists.txt`
- Modify: `wulfram-lua/tests/test_main.cpp`

- [ ] **Step 1: Write failing Lua runtime test**

Add a test that creates a temporary `main.lua`:

```lua
w2.on_frame = function(ctx)
  w2.log("frame from lua")
  w2.draw.text(10, 20, "hello", 0xff00ffff)
end
```

The test loads the script, dispatches `on_frame`, drains the draw queue, and expects one text command.

- [ ] **Step 2: Run tests to verify failure**

Run: `.\build.ps1 -Config Debug`

Expected: FAIL because Lua is not linked and `LuaRuntime` is not implemented.

- [ ] **Step 3: Implement Lua embedding**

Fetch Lua 5.4.8 in CMake, build it as a static C library, create a `w2` table with log and draw functions, load `mods/main.lua`, and call event handlers via `lua_pcall`.

- [ ] **Step 4: Run tests**

Run: `.\build.ps1 -Config Debug`

Expected: PASS.

### Task 5: Memory Helpers and Hook Registry

**Files:**
- Create: `wulfram-lua/include/wulfram_lua/memory.hpp`
- Create: `wulfram-lua/include/wulfram_lua/hooks.hpp`
- Create: `wulfram-lua/src/runtime/memory.cpp`
- Create: `wulfram-lua/src/runtime/hooks.cpp`
- Modify: `wulfram-lua/tests/test_main.cpp`

- [ ] **Step 1: Write failing tests**

Add tests for in-process `ReadU32`/`WriteU32` on a local variable, write rejection when `allow_memory_writes` is false, and address resolution from Ghidra absolute addresses relative to a module base.

- [ ] **Step 2: Run tests to verify failure**

Run: `.\build.ps1 -Config Debug`

Expected: FAIL because helpers are not implemented.

- [ ] **Step 3: Implement helpers**

Use `ReadProcessMemory`, guarded writes, `VirtualProtect`, and a five-byte x86 JMP hook object with trampoline allocation. Tests cover deterministic address resolution and memory helpers; live hook installation remains opt-in in config.

- [ ] **Step 4: Run tests**

Run: `.\build.ps1 -Config Debug`

Expected: PASS.

### Task 6: Loader and DLL Runtime Bootstrap

**Files:**
- Create: `wulfram-lua/src/loader/main.cpp`
- Create: `wulfram-lua/src/loader/injector.cpp`
- Create: `wulfram-lua/include/wulfram_lua/injector.hpp`
- Create: `wulfram-lua/src/runtime/dllmain.cpp`
- Create: `wulfram-lua/src/runtime/runtime.cpp`
- Create: `wulfram-lua/include/wulfram_lua/runtime.hpp`
- Create: `wulfram-lua/config/wulfram_lua.toml`
- Create: `wulfram-lua/mods/main.lua`

- [ ] **Step 1: Write failing integration-facing tests**

Add tests for injection plan creation without launching the game: command line quoting, absolute DLL path validation, and runtime path discovery from a fake DLL directory.

- [ ] **Step 2: Run tests to verify failure**

Run: `.\build.ps1 -Config Debug`

Expected: FAIL because loader/runtime bootstrap is not implemented.

- [ ] **Step 3: Implement loader and DLL bootstrap**

Implement suspended process creation, remote `LoadLibraryW` injection, thread resume, safe `DllMain`, worker thread startup, runtime init/shutdown, default config, and sample Lua mod.

- [ ] **Step 4: Run tests and build binaries**

Run: `.\build.ps1 -Config Debug`

Expected: PASS and outputs `build\wulfram-lua-loader.exe`, `build\wulfram_lua.dll`, and `build\wulfram_lua_tests.exe`.

### Task 7: Documentation and Final Verification

**Files:**
- Create: `wulfram-lua/README.md`

- [ ] **Step 1: Document usage**

Document:

```powershell
.\build.ps1 -Config Debug
.\build\wulfram-lua-loader.exe ..\..\Game\wulfram2.exe -root -windowed
```

- [ ] **Step 2: Run verification**

Run:

```powershell
.\build.ps1 -Config Debug
python -m pytest tests -q
git status --short
```

Expected: native tests pass, existing Python tests still pass, and git status shows only the intended `wulfram-lua` and plan files plus pre-existing unrelated untracked files.
