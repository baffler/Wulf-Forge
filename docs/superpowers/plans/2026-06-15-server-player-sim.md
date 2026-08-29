# Server-Authoritative Player Simulation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the server authoritatively track each player's tank by simulating it from the control inputs the client already sends, reusing the exact `phys_sim` physics, and writing the result into the existing `EntityManager` so the broadcast + cargo systems work against real positions.

**Architecture:** Per-client receive threads only record control inputs. One central 10 Hz sim tick (the existing `global_game_loop`, `server_simulation` mode) integrates every player's tank via the shared `wulfsim` physics package and writes `GameState`. No shared-state races (single writer).

**Tech Stack:** Python 3.12, the existing `phys_sim/sim` physics (extracted to a shared `wulfsim/` package), `EntityManager`, `unittest`/`pytest`.

**Spec:** `docs/superpowers/specs/2026-06-15-server-player-sim-design.md`

## File Structure

- Create `wulfsim/` — shared physics package (the modules moved out of `phys_sim/sim/`): `vec3, constants, fixed, body, gravity, tuning, thrust, integrator, suspension, terrain, vehicle`. Internal relative imports unchanged.
- Modify `phys_sim/sim/*.py` — become one-line re-export shims so the phys_sim sandbox keeps working with zero other changes.
- Create `core/sim/__init__.py`
- Create `core/sim/tunables.py` — `ServerTunables` adapter: maps the server's `BEHAVIOR`/`packet_config` to the `.get()`/`.effective_gravity` interface `Vehicle.step` expects.
- Create `core/sim/inputs.py` — `controls_from_actions(actions)` → `wulfsim.vehicle.Inputs` (the action-id → throttle/turn/strafe mapping).
- Create `core/sim/tank.py` — `TankSim`: owns a per-player `Vehicle` + flat terrain + `ServerTunables`; `step(entity, dt)` reads `entity.actions`, integrates, writes `entity.pos/vel/rot`.
- Modify `main.py` — add `player_sim_tick(server)` and call it in `global_game_loop` under `server_simulation`.
- Tests: `tests/test_server_tunables.py`, `tests/test_sim_inputs.py`, `tests/test_tank_sim.py`, `tests/test_player_sim_tick.py`.

**Run tests with:** `python -m pytest tests -q -p no:cacheprovider`

---

### Task 1: Extract physics into shared `wulfsim/` package

**Files:**
- Create: `wulfsim/` (moved modules) + `wulfsim/__init__.py`
- Modify: `phys_sim/sim/*.py` (shims), `phys_sim/sim/__init__.py`

- [ ] **Step 1: Move the physics modules to `wulfsim/`**

```bash
cd "C:/Users/balsa/desktop/WulframII/Wulf-Forge"
mkdir -p wulfsim
for m in vec3 constants fixed body gravity tuning thrust integrator suspension terrain vehicle; do
  git mv "phys_sim/sim/$m.py" "wulfsim/$m.py"
done
printf '"""Shared 1:1 port of the wulfram2.exe vehicle physics (see phys_sim spec)."""\n' > wulfsim/__init__.py
```

- [ ] **Step 2: Replace `phys_sim/sim/` with re-export shims**

```bash
cd "C:/Users/balsa/desktop/WulframII/Wulf-Forge"
for m in vec3 constants fixed body gravity tuning thrust integrator suspension terrain vehicle; do
  printf 'from wulfsim.%s import *  # noqa: F401,F403  (shim: real code lives in wulfsim/)\n' "$m" > "phys_sim/sim/$m.py"
done
cat > phys_sim/sim/__init__.py <<'EOF'
"""Compatibility shim: phys_sim.sim now re-exports the shared wulfsim package."""
from wulfsim import (  # noqa: F401
    vec3, constants, fixed, body, gravity, tuning,
    thrust, integrator, suspension, terrain, vehicle,
)
EOF
```

- [ ] **Step 3: Verify the server can import wulfsim and phys_sim still imports sim**

Run:
```bash
python -c "from wulfsim.vehicle import Vehicle, Inputs; from wulfsim import integrator; print('wulfsim OK')"
python -c "import sys; sys.path.insert(0,'phys_sim'); from sim.vehicle import Vehicle, Inputs, VEHICLE_KINDS; from sim import integrator, gravity; print('phys_sim shim OK')"
```
Expected: both print OK with no ImportError.

- [ ] **Step 4: Verify phys_sim's own tests still pass**

Run: `cd phys_sim && python -m pytest tests -q -p no:cacheprovider && cd ..`
Expected: the phys_sim integrator golden tests PASS unchanged (physics math is byte-identical; only the import path moved).

- [ ] **Step 5: Commit**

```bash
git add wulfsim phys_sim/sim
git commit -m "refactor: extract phys_sim/sim into shared wulfsim package"
```

---

### Task 2: `ServerTunables` adapter

Maps the server's real `BEHAVIOR` config to the duck-typed registry `Vehicle.step` reads. EXACT values come from `packet_config`; MODEL knobs (sandbox-only scales) use the phys_sim defaults.

**Files:**
- Create: `core/sim/__init__.py` (empty)
- Create: `core/sim/tunables.py`
- Test: `tests/test_server_tunables.py`

- [ ] **Step 1: Write the failing test**

```python
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.packets.packet_config import PacketConfig
from core.sim.tunables import ServerTunables


class ServerTunablesTests(unittest.TestCase):
    def setUp(self):
        self.t = ServerTunables(PacketConfig())

    def test_exact_values_come_from_behavior(self):
        avp = PacketConfig().behavior.active_vehicle_physics
        self.assertAlmostEqual(self.t.get("turn_adjust"), avp.turn_adjust)
        self.assertAlmostEqual(self.t.get("move_adjust"), avp.move_adjust)
        self.assertAlmostEqual(self.t.get("strafe_adjust"), avp.strafe_adjust)
        self.assertAlmostEqual(self.t.get("max_velocity"), avp.max_velocity)
        self.assertAlmostEqual(self.t.get("max_altitude"), avp.max_altitude)

    def test_effective_gravity_is_force_times_pct(self):
        b = PacketConfig().behavior
        expected = b.header.gravity_force * b.active_vehicle_physics.gravity_pct
        self.assertAlmostEqual(self.t.effective_gravity, expected)

    def test_model_knobs_have_defaults(self):
        for k in ("thrust_scale", "torque_scale", "max_thrust", "hover_spring",
                  "hover_damp", "angular_damp", "control_divisor"):
            self.assertGreater(self.t.get(k), 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_tunables.py -q -p no:cacheprovider`
Expected: FAIL — `No module named 'core.sim.tunables'`.

- [ ] **Step 3: Implement `ServerTunables`**

Create `core/sim/__init__.py` (empty). Create `core/sim/tunables.py`:

```python
"""Adapter exposing the server's BEHAVIOR config via the registry interface
that wulfsim.vehicle.Vehicle.step expects (.get(name) / .effective_gravity).

EXACT tunables are pulled from packet_config (the real client values shipped in
the BEHAVIOR 0x24 packet). MODEL knobs are sandbox force/scale models not present
in the packet; they use the phys_sim defaults until decompiled.
"""
from __future__ import annotations

from network.packets.packet_config import PacketConfig

# Sandbox model knobs (mirror phys_sim/tunables.py defaults).
_MODEL_DEFAULTS = {
    "control_divisor": 100.0,
    "thrust_scale": 120.0,
    "torque_scale": 100.0,
    "max_thrust": 400.0,
    "hover_spring": 200.0,
    "hover_damp": 28.0,
    "angular_damp": 4.0,
}


class ServerTunables:
    def __init__(self, cfg: PacketConfig):
        avp = cfg.behavior.active_vehicle_physics
        vp = cfg.behavior.vehicle_physics
        self._gravity_force = cfg.behavior.header.gravity_force
        self._gravity_pct = avp.gravity_pct
        self._exact = {
            "gravity_accel": self._gravity_force,
            "gravity_pct": avp.gravity_pct,
            "ground_friction": vp.ground_friction,
            "turn_adjust": avp.turn_adjust,
            "move_adjust": avp.move_adjust,
            "strafe_adjust": avp.strafe_adjust,
            "max_velocity": avp.max_velocity,
            "hover_height": avp.tank_hover_height,
            "max_altitude": avp.max_altitude,
        }

    def get(self, name: str) -> float:
        if name in self._exact:
            return self._exact[name]
        return _MODEL_DEFAULTS[name]

    @property
    def effective_gravity(self) -> float:
        return self._gravity_force * self._gravity_pct
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_tunables.py -q -p no:cacheprovider`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/sim/__init__.py core/sim/tunables.py tests/test_server_tunables.py
git commit -m "feat: ServerTunables adapter mapping BEHAVIOR config to the sim registry"
```

---

### Task 3: Input mapping (`controls_from_actions`)

Convert the player's decoded action values (`GameEntity.actions`, an `{action_id: value}` dict the receive threads already populate) into `wulfsim.vehicle.Inputs`. The exact action-id assignment is **confirmed in Task 6**; this task uses the documented starting mapping (turn=1, throttle=2, strafe=3 — matching the binary's slot order 1=turn,2=move,3=strafe) and is structured so only the constant map changes later.

**Files:**
- Create: `core/sim/inputs.py`
- Test: `tests/test_sim_inputs.py`

- [ ] **Step 1: Write the failing test**

```python
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.sim.inputs import controls_from_actions, ACTION_TURN, ACTION_THROTTLE, ACTION_STRAFE


class InputMappingTests(unittest.TestCase):
    def test_maps_action_axes_to_inputs(self):
        actions = {ACTION_TURN: 1.0, ACTION_THROTTLE: -0.5, ACTION_STRAFE: 0.25}
        inp = controls_from_actions(actions)
        self.assertAlmostEqual(inp.turn, 1.0)
        self.assertAlmostEqual(inp.throttle, -0.5)
        self.assertAlmostEqual(inp.strafe, 0.25)

    def test_missing_actions_default_zero(self):
        inp = controls_from_actions({})
        self.assertEqual((inp.throttle, inp.strafe, inp.turn, inp.vertical), (0.0, 0.0, 0.0, 0.0))

    def test_clamps_to_unit_range(self):
        inp = controls_from_actions({ACTION_THROTTLE: 5.0, ACTION_TURN: -9.0})
        self.assertAlmostEqual(inp.throttle, 1.0)
        self.assertAlmostEqual(inp.turn, -1.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sim_inputs.py -q -p no:cacheprovider`
Expected: FAIL — `No module named 'core.sim.inputs'`.

- [ ] **Step 3: Implement `controls_from_actions`**

Create `core/sim/inputs.py`:

```python
"""Map decoded client action axes -> wulfsim Inputs.

GameEntity.actions is {action_id: value} populated by the action-packet handlers
(0x09/0x0A). Action ids 1..21; the binary's control slot order is 1=turn, 2=move,
3=strafe (VehicleTuning_ComputeControlScalars). These ids are CONFIRMED in Task 6;
change only this constant map if RE corrects them.
"""
from __future__ import annotations

from wulfsim.vehicle import Inputs

ACTION_TURN = 1
ACTION_THROTTLE = 2
ACTION_STRAFE = 3
ACTION_VERTICAL = 4  # provisional (flyers); unused for Tank


def _clamp_unit(v: float) -> float:
    return -1.0 if v < -1.0 else 1.0 if v > 1.0 else v


def controls_from_actions(actions: dict) -> Inputs:
    g = lambda aid: _clamp_unit(float(actions.get(aid, 0.0)))
    return Inputs(
        throttle=g(ACTION_THROTTLE),
        strafe=g(ACTION_STRAFE),
        turn=g(ACTION_TURN),
        vertical=g(ACTION_VERTICAL),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sim_inputs.py -q -p no:cacheprovider`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/sim/inputs.py tests/test_sim_inputs.py
git commit -m "feat: map client action axes to wulfsim Inputs (provisional ids)"
```

---

### Task 4: `TankSim`

Owns a per-player `Vehicle` and integrates it from the entity's actions, writing pos/vel/yaw back onto the `GameEntity`. Uses a flat terrain stand-in (real terrain sampling deferred per spec).

**Files:**
- Create: `core/sim/tank.py`
- Test: `tests/test_tank_sim.py`

- [ ] **Step 1: Write the failing test**

```python
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from network.packets.packet_config import PacketConfig
from core.entity import GameEntity
from core.sim.tank import TankSim
from core.sim.inputs import ACTION_THROTTLE


class TankSimTests(unittest.TestCase):
    def setUp(self):
        self.sim = TankSim(PacketConfig())

    def test_idle_tank_does_not_drift_horizontally(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        for _ in range(20):
            self.sim.step(ent, dt=0.1)
        self.assertAlmostEqual(ent.pos[0], 0.0, places=3)
        self.assertAlmostEqual(ent.pos[1], 0.0, places=3)

    def test_throttle_moves_tank(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        ent.actions = {ACTION_THROTTLE: 1.0}
        start = ent.pos
        for _ in range(20):
            self.sim.step(ent, dt=0.1)
        moved = abs(ent.pos[0] - start[0]) + abs(ent.pos[1] - start[1])
        self.assertGreater(moved, 1.0, "throttle should move the tank")

    def test_writes_velocity_back_to_entity(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        ent.actions = {ACTION_THROTTLE: 1.0}
        self.sim.step(ent, dt=0.1)
        self.assertEqual(len(ent.vel), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tank_sim.py -q -p no:cacheprovider`
Expected: FAIL — `No module named 'core.sim.tank'`.

- [ ] **Step 3: Implement `TankSim`**

Create `core/sim/tank.py`:

```python
"""Per-player Tank simulation: integrate the client's inputs into authoritative state.

Wraps wulfsim.vehicle.Vehicle (the exact decompiled Tank pipeline). Terrain is a flat
stand-in for now (real heightmap sampling deferred per the design spec). One Vehicle is
kept per entity net_id; each step reads the entity's actions and writes pos/vel/yaw back.
"""
from __future__ import annotations

from network.packets.packet_config import PacketConfig
from core.entity import GameEntity, UpdateMask
from core.sim.tunables import ServerTunables
from core.sim.inputs import controls_from_actions
from wulfsim.vehicle import Vehicle


class _FlatTerrain:
    """Minimal HeightMap stand-in: constant ground height."""
    def __init__(self, ground_z: float = 0.0):
        self.ground_z = ground_z

    def height_at(self, x: float, y: float) -> float:
        return self.ground_z


class TankSim:
    def __init__(self, cfg: PacketConfig, ground_z: float = 0.0):
        self.tunables = ServerTunables(cfg)
        self.terrain = _FlatTerrain(ground_z)
        self._vehicles: dict[int, Vehicle] = {}

    def _vehicle_for(self, ent: GameEntity) -> Vehicle:
        v = self._vehicles.get(ent.net_id)
        if v is None:
            v = Vehicle(kind="tank")
            v.body.pos.set(ent.pos[0], ent.pos[1], ent.pos[2])
            self._vehicles[ent.net_id] = v
        return v

    def forget(self, net_id: int) -> None:
        self._vehicles.pop(net_id, None)

    def step(self, ent: GameEntity, dt: float) -> None:
        v = self._vehicle_for(ent)
        inp = controls_from_actions(ent.actions)
        v.step(dt, inp, self.tunables, self.terrain)
        b = v.body
        ent.pos = (b.pos.x, b.pos.y, b.pos.z)
        ent.vel = (b.vel.x, b.vel.y, b.vel.z)
        ent.rot = (ent.rot[0], ent.rot[1], b.euler.z)
        ent.mark_dirty(UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tank_sim.py -q -p no:cacheprovider`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/sim/tank.py tests/test_tank_sim.py
git commit -m "feat: TankSim integrates a player's tank from inputs into entity state"
```

---

### Task 5: Wire the central sim tick into the game loop

Add `player_sim_tick(server)` (testable like `cargo_pickup_tick`) and call it in `global_game_loop` under `server_simulation`, before the cargo scan. The server gets one `TankSim` instance.

**Files:**
- Modify: `main.py` (server init: add `self.tank_sim`; loop: call `player_sim_tick`)
- Test: `tests/test_player_sim_tick.py`

- [ ] **Step 1: Write the failing test**

```python
import sys, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from network.packets.packet_config import PacketConfig
from core.entity import GameEntity
from core.sim.tank import TankSim
from core.sim.inputs import ACTION_THROTTLE


class PlayerSimTickTests(unittest.TestCase):
    def test_tick_advances_each_player_from_inputs(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        ent.actions = {ACTION_THROTTLE: 1.0}
        session = SimpleNamespace(entity=ent, player_id=1, is_logged_in=True)
        server = SimpleNamespace(sessions=[session], tank_sim=TankSim(PacketConfig()))

        start = ent.pos
        for _ in range(20):
            main.player_sim_tick(server, dt=0.1)
        moved = abs(ent.pos[0] - start[0]) + abs(ent.pos[1] - start[1])
        self.assertGreater(moved, 1.0)

    def test_tick_skips_players_without_entity(self):
        server = SimpleNamespace(
            sessions=[SimpleNamespace(entity=None, player_id=2, is_logged_in=True)],
            tank_sim=TankSim(PacketConfig()),
        )
        main.player_sim_tick(server, dt=0.1)  # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_player_sim_tick.py -q -p no:cacheprovider`
Expected: FAIL — `module 'main' has no attribute 'player_sim_tick'`.

- [ ] **Step 3: Add `TankSim` to the server and implement `player_sim_tick`**

In `main.py`, add the import near the other `core.sim`/cargo imports:

```python
from core.sim.tank import TankSim
```

In `WulframServerContext.__init__`, right after `self.cargo = CargoSystem(...)`:

```python
        self.tank_sim = TankSim(self.packet_cfg)
```

Add the module-level function next to `cargo_pickup_tick` (above `global_game_loop`):

```python
def player_sim_tick(server: WulframServerContext, dt: float) -> None:
    """Integrate every in-world player's tank from its inputs (server-authoritative).

    Single writer of simulated state; runs only in server_simulation mode.
    """
    for session in server.sessions:
        if session.entity and session.is_logged_in:
            server.tank_sim.step(session.entity, dt)
```

- [ ] **Step 4: Call it in the loop under `server_simulation`**

In `global_game_loop`, the loop computes per-iteration timing. Replace the jump-only `should_run_server_simulation` block's body so the sim tick runs first. Find:

```python
        if should_run_server_simulation(server):
            # --- 1. Process Inputs (Physics/Actions) ---
            # Apply actions (jump/hover) for every active player
            for session in server.sessions:
```

Insert immediately after the `if should_run_server_simulation(server):` line:

```python
            # --- 1. Server-authoritative tank simulation ---
            player_sim_tick(server, dt=FRAME_TIME)
```

(The existing jump loop stays; it now layers on top of the integrated state.)

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_player_sim_tick.py -q -p no:cacheprovider`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full suite + boot check**

Run:
```bash
python -m pytest tests -q -p no:cacheprovider
python -c "import main; s=main.WulframServerContext(); s.stop_update_event.set(); print('boot OK; tank_sim=', type(s.tank_sim).__name__)"
```
Expected: full suite PASS; boot prints `boot OK; tank_sim= TankSim`.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_player_sim_tick.py
git commit -m "feat: run server-authoritative tank sim tick in server_simulation mode"
```

---

### Task 6: Confirm the action-id → control-axis mapping (Ghidra + live capture)

The mapping in Task 3 is the binary's documented slot order (1=turn, 2=move, 3=strafe) but the **action-table id** for each axis must be confirmed. This task verifies/corrects `core/sim/inputs.py`'s constants.

**Files:**
- Modify: `core/sim/inputs.py` (only the `ACTION_*` constants, if RE corrects them)
- Test: `tests/test_sim_inputs.py` (update ids if they change)

- [ ] **Step 1: RE the action ids in Ghidra**

Decompile `Net_SendActionDump @ 0x0046c790` and `VehicleTuning_ComputeControlScalars @ 0x004f9540`. Determine which numbered action-table index (the `&DAT_00678e94[1..0x15]` axes written by the dump) feeds the turn / move(throttle) / strafe control slots. Record the concrete id → axis assignment.

- [ ] **Step 2: Cross-check with a live action capture**

Temporarily set `log_all_opcodes = true` in `config.toml`, run the server, drive the tank (forward / turn / strafe one at a time), and read the `ACTION_UPDATE (0x0A)` entries in the latest `logs/wulf-forge-*.log` to see which action id changes for each control. Confirm against Step 1.

- [ ] **Step 3: Update the constants if needed**

If the confirmed ids differ from `ACTION_TURN=1, ACTION_THROTTLE=2, ACTION_STRAFE=3`, edit those constants in `core/sim/inputs.py` and the ids in `tests/test_sim_inputs.py`. Add a one-line comment citing the confirming function address.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_sim_inputs.py tests/test_tank_sim.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sim/inputs.py tests/test_sim_inputs.py
git commit -m "fix: confirm action-id to control-axis mapping from Ghidra + capture"
```

---

### Task 7: Default to server simulation + manual verification

**Files:**
- Modify: `config.toml` (`[sync] mode`)

- [ ] **Step 1: Set the sync mode**

In `config.toml`, set:

```toml
[sync]
mode = "server_simulation"
```

- [ ] **Step 2: Manual in-game verification**

Run the server, connect the client, spawn, and drive. Confirm with `/s cargostatus` that your server-side `pos` now **changes as you move** (no longer frozen at spawn). Drive onto a cargo box and confirm pickup fires (`carrying=True`). This is the end-to-end payoff: real positions → working collision pickup.

- [ ] **Step 3: Commit**

```bash
git add config.toml
git commit -m "chore: default to server_simulation mode"
```

---

## Self-Review Notes

- **Spec coverage:** shared package (Task 1), InputTracker (Task 3), TankSim (Task 4), central sim tick + server_simulation (Task 5), action mapping resolved-in-plan (Task 6), cargo payoff (Task 7 verification). Reconciliation tuning, Scout/Bomber, real terrain — explicitly deferred per spec.
- **Type consistency:** `controls_from_actions` → `Inputs`; `TankSim.step(ent, dt)`; `player_sim_tick(server, dt)`; `ServerTunables.get/effective_gravity` matches `Vehicle.step`'s usage.
- **Deferred terrain:** `_FlatTerrain.height_at` returns a constant; the design notes real terrain sampling is later work (so altitude-sensitive physics like hover use a flat ground for now).
