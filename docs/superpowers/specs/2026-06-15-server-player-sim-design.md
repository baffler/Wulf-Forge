# Server-Authoritative Player Simulation — Design Spec

*Design spec — 2026-06-15. For the Wulf-Forge server emulator. Makes the server
authoritatively track each player's tank by simulating it from the control inputs
the client already sends, reusing the exact decompiled physics from `phys_sim`.*

## Goal

Give the server a correct, live position/velocity/orientation for every player by
**simulating each tank from its control inputs** at the server tick, then broadcasting
that authoritative state to all clients via the existing entity-update packets. This
replaces the dead W2Mod relay and the elevated memory-read hack as the position source,
and unblocks gameplay that needs real positions (e.g. collision-based cargo pickup).

## Why this model (reverse-engineering evidence)

The original game is **server-authoritative with client-side prediction**, confirmed by RE
of `wulfram2.exe`:

- The client **never sends its own world position upstream.** Every `Net_SendStart` caller
  was enumerated; none reads the controlled-entity position (`DAT_00677f2c + 0xC`). The
  client uploads only: control-axis inputs (`ACTION_DUMP 0x09`, `ACTION_UPDATE 0x0A`,
  `INPUT_FEEDBACK 0x40`), target ids (`RETARGET 0x26`), menu/loadout selections, and
  user-clicked map coordinates (`BEACON_REQUEST/MODIFY 0x3a/0x3b`, `COMM_MESSAGE_REQUEST 0x20`
  move/build). None of these is the player's own position.
- Position flows the other way: the client **receives** it (`Net_HandleTankSpawn` reads two
  inbound quantized vec3s) and **reconciles** its local prediction against server corrections
  (`Interp_ReplayLocalPlayerPrediction @ 0x004699b0`).
- The `BEHAVIOR (0x24)` packet ships the physics tunables once; the client integrates locally
  every frame and the server sends authoritative corrections.

So simulating from inputs is not a workaround — it is the original's own design. The server
runs the same integration math the client runs, from the same inputs, and stays in sync.

## Architecture

```
client control inputs
      │  (ACTION_DUMP 0x09 / ACTION_UPDATE 0x0A)
      ▼
per-client receive thread ──writes──▶ InputTracker (latest control axes per player)
                                            │  (write-only from I/O threads; no physics)
                                            ▼
            ONE 10 Hz Sim Tick (global_game_loop, server_simulation mode)
              for each player: TankSim.step(entity, inputs, dt)   ← phys_sim math
                                            │
                                            ▼
                              GameState  (EntityManager)  ← authoritative pos/vel/rot
                                            │
                              Broadcaster (existing 0x0E / 0x0F entity updates) ─▶ all clients
```

### Concurrency model
- **Per-client receive threads are write-only into `InputTracker`.** They decode action
  packets and store the latest control values for that player. They never touch physics or
  `GameState`.
- **A single central Sim Tick is the sole writer of simulated state.** It reads each player's
  inputs, integrates, and writes `GameState`. Deterministic, single-writer → no shared-state
  races and no per-tick lock contention.

## Components

Each is a small, independently testable unit.

1. **Shared physics package (`wulfsim/`, extracted from `phys_sim/sim/`)**
   - The pure, renderer-agnostic 1:1 port of the client integrators: `integrator`,
     `gravity`, `tuning`, `thrust`, `body`, `constants` (and `terrain`/`suspension` as needed).
   - **Single source of truth** for the exact decompiled math. Both the server and the
     `phys_sim` sandbox import it (phys_sim's imports are repointed; no behavior change there).

2. **`InputTracker`** (`core/input_tracker.py` or formalized on the session/entity)
   - Per-player latest control axes. The receive threads already populate `entity.actions`
     (action-id → value); this formalizes that as the typed input state the sim reads, with a
     clear `get_controls(player)` interface. Exact action-id → control-slot mapping
     (throttle/turn/strafe/…) is resolved during implementation via a Ghidra RE pass +
     a live action-packet capture.

3. **`TankSim`** (`core/sim/tank.py`)
   - Per-player Tank integrator built on the shared physics package: `ComputeControlScalars`
     → `ApplyThrustForces` → gravity → `IntegrateStep`. Reads the player's inputs and the
     `BEHAVIOR` tunables already in `packet_config` (`active_vehicle_physics`, header gravity).
   - "Basic tank" = the **Tank class only** with the **real physics** (so client prediction
     reconciles smoothly instead of fighting the server). Scout/Bomber deferred.

4. **`GameState`** — the existing `EntityManager`. The sim tick writes each player's integrated
   `pos`/`vel`/`rot` here; everything downstream (broadcast, cargo pickup, static anchors)
   already reads it.

5. **Central `SimTick`** — runs inside the existing 10 Hz `global_game_loop` under
   `server_simulation` mode: for each logged-in player, `TankSim.step(...)`; then the existing
   cargo pickup scan and broadcast. This is `server_simulation` fleshed out (today it only
   handles the jump action).

## Integration with existing systems

- **Sync modes:** this *is* `server_simulation`, completed. `client_state_relay` remains as an
  alternate owner-authoritative mode for modified clients; it is untouched.
- **Reconciliation:** the server broadcasts the owner's simulated state back via the `0x0F`
  view-update path; the client reconciles its prediction against it (as the original does).
  Fine-tuning correction cadence/thresholds is deferred — the goal here is correct tracking.
- **Cargo pickup:** once the sim writes real positions to `GameState`, the collision-based
  `cargo_pickup_tick` already built works directly — no relay, no memory bridge.

## Scope

**In scope:** shared physics package extraction; `InputTracker`; `TankSim` (Tank class, exact
physics); wiring the central sim tick into `server_simulation`; broadcasting simulated state.

**Deferred (YAGNI):** Scout/Bomber classes; server-side collision/suspension fidelity tuning;
prediction-reconciliation threshold tuning; client modification (not needed — inputs suffice);
weapons/projectiles.

## Testing

- **Shared package:** the existing `phys_sim` golden tests move with it and must still pass
  (integration math unchanged).
- **`TankSim`:** golden tests — given a fixed input + BEHAVIOR tunables + dt, assert the
  integrated pos/vel matches hand-computed values from the phys_sim integrator.
- **`InputTracker`:** records and exposes latest control axes from decoded action values.
- **`SimTick`:** a server with a logged-in player and a held "forward" input produces a
  changing authoritative position across ticks (mode-gated to `server_simulation`).
- **Regression:** `phys_sim` sandbox still imports and runs after the package extraction.

## Open implementation detail (resolved in the plan, not here)

- **Action-id → control-slot mapping.** Which numbered action ids (1..21) are throttle / turn /
  strafe / etc., and their scaling, confirmed by a Ghidra RE pass against
  `VehicleTuning_ComputeControlScalars` and verified with a live `ACTION_UPDATE` capture.
