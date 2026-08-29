# phys_sim — Wulfram II vehicle physics sandbox

A self-contained 3D sandbox that runs a **port of the actual `wulfram2.exe` client vehicle
physics**, with **live tuning via both a REST API and on-screen sliders**, heightmap terrain,
and an optional **live-attach / drift** mode that reads a running game and measures how far the
sim diverges from the real client.

Everything lives under `./phys_sim` and never writes back to the rest of the repo.

## Install & run

```bash
cd phys_sim
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
python run.py
```

- `python run.py` — sandbox window + REST API (port 8077) + sliders
- `python run.py --no-api` — no REST server
- `python run.py --attach --entity-ptr 0x6XXXXX,0x0` — attach to a running `wulfram2.exe`

### Controls
`W/S` throttle · `A/D` strafe · `Q/E` turn · `Space/Ctrl` up/down (flyers) ·
`1` Tank `2` Scout `3` Bomber · `R` reset

### REST API (default `http://127.0.0.1:8077`)
| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/tunables` | full registry (value, range, group, kind) |
| GET  | `/tunables/<name>` | one value |
| POST | `/tunables` | bulk live patch `{"gravity_accel": 80, ...}` |
| GET  | `/state` | live pos/vel/yaw/speed + effective gravity |
| POST | `/reset` | respawn the vehicle |
| POST | `/vehicle/<tank\|scout\|bomber>` | switch class |
| GET  | `/drift` | live-vs-sim drift report (attach mode) |

The sliders, the REST API, and the physics tick all share **one** `Tunables` object, so an edit
from any source takes effect on the next tick — mirroring the client model where the server ships
one `BEHAVIOR(0x24)` packet of tunables that the physics loop reads every frame.

## Fidelity: what is 1:1 vs. still a model

Sliders/`/tunables` tag each value `EXACT` (green) or `MODEL` (orange).

**Bit-exact ports (verified against the binary + unit tests in `tests/`):**
- **Integrator** — `Vec3_IntegratePositionVelocity` (0x004f10c0), `EntityPhysics_IntegrateLinear`
  (0x004f27a0): `pos += v·dt + 0.5·a·dt²`, `v += a·dt`, friction fold `a_eff = a − v·k`, kinematic
  branch. Constant `0.5` = `_DAT_00564e28`.
- **Tick rate** — `dt = elapsed_ms / 1000.0` (`_DAT_00564f10`).
- **Gravity** — `EntityPhysics_PitchDown`: `accel.z −= gravity` (pure acceleration).
- **Control normalization** — `VehicleTuningSlot_GetScaledValue` (0x004f6420) /
  `VehicleTuning_ComputeControlScalars` (0x004f9540): `coeff = raw/divisor` clamped to `[-1, 1]`
  (`_DAT_00564fc0 = -1.0`), turn & strafe negated.

**Structural models (right shape, exact constants still being reverse-engineered):**
- **Thrust/torque** — `Vehicle_ApplyThrustForces` (0x004f9b10) structure is reproduced, but the
  chassis scale factors (`+0x58/+0x5c`) are exposed as `thrust_scale`/`torque_scale` knobs.
- **Suspension hover** — a PD spring/damper (`hover_spring`/`hover_damp`) standing in for the
  exact contact response in `CollisionContact_ResolveAll` (0x004f8510).
- **Rotation** — yaw integrated with a tunable `angular_damp` pending the exact
  `EntityPhysics_IntegrateRotation` port.

The full ports of these three are the next step (the RE pass was paused on a session limit). The
**drift tool below is the instrument for validating them.**

## Live attach & drift

`live/attach.py` reads a running `wulfram2.exe` via `pymem` at the confirmed entity-physics
offsets (`+0x0c` pos, `+0x18` vel, `+0x24` accel, `+0x30` euler, …) and the gravity global
(`0x5738b8`). `live/drift.py` then, each frame, predicts the next live position from the previous
live read using **only the ported integrator** and compares it to what the client actually
produced.

Because the live `accel` accumulator already contains the client's own thrust + gravity +
suspension for that tick, this **isolates the integration math**: near-zero `pos_err`/`vel_err`
proves the integrator port is 1:1; any residual localizes the discrepancy (missing `0.5·a·dt²`,
wrong `dt`, or read phase). Once thrust/suspension are fully ported, switch `DriftTracker.mode` to
`"full"` for end-to-end validation.

You must supply the player-entity pointer chain via `--entity-ptr` (find it with Cheat
Engine/Ghidra — a global holding the local ship object). Until then attach is inert and the sim
runs standalone. Drift is most meaningful when the in-game vehicle is **idle/coasting** (no pilot
input), which isolates gravity/suspension/friction/integration error.

## Layout
```
sim/        pure, renderer-agnostic 1:1 port (no ursina/flask imports)
tunables.py shared live registry (single source of truth)
world.py    fixed-timestep driver
api/        Flask REST server (background thread)
ui/         ursina sliders bound to the registry
render/     ursina scene + input
live/       attach + drift tooling
tests/      integrator golden tests
```

Run the exact-math tests any time: `python tests/test_integrator.py`.
