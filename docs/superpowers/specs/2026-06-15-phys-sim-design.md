# phys_sim — Faithful Wulfram II Vehicle Physics Sandbox

*Design spec — 2026-06-15. Isolated under `./phys_sim`. A 3D (ursina) sandbox that runs
a 1:1 port of `wulfram2.exe`'s client-side vehicle integrators, with live tuning via both
a REST API and on-screen sliders.*

## Goal

Render a controllable vehicle (Tank → then Scout, Bomber) over heightmap terrain, driven by
the **exact integration math decompiled from the client**, so that editing the same tunables
the server ships in the `BEHAVIOR` (0x24) packet reproduces the real "feel" of the tank.
Both a REST API and ursina sliders mutate one shared tunable set that the physics tick reads
every frame — mirroring the client's "server ships packet → globals read each frame" model.

## Decompiled reference (the load-bearing 1:1 facts)

All addresses are in `wulfram2.exe` (Ghidra project `W2VULK`).

### Integration core
- **`Vec3_IntegratePositionVelocity(dt, pos, vel, accel)`** @ `0x004f10c0`
  - `accel != NULL`: `pos += vel·dt + 0.5·accel·dt²` ; `vel += accel·dt` (per component)
  - `accel == NULL`: `pos += vel·dt` (velocity unchanged)
- **`EntityPhysics_IntegrateLinear(ent, pos, vel, accel, dt)`** @ `0x004f27a0`
  - kinematic flag set (`flags[+4]`): `pos += vel·dt`, return.
  - damping flag clear (`flags[+3]==0`): pass `accel` straight through.
  - damping flag set: `accel_eff = accel − vel·k_friction` (k at struct `+0x78`), then integrate.
- **`EntityPhysics_IntegrateStep(ent, dt)`** @ `0x004f2890`: accumulate sim time, integrate
  rotation (unless flag), then integrate linear. Entity offsets: `+0xc` pos, `+0x18` vel,
  `+0x24` accel/force-accum, `+0x30` euler, `+0x3c`/`+0x48` angular.
- **`EntityPhysics_RunWorldTick(world, elapsed_ms)`** @ `0x004f8550`:
  - `dt = elapsed_ms / 1000.0` (`_DAT_00564f10 = 1000.0`).
  - per entity: clear per-step scratch, apply gravity (`PitchDown(ent, 1.0)`), `IntegrateStep`.
  - then `CollisionContact_ResolveAll`, then **clear force/torque accumulators**
    (`+0x24..+0x2c`, `+0x48..+0x50`). Velocity (`+0x18`) persists across ticks.

### Gravity
- **`EntityPhysics_PitchDown(ent, s)`** @ (named): `accel.z (+0x2c) -= gravity_global · s`.
  Called once per tick with `s = 1.0`. `gravity_global` = `_DAT_005738b8`, written from the
  BEHAVIOR header `gravity_accel` (toml default **100.0**). Gravity is a pure acceleration.

### Control-scalar normalization
- **`VehicleTuningSlot_GetScaledValue(slot, divisor)`** @ `0x004f6420`:
  `v = slot.raw / divisor`; clamp to `[min, 1.0]` where `min = _DAT_00564fc0 = -1.0`.
- **`VehicleTuning_ComputeControlScalars(ctrl)`** @ `0x004f9540`: writes normalized coeffs:
  `+0x74 = −scaled(slot1)` (turn), `+0x78 = −scaled(slot3)` (strafe), `+0x70 = +scaled(slot2)`
  (move), `+0x68 = raw(slot6)`, `+0x6c = raw(slot7)`; each clamped to `[-1.0, 1.0]`.

### Thrust (Tank)
- **`Vehicle_ApplyThrustForces(v)`** @ `0x004f9b10`: builds a body-space thrust vector from
  throttle/strafe inputs × control coeffs × scale factors, rotates to world via
  `Vec3_RotateAroundAxis`, clamps to a max-thrust magnitude (`Math_ClassifyAndCheckResult` =
  vector length), folds a ground-proximity factor, **accumulates onto force `+0x24..+0x2c`**
  and torque `+0x48..+0x50`. (Scout/Bomber: `MedicVehicle_ApplyThrustAndLift` @ `0x004f6ed0`,
  `Vehicle_ApplyAerodynamicForces` @ `0x004f15b0` — ported in later phases.)

### Constants (read from the binary)
| Symbol | Addr | Value | Meaning |
|--------|------|-------|---------|
| `_DAT_00564e28` | `0x564e28` | `0.5` | ½ in `½·a·dt²` |
| `_DAT_00564f10` | `0x564f10` | `1000.0` | tick denominator (ms→s) |
| `_DAT_00564fc0` | `0x564fc0` | `-1.0` | control-coeff clamp floor |
| `_DAT_005738b8` | `0x5738b8` | runtime (100.0) | gravity accel (header) |

## Architecture

```
phys_sim/
  run.py                 # entry: start REST thread + ursina app
  requirements.txt       # ursina, flask
  packets.toml           # embedded tunable defaults (seeded from repo, never writes back)
  sim/                   # PURE, renderer-agnostic, 1:1 port
    constants.py         # the _DAT_* values above
    fixed.py             # 16.16 fixed-point decode (matches write_fixed1616)
    body.py              # PhysicsBody dataclass: pos/vel/force-accum/euler/ang + flags
    integrator.py        # Vec3_IntegratePositionVelocity / IntegrateLinear / IntegrateStep / RunWorldTick
    gravity.py           # PitchDown
    tuning.py            # GetScaledValue + ComputeControlScalars
    thrust.py            # Vehicle_ApplyThrustForces (+ medic/aero later)
    terrain.py           # heightmap sampling
    suspension.py        # ground contact + ceiling (max_altitude)
    vehicle.py           # per-class tick pipeline (Tank/Scout/Bomber)
  tunables.py            # SHARED live registry (name, value, min, max, group) seeded from toml
  api/server.py          # Flask: GET/POST /tunables, GET /state, POST /reset, POST /vehicle/<cls>
  render/app.py          # ursina scene + Wulfram-style input → control inputs
  ui/sliders.py          # ursina sliders bound to the SAME registry
  tests/test_integrator.py
```

### Decisions
1. **Pure core, fixed tick.** `sim/` has no ursina/flask imports. Physics steps at the client
   tick via a fixed-`dt` accumulator in `update()`; render interpolates. Glue that depends on
   engine internals absent from the sandbox (render list, net budget) is stubbed and documented;
   the math stays exact.
2. **One tunable registry, two editors.** `tunables.py` is the single source of truth, seeded
   from `phys_sim/packets.toml` using the repo's `BehaviorConfig` field layout. REST + sliders
   both mutate it; the tick reads it live.
3. **All classes share one integrator.** Tank = thrust+suspension+gravity; Scout adds Medic lift
   + fuel/altitude limiters; Bomber adds aero. Class switch rebinds the per-class pipeline and the
   7/9/11 field counts.
4. **Isolation.** Everything in `./phys_sim`, own `requirements.txt`/venv, embedded toml copy.

### Build order
1. Pure core + Tank, controllable + live-tunable end to end (vertical slice).
2. REST API + sliders wired to the shared registry.
3. Scout (Medic lift + limiters), then Bomber (aero).

## Testing
- `tests/test_integrator.py`: golden tests asserting `Vec3_IntegratePositionVelocity` and
  `IntegrateLinear` match hand-computed constant-acceleration steps (incl. the `0.5·a·dt²` term
  and the friction fold) to float tolerance.
- Manual: drive the tank; confirm hover/gravity/turn feel responds to live tunable edits.
